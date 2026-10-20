from __future__ import annotations

import json
import logging
import time
import types
from collections import defaultdict
from pathlib import Path

import torch

from comfy.patcher_extension import WrappersMP

try:
    import folder_paths
except Exception:  # pragma: no cover - only used outside ComfyUI tests
    folder_paths = None


LOG = logging.getLogger(__name__)
WRAPPER_KEY = "spectrum_h3_exact_gpu_profile"


class _ExactGPUProfile:
    def __init__(self, block_count: int):
        self.block_count = block_count
        self.pending = []
        self.steps = []
        self.run_started = time.time()

    def record(self, kind: str, block_index: int, start, end) -> None:
        self.pending.append((kind, block_index, start, end))

    def finish_step(self, timestep: float, device, step_start, step_end, wall_ms: float) -> None:
        torch.cuda.synchronize(device)
        totals = defaultdict(float)
        blocks = defaultdict(lambda: defaultdict(float))
        for kind, index, start, end in self.pending:
            elapsed = float(start.elapsed_time(end))
            totals[kind] += elapsed
            blocks[str(index)][kind] += elapsed
        gpu_total = float(step_start.elapsed_time(step_end))
        accounted = totals["attention"] + totals["mlp"]
        attention_kernel = max(0.0, totals["attention"] - totals["qkv_proj"] - totals["out_proj"])
        mlp_tail = max(0.0, totals["mlp"] - totals["mlp_fc1"])
        entry = {
            "step": len(self.steps) + 1,
            "timestep": timestep,
            "gpu_total_ms": gpu_total,
            "wall_total_ms": wall_ms,
            "attention_ms": totals["attention"],
            "qkv_proj_ms": totals["qkv_proj"],
            "attention_kernel_ms": attention_kernel,
            "out_proj_ms": totals["out_proj"],
            "mlp_ms": totals["mlp"],
            "mlp_fc1_ms": totals["mlp_fc1"],
            "mlp_activation_fc2_ms": mlp_tail,
            "other_ms": max(0.0, gpu_total - accounted),
            "blocks": dict(blocks),
        }
        self.steps.append(entry)
        self.pending.clear()
        self._write_report()
        LOG.info(
            "H3 exact GPU profile step %d | total %.1f ms | attention %.1f ms | MLP %.1f ms | other %.1f ms",
            entry["step"], gpu_total, entry["attention_ms"], entry["mlp_ms"], entry["other_ms"],
        )

    def _write_report(self) -> None:
        sums = defaultdict(float)
        for step in self.steps:
            for key in (
                "gpu_total_ms", "wall_total_ms", "attention_ms", "qkv_proj_ms",
                "attention_kernel_ms", "out_proj_ms", "mlp_ms", "mlp_fc1_ms",
                "mlp_activation_fc2_ms", "other_ms",
            ):
                sums[key] += step[key]
        gpu_total = sums["gpu_total_ms"] or 1.0
        report = {
            "schema": 1,
            "description": "Exact MiniMax H3 GPU timing; model math, frames, and denoise steps are unchanged.",
            "block_count": self.block_count,
            "steps_profiled": len(self.steps),
            "run_started_unix": self.run_started,
            "totals_ms": dict(sums),
            "share_percent": {
                "attention": sums["attention_ms"] / gpu_total * 100.0,
                "qkv_proj": sums["qkv_proj_ms"] / gpu_total * 100.0,
                "attention_kernel": sums["attention_kernel_ms"] / gpu_total * 100.0,
                "out_proj": sums["out_proj_ms"] / gpu_total * 100.0,
                "mlp": sums["mlp_ms"] / gpu_total * 100.0,
                "other": sums["other_ms"] / gpu_total * 100.0,
            },
            "steps": self.steps,
        }
        root = Path(folder_paths.get_output_directory()) if folder_paths is not None else Path.cwd()
        path = root / "h3_exact_gpu_profile_latest.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)


def _timed_forward(original, state: _ExactGPUProfile, kind: str, block_index: int):
    def forward(_module, *args, **kwargs):
        tensor = args[0] if args else None
        if not torch.is_tensor(tensor) or tensor.device.type != "cuda":
            return original(*args, **kwargs)
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record(torch.cuda.current_stream(tensor.device))
        result = original(*args, **kwargs)
        end.record(torch.cuda.current_stream(tensor.device))
        state.record(kind, block_index, start, end)
        return result

    return forward


def _model_wrapper(state: _ExactGPUProfile):
    def wrapper(executor, x, timestep, context, transformer_options={}, **kwargs):
        video = x[0] if isinstance(x, (list, tuple)) and x else x
        if not torch.is_tensor(video) or video.device.type != "cuda":
            return executor(x, timestep, context, transformer_options, **kwargs)
        state.pending.clear()
        device = video.device
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record(torch.cuda.current_stream(device))
        wall_start = time.perf_counter()
        result = executor(x, timestep, context, transformer_options, **kwargs)
        end.record(torch.cuda.current_stream(device))
        wall_ms = (time.perf_counter() - wall_start) * 1000.0
        sigma = float(timestep.flatten()[0].detach().cpu())
        state.finish_step(sigma, device, start, end, wall_ms)
        return result

    return wrapper


def patch_h3_exact_gpu_profile(model):
    diffusion_model = model.get_model_object("diffusion_model")
    blocks = getattr(diffusion_model, "blocks", None)
    if blocks is None or not blocks or not hasattr(blocks[0], "attn") or not hasattr(blocks[0], "mlp"):
        raise RuntimeError("H3 exact GPU profile requires native MiniMax H3 transformer blocks")

    patched = model.clone()
    state = _ExactGPUProfile(len(blocks))
    for index, block in enumerate(blocks):
        attn_key = f"diffusion_model.blocks.{index}.attn.forward"
        mlp_key = f"diffusion_model.blocks.{index}.mlp.forward"
        original_attn = patched.object_patches.get(attn_key, block.attn.forward)
        original_mlp = patched.object_patches.get(mlp_key, block.mlp.forward)
        patched.add_object_patch(
            attn_key,
            types.MethodType(_timed_forward(original_attn, state, "attention", index), block.attn),
        )
        patched.add_object_patch(
            mlp_key,
            types.MethodType(_timed_forward(original_mlp, state, "mlp", index), block.mlp),
        )
        for suffix, module, kind in (
            ("attn.qkv_proj.forward", block.attn.qkv_proj, "qkv_proj"),
            ("attn.out_proj.forward", block.attn.out_proj, "out_proj"),
            ("mlp.fc1.forward", block.mlp.fc1, "mlp_fc1"),
        ):
            key = f"diffusion_model.blocks.{index}.{suffix}"
            original = patched.object_patches.get(key, module.forward)
            patched.add_object_patch(
                key,
                types.MethodType(_timed_forward(original, state, kind, index), module),
            )
    patched.add_wrapper_with_key(WrappersMP.DIFFUSION_MODEL, WRAPPER_KEY, _model_wrapper(state))
    return patched


class H3ExactGPUProfilePatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "enabled": ("BOOLEAN", {"default": True})}}

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "apply"
    CATEGORY = "sampling/spectrum/diagnostics"
    DESCRIPTION = "Profiles exact MiniMax H3 GPU time without changing frames, denoise steps, or model math."

    def apply(self, model, enabled=True):
        if not enabled:
            return (model,)
        return (patch_h3_exact_gpu_profile(model),)


__all__ = ["H3ExactGPUProfilePatch", "patch_h3_exact_gpu_profile"]
