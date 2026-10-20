from __future__ import annotations

import copy
import json
import logging
import time
import types
from collections import defaultdict
from pathlib import Path

import torch

try:
    import folder_paths
except Exception:  # pragma: no cover
    folder_paths = None


LOG = logging.getLogger(__name__)


def _first_cuda_tensor(value):
    if torch.is_tensor(value) and value.device.type == "cuda":
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _first_cuda_tensor(item)
            if found is not None:
                return found
    if isinstance(value, dict):
        for item in value.values():
            found = _first_cuda_tensor(item)
            if found is not None:
                return found
    return None


def patch_vae_profile(vae):
    patched = copy.copy(vae)
    original_decode = vae.decode
    decoder = getattr(vae.first_stage_model, "decoder", None)

    def decode(samples, *args, **kwargs):
        handles = []
        pending = defaultdict(list)
        records = []

        def pre_hook(name):
            def hook(_module, inputs):
                tensor = _first_cuda_tensor(inputs)
                if tensor is None:
                    return
                event = torch.cuda.Event(enable_timing=True)
                event.record(torch.cuda.current_stream(tensor.device))
                pending[name].append(event)
            return hook

        def post_hook(name):
            def hook(_module, _inputs, output):
                if not pending[name]:
                    return
                tensor = _first_cuda_tensor(output)
                if tensor is None:
                    return
                start = pending[name].pop()
                end = torch.cuda.Event(enable_timing=True)
                end.record(torch.cuda.current_stream(tensor.device))
                records.append((name, start, end))
            return hook

        module_info = []
        if decoder is not None:
            selected = []
            for child_name, child in decoder.named_children():
                selected.append((child_name, child))
                if isinstance(child, (torch.nn.Sequential, torch.nn.ModuleList)):
                    selected.extend((f"{child_name}.{i}", sub) for i, sub in enumerate(child))
            for name, module in selected:
                module_info.append({"name": name, "type": type(module).__name__})
                handles.append(module.register_forward_pre_hook(pre_hook(name)))
                handles.append(module.register_forward_hook(post_hook(name)))

        device = samples.device if torch.is_tensor(samples) and samples.device.type == "cuda" else torch.device("cuda")
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record(torch.cuda.current_stream(device))
        wall_start = time.perf_counter()
        try:
            result = original_decode(samples, *args, **kwargs)
        finally:
            for handle in handles:
                handle.remove()
        end.record(torch.cuda.current_stream(device))
        torch.cuda.synchronize(device)
        wall_ms = (time.perf_counter() - wall_start) * 1000.0
        gpu_ms = float(start.elapsed_time(end))
        totals = defaultdict(float)
        calls = defaultdict(int)
        for name, item_start, item_end in records:
            totals[name] += float(item_start.elapsed_time(item_end))
            calls[name] += 1
        report = {
            "schema": 1,
            "description": "Exact VAE decode timing; decoder math and output are unchanged.",
            "vae_type": type(vae.first_stage_model).__name__,
            "decoder_type": type(decoder).__name__ if decoder is not None else None,
            "input_shape": list(samples.shape) if torch.is_tensor(samples) else None,
            "gpu_ms": gpu_ms,
            "wall_ms": wall_ms,
            "modules": module_info,
            "module_totals_ms": dict(totals),
            "module_calls": dict(calls),
        }
        root = Path(folder_paths.get_output_directory()) if folder_paths is not None else Path.cwd()
        path = root / "h3_vae_profile_latest.json"
        temp = path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(path)
        except PermissionError:
            # Diagnostic fallback for a sandboxed ComfyUI process.
            from tempfile import gettempdir
            path = Path(gettempdir()) / "h3_vae_profile_latest.json"
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(path)
        LOG.info("H3 exact VAE profile | GPU %.1f ms | wall %.1f ms", gpu_ms, wall_ms)
        return result

    patched.decode = decode
    return patched


class H3VAEProfilePatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"vae": ("VAE",)}}

    RETURN_TYPES = ("VAE",)
    RETURN_NAMES = ("vae",)
    FUNCTION = "apply"
    CATEGORY = "sampling/spectrum/diagnostics"
    DESCRIPTION = "Profiles exact H3 VAE decode time without changing decoder math or output pixels."

    def apply(self, vae):
        return (patch_vae_profile(vae),)


def patch_h3_vae_blocks_compile(vae, mode="default"):
    patched = copy.copy(vae)
    original_decode = vae.decode
    decoder = getattr(vae.first_stage_model, "decoder", None)
    blocks = getattr(decoder, "transformer_blocks", None)
    if blocks is None or not blocks:
        raise RuntimeError("H3 VAE block compile requires ViT3DDecoder.transformer_blocks")

    # All H3 VAE transformer blocks share one Python implementation and tensor
    # shape. Compile that unbound implementation once, then bind it to every
    # block only for the duration of decode. The original VAE object is never
    # mutated outside this call and ComfyUI can restore/offload weights normally.
    compiled_forward = torch.compile(
        type(blocks[0]).forward,
        backend="inductor",
        mode=str(mode),
        fullgraph=False,
        dynamic=False,
    )

    def decode(samples, *args, **kwargs):
        originals = [block.forward for block in blocks]
        try:
            for block in blocks:
                block.forward = types.MethodType(compiled_forward, block)
            return original_decode(samples, *args, **kwargs)
        finally:
            for block, original in zip(blocks, originals):
                block.forward = original

    patched.decode = decode
    return patched


class H3VAEBlockCompilePatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vae": ("VAE",),
                "mode": (["default", "max-autotune-no-cudagraphs"], {"default": "default"}),
            }
        }

    RETURN_TYPES = ("VAE",)
    RETURN_NAMES = ("vae",)
    FUNCTION = "apply"
    CATEGORY = "sampling/spectrum/experimental"
    DESCRIPTION = "Compiles the shared H3 ViT3D VAE transformer block implementation without changing decoder math."

    def apply(self, vae, mode="default"):
        return (patch_h3_vae_blocks_compile(vae, mode=mode),)


__all__ = [
    "H3VAEProfilePatch",
    "H3VAEBlockCompilePatch",
    "patch_vae_profile",
    "patch_h3_vae_blocks_compile",
]
