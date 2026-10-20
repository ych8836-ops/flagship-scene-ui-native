from __future__ import annotations

import copy
import logging
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

import comfy.model_management
import comfy.nested_tensor
import comfy.utils
import node_helpers
from comfy.patcher_extension import WrappersMP

from .minimax_h3 import require_native_minimax_h3


LOG = logging.getLogger(__name__)
WRAPPER_KEY = "h3_acr_sparse_time_v1"
FPS = 24.0
AUDIO_LATENT_FPS = 40.0


def _align_frame_count(value: int) -> int:
    value = max(5, int(value))
    while value % 17 != 5:
        value += 1
    return value


def _video_latent_t(frame_count: int) -> int:
    return 2 if frame_count <= 5 else ((frame_count - 5) // 17) * 5 + 2


def _resize(image, width: int, height: int, crop: str):
    samples = image[..., :3].movedim(-1, 1)
    samples = comfy.utils.common_upscale(samples, width, height, "lanczos", crop)
    return samples.movedim(1, -1)


def _source_frames(profile: str) -> int:
    value = str(profile)
    if value.startswith("fast"):
        return 56
    if value.startswith("action"):
        return 90
    return 73


def _empty_sparse_av_latent(width: int, height: int, full_length: int, source_profile: str):
    full_frames = _align_frame_count(full_length)
    source_frames = _source_frames(source_profile)
    video_t = _video_latent_t(source_frames)
    audio_t = round((full_frames / FPS) * AUDIO_LATENT_FPS)
    device = comfy.model_management.intermediate_device()
    video = torch.zeros([1, 24, video_t, height // 16, width // 16], device=device)
    audio = torch.zeros([1, 32, 2, audio_t], device=device)
    latent = {"samples": comfy.nested_tensor.NestedTensor((video, audio))}
    return latent, full_frames, source_frames


class H3ACRSparseImageToVideo:
    """Generate fewer video frames while retaining the full H3 audio duration."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True}),
                "width": ("INT", {"default": 1344, "min": 32, "max": 16384, "step": 32}),
                "height": ("INT", {"default": 768, "min": 32, "max": 16384, "step": 32}),
                "length": ("INT", {"default": 124, "min": 5, "max": 3600, "step": 17}),
                "source_profile": (
                    ["action 90 frames", "quality 73 frames", "fast 56 frames"],
                    {"default": "quality 73 frames"},
                ),
            },
            "optional": {
                "first_frame": ("IMAGE",),
                "last_frame": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "LATENT", "INT", "INT")
    RETURN_NAMES = ("positive", "latent", "target_frames", "source_frames")
    FUNCTION = "execute"
    CATEGORY = "conditioning/minimax"

    def execute(self, clip, vae, prompt, width, height, length, source_profile,
                first_frame=None, last_frame=None):
        latent, full_frames, source_frames = _empty_sparse_av_latent(
            int(width), int(height), int(length), source_profile
        )
        images = []
        keyframes = []
        if first_frame is not None:
            img = _resize(first_frame[:1], int(width), int(height), "disabled")
            images.append(img)
            keyframes.append({"resolved_frame_index": 0, "image": img})
        if last_frame is not None:
            img = _resize(last_frame[:1], int(width), int(height), "center")
            images.append(img)
            keyframes.append({"resolved_frame_index": source_frames - 1, "image": img})

        tokens = clip.tokenize(prompt, images=images)
        cond = clip.encode_from_tokens_scheduled(tokens)
        values = {
            "minimax_sparse_target_frames": full_frames,
            "minimax_sparse_source_frames": source_frames,
        }
        if keyframes:
            for keyframe in keyframes:
                keyframe["latent"] = vae.encode(keyframe.pop("image"))
            values.update({
                "minimax_keyframes": keyframes,
                "minimax_frame_count": source_frames,
            })
        cond = node_helpers.conditioning_set_values(cond, values)
        LOG.info(
            "H3 ACR Sparse FPS latent: video=%d frames, audio duration=%d/24 sec, target=%d frames",
            source_frames, full_frames, full_frames,
        )
        return cond, latent, full_frames, source_frames


def _scale_sparse_layout(layout, target_audio_t: int):
    if getattr(layout, "_h3_acr_sparse_scaled", False):
        return layout
    video_segment = next(((a, b) for a, b, kind in layout.segments if kind == "video"), None)
    audio_segment = next(((a, b) for a, b, kind in layout.segments if kind == "audio"), None)
    if video_segment is None or audio_segment is None:
        return layout
    va, vb = video_segment
    aa, _ = audio_segment
    origin = float(layout.position_ids[aa, 0])
    video_t = layout.position_ids[va:vb, 0]
    extent = float(video_t.max().item() - origin)
    # Last video token is the beginning of its temporal cell. Match it to the
    # full audio horizon while preserving the native H3 cell-end margin.
    desired_extent = max(1.0, float(target_audio_t) - 7.0)
    if extent <= 0.0:
        return layout
    scale = desired_extent / extent
    if scale <= 1.08:
        layout._h3_acr_sparse_scaled = True
        layout._h3_acr_sparse_scale = 1.0
        return layout
    layout.position_ids[va:vb, 0] = origin + (video_t - origin) * scale
    for a, b, kind in layout.segments:
        if kind == "cond":
            t = layout.position_ids[a:b, 0]
            after_origin = t > origin + 1e-6
            if bool(after_origin.any()):
                layout.position_ids[a:b, 0] = torch.where(
                    after_origin, origin + (t - origin) * scale, t
                )
    layout._h3_acr_sparse_scaled = True
    layout._h3_acr_sparse_scale = scale
    LOG.info("H3 ACR Sparse FPS temporal scale active: %.4fx", scale)
    return layout


def _sparse_time_wrapper(executor, x, timestep, context, transformer_options={}, **kwargs):
    payload = kwargs.get("minimax_payload") or {}
    layout = payload.get("layout")
    if layout is not None and isinstance(x, (list, tuple)) and len(x) == 2:
        audio_t = int(x[1].shape[-1])
        _scale_sparse_layout(layout, audio_t)
    return executor(x, timestep, context, transformer_options, **kwargs)


class H3ACRSparseTimePatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "enabled": ("BOOLEAN", {"default": True})}}

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "apply"
    CATEGORY = "sampling/spectrum"

    def apply(self, model, enabled=True):
        if not enabled:
            return (model,)
        require_native_minimax_h3(model)
        patched = model.clone()
        patched.add_wrapper_with_key(WrappersMP.DIFFUSION_MODEL, WRAPPER_KEY, _sparse_time_wrapper)
        return (patched,)


class H3ACRSparseStage1Patch:
    """Sparse timeline plus the bounded seven-actual/five-forecast ACR path."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "enabled": ("BOOLEAN", {"default": True}),
                "mode": (["safe", "action", "balanced", "fast"], {"default": "safe"}),
            },
            "optional": {"debug": ("BOOLEAN", {"default": False})},
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "apply"
    CATEGORY = "sampling/spectrum"

    def apply(self, model, enabled=True, mode="safe", debug=False):
        if not enabled:
            return (model,)
        from .config import SpectrumH3Config
        from .minimax_h3 import install_h3_wrapper
        from .runtime import SpectrumH3Runtime
        from .sampling import install_sampler_wrappers

        presets = {
            "safe": (0.30, 3.0, 0.50, 3, "safe"),
            "action": (0.30, 3.0, 0.50, 2, "safe"),
            "balanced": (0.36, 2.5, 0.65, 2, "balanced"),
            "fast": (0.42, 2.0, 0.80, 2, "fast"),
        }
        resolved = str(mode).lower()
        if resolved not in presets:
            raise ValueError("Sparse Stage 1 mode must be safe, action, balanced, or fast")
        blend, window, flex, tail_actual, acr_mode = presets[resolved]
        patched = H3ACRSparseTimePatch().apply(model, True)[0]
        config = SpectrumH3Config(
            enabled=True,
            blend_weight=blend,
            degree=1,
            ridge_lambda=0.10,
            window_size=window,
            flex_window=flex,
            warmup_steps=1,
            tail_actual_steps=tail_actual,
            max_history=4,
            history_storage="vram",
            bootstrap_first_forecast=True,
            anchor_residual_feedback=resolved != "action",
            selective_rollback_correction=False,
            offline_smoothing_replay=False,
            audio_blend_weight=0.0,
            offline_archive_storage="system_ram",
            model_aware_mode="off",
            model_aware_risk_threshold=0.65,
            model_aware_trust_shrinkage=False,
            model_aware_replay_generic_correction=False,
            generic_correction_mode="coordinate_rls",
            generic_correction_attenuation="no_attenuation",
            generic_correction_limiter="hard_clip",
            generic_correction_limit=0.40,
            debug=bool(debug),
            acr_mode=acr_mode,
        ).validate()
        runtime = SpectrumH3Runtime(config)
        install_sampler_wrappers(patched, runtime)
        install_h3_wrapper(patched)
        return (patched,)


class H3ACRNvidiaFrameRestore:
    """Reconstruct a sparse H3 frame batch with NVIDIA NvOFFRUC on CUDA."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "target_frames": ("INT", {"default": 124, "min": 5, "max": 3600, "step": 1}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "status")
    FUNCTION = "restore"
    CATEGORY = "image/video"

    def restore(self, images, target_frames):
        if images.ndim != 4 or images.shape[0] < 2:
            return images, "Sparse FPS restore skipped: fewer than two frames"
        node_root = Path(__file__).resolve().parents[2] / "ComfyUI-RTX-Video-Restoration"
        if str(node_root) not in sys.path:
            sys.path.insert(0, str(node_root))
        from nvfruc_runtime import NvFRUCStream, find_nvfruc_dll

        source_count, height, width, _ = images.shape
        dll_path = find_nvfruc_dll(node_root)
        restored = []
        # Measure only three scalars per frame on CUDA, then use a wide robust
        # temporal median to catch short H3 exposure/chroma bursts. The actual
        # pixel correction stays on CUDA and is bounded per RGB channel.
        channel_means = []
        for index in range(source_count):
            frame = images[index, ..., :3].to(device="cuda", dtype=torch.float32, non_blocking=True)
            channel_means.append(frame.mean(dim=(0, 1)).cpu())
        channel_means = torch.stack(channel_means)
        target_means = torch.empty_like(channel_means)
        for index in range(source_count):
            lo, hi = max(0, index - 8), min(source_count, index + 9)
            target_means[index] = channel_means[lo:hi].median(dim=0).values
        ratios = target_means / channel_means.clamp_min(1.0 / 255.0)
        correction_mask = (ratios - 1.0).abs().amax(dim=1) > 0.06
        current_unit = channel_means.clamp(0.01, 0.99)
        target_unit = target_means.clamp(0.01, 0.99)
        gamma = torch.log(target_unit) / torch.log(current_unit)
        gamma = torch.where(correction_mask[:, None], gamma.clamp(0.55, 1.80), torch.ones_like(gamma))
        weights = torch.tensor([0.2126, 0.7152, 0.0722], dtype=torch.float32, device="cuda")

        def gamma_adjust(frame_index):
            frame = images[frame_index, ..., :3].to(device="cuda", dtype=torch.float32, non_blocking=True)
            return frame.clamp(0.0, 1.0).pow(gamma[frame_index].to("cuda").view(1, 1, 3))

        def repair_isolated_chroma(current, before, after, agreement_limit, deviation_limit, saturation_margin):
            """Remove one-frame colour fringes while retaining the current frame's luminance and geometry."""
            current_y = (current * weights).sum(-1, keepdim=True)
            before_y = (before * weights).sum(-1, keepdim=True)
            after_y = (after * weights).sum(-1, keepdim=True)
            current_chroma = current / current_y.clamp_min(0.08)
            before_chroma = before / before_y.clamp_min(0.08)
            after_chroma = after / after_y.clamp_min(0.08)
            consensus = (before_chroma + after_chroma) * 0.5
            agreement = (before_chroma - after_chroma).abs().amax(dim=-1) < agreement_limit
            deviation = (current_chroma - consensus).abs().amax(dim=-1)
            current_saturation = (current_chroma - 1.0).abs().amax(dim=-1)
            neighbour_saturation = torch.maximum(
                (before_chroma - 1.0).abs().amax(dim=-1),
                (after_chroma - 1.0).abs().amax(dim=-1),
            )
            isolated = (
                agreement
                & (deviation > deviation_limit)
                & (current_saturation > neighbour_saturation + saturation_margin)
                & (current_y[..., 0] > 0.08)
            ).float()
            if not bool(isolated.any()):
                return current, False
            mask = F.avg_pool2d(isolated[None, None], kernel_size=5, stride=1, padding=2)[0, 0, ..., None]
            target = consensus * current_y
            target_y = (target * weights).sum(-1, keepdim=True)
            target = (target * (current_y / target_y.clamp_min(1e-4))).clamp(0.0, 1.0)
            return current.lerp(target, mask.clamp(0.0, 1.0)), True

        def corrected_source(frame_index):
            current = gamma_adjust(frame_index)
            if bool(correction_mask[frame_index]):
                chroma_neighbours = []
                for neighbour_index in range(max(0, frame_index - 4), min(source_count, frame_index + 5)):
                    neighbour = gamma_adjust(neighbour_index)
                    neighbour_y = (neighbour * weights).sum(-1, keepdim=True)
                    chroma_neighbours.append(neighbour / neighbour_y.clamp_min(0.06))
                median_chroma = torch.stack(chroma_neighbours).median(dim=0).values
                current_y = (current * weights).sum(-1, keepdim=True)
                current_chroma = current / current_y.clamp_min(0.06)
                outlier = (current_chroma - median_chroma).abs().amax(dim=-1)
                mask = ((outlier > 0.08) & (current_y[..., 0] > 0.08)).float()
                mask = F.avg_pool2d(mask[None, None], kernel_size=5, stride=1, padding=2)[0, 0, ..., None]
                target = median_chroma * current_y
                target_y = (target * weights).sum(-1, keepdim=True)
                target = (target * (current_y / target_y.clamp_min(1e-4))).clamp(0.0, 1.0)
                current = current.lerp(target, mask.clamp(0.0, 1.0))
            local_repaired = False
            if 0 < frame_index < source_count - 1:
                current, local_repaired = repair_isolated_chroma(
                    current,
                    gamma_adjust(frame_index - 1),
                    gamma_adjust(frame_index + 1),
                    agreement_limit=0.16,
                    deviation_limit=0.10,
                    saturation_margin=0.04,
                )
            return current, local_repaired
        rejected = 0
        local_source_guards = 0
        local_fruc_guards = 0
        with torch.inference_mode(), NvFRUCStream(int(width), int(height), dll_path) as stream:
            previous = None
            for index in range(source_count):
                rgb, source_guarded = corrected_source(index)
                local_source_guards += int(source_guarded)
                rgba = torch.empty((height, width, 4), dtype=torch.uint8, device="cuda")
                rgba[..., :3] = rgb.mul(255.0).round().clamp(0, 255).to(torch.uint8)
                rgba[..., 3] = 255
                if index == 0:
                    restored.append(rgb.cpu())
                candidate, repeated = stream.process_cuda(rgba, float(index * 2 + 2))
                if candidate is not None:
                    mid = candidate[..., :3].to(torch.float32).div(255.0)
                    fallback = previous.lerp(rgb, 0.5)
                    channel_bias = (mid.mean(dim=(0, 1)) - fallback.mean(dim=(0, 1))).abs().max()
                    mean_error = (mid - fallback).abs().mean()
                    mid_luma = (mid * weights).sum(-1).mean()
                    previous_luma = (previous * weights).sum(-1).mean()
                    current_luma = (rgb * weights).sum(-1).mean()
                    low = torch.minimum(previous_luma, current_luma) - 0.025
                    high = torch.maximum(previous_luma, current_luma) + 0.025
                    bad = bool(
                        repeated
                        or channel_bias.item() > 0.030
                        or mean_error.item() > 0.080
                        or mid_luma.item() < low.item()
                        or mid_luma.item() > high.item()
                    )
                    if bad:
                        mid = fallback
                        rejected += 1
                    else:
                        mid, candidate_guarded = repair_isolated_chroma(
                            mid,
                            previous,
                            rgb,
                            agreement_limit=0.18,
                            deviation_limit=0.12,
                            saturation_margin=0.05,
                        )
                        local_fruc_guards += int(candidate_guarded)
                    restored.append(mid.cpu())
                    restored.append(rgb.cpu())
                previous = rgb

        dense = torch.stack(restored, dim=0)
        target = max(2, int(target_frames))
        if dense.shape[0] != target:
            indices = torch.linspace(0, dense.shape[0] - 1, target).round().long()
            dense = dense.index_select(0, indices)
        status = (
            f"NVIDIA FRUC sparse restore: {source_count} -> {dense.shape[0]} frames "
            f"({width}x{height}, CUDA); temporal color guard="
            f"{int(correction_mask.sum().item())}, local source guard={local_source_guards}, "
            f"local FRUC guard={local_fruc_guards}, rejected candidates={rejected}"
        )
        LOG.info(status)
        return dense, status


__all__ = [
    "H3ACRSparseImageToVideo",
    "H3ACRSparseTimePatch",
    "H3ACRSparseStage1Patch",
    "H3ACRNvidiaFrameRestore",
]
