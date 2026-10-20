from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import torch

from comfy.patcher_extension import WrappersMP

from .minimax_h3 import require_native_minimax_h3


LOG = logging.getLogger(__name__)
WRAPPER_KEY = "h3_acr_depth_v1"


_PRESETS = {
    "safe": {"skip_fraction": 0.25, "refresh_interval": 3, "warmup_steps": 2, "tail_steps": 3},
    "balanced": {"skip_fraction": 0.40, "refresh_interval": 4, "warmup_steps": 2, "tail_steps": 3},
    "fast": {"skip_fraction": 0.55, "refresh_interval": 0, "warmup_steps": 2, "tail_steps": 3},
}


@dataclass
class _DepthState:
    preset: dict
    expected_steps: int
    debug: bool
    last_sigma: float | None = None
    step_index: int = -1
    exact_this_step: bool = True
    block_index: int = 0
    importance: torch.Tensor | None = None
    probes: list[torch.Tensor] = field(default_factory=list)
    skip_blocks: set[int] = field(default_factory=set)
    n_skipped: int = 0
    n_exact: int = 0

    def begin_step(self, sigma, n_blocks):
        is_new_run = self.last_sigma is None or sigma > self.last_sigma + 1e-6
        changed = self.last_sigma is None or abs(sigma - self.last_sigma) > 1e-6
        if is_new_run:
            self.step_index = 0
            self.importance = None
        elif changed:
            self.step_index += 1
        self.last_sigma = sigma
        warm = int(self.preset["warmup_steps"])
        tail = int(self.preset["tail_steps"])
        middle_index = self.step_index - warm
        refresh = int(self.preset["refresh_interval"])
        periodic_exact = refresh > 0 and middle_index >= 0 and (middle_index + 1) % refresh == 0
        self.exact_this_step = (
            self.step_index < warm
            or self.step_index >= max(warm, self.expected_steps - tail)
            or periodic_exact
            or self.importance is None
        )
        self.block_index = 0
        self.probes = []
        self.skip_blocks = set()
        self.n_skipped = 0
        self.n_exact = 0
        if not self.exact_this_step:
            locked = {0, 1, 2, n_blocks - 3, n_blocks - 2, n_blocks - 1}
            candidates = [i for i in range(n_blocks) if i not in locked]
            n_skip = min(
                len(candidates),
                max(1, int(round(n_blocks * float(self.preset["skip_fraction"])))),
            )
            order = sorted(candidates, key=lambda i: float(self.importance[i]))
            self.skip_blocks = set(order[:n_skip])


def _probe_indices(seq_len, device, count=384):
    if seq_len <= count:
        return torch.arange(seq_len, dtype=torch.long, device=device)
    return torch.linspace(0, seq_len - 1, count, device=device).round().long()


def _make_block_replace(state, n_blocks):
    def replace(args, extra):
        i = state.block_index
        state.block_index += 1
        if i >= n_blocks:
            return extra["original_block"](args)
        if not state.exact_this_step and i in state.skip_blocks:
            state.n_skipped += 1
            return {"img": args["img"]}

        state.n_exact += 1
        if state.exact_this_step:
            idx = _probe_indices(args["img"].shape[0], args["img"].device)
            before = args["img"].index_select(0, idx).clone()
            result = extra["original_block"](args)
            after = result["img"].index_select(0, idx)
            denom = before.float().square().mean().clamp_min(1e-8)
            score = (after.float() - before.float()).square().mean() / denom
            state.probes.append(score.detach())
            return result
        return extra["original_block"](args)

    return replace


def _make_wrapper(state, n_blocks):
    def wrapper(executor, x, timestep, context, transformer_options={}, **kwargs):
        payload = kwargs.get("minimax_payload") or {}
        compatible = (
            payload.get("layout") is not None
            and kwargs.get("control") is None
            and isinstance(x, (list, tuple))
            and len(x) == 2
            and torch.is_tensor(x[0])
        )
        if not compatible:
            return executor(x, timestep, context, transformer_options, **kwargs)
        state.begin_step(float(timestep.flatten()[0]), n_blocks)
        started = time.perf_counter()
        result = executor(x, timestep, context, transformer_options, **kwargs)
        if state.exact_this_step and len(state.probes) == n_blocks:
            state.importance = torch.stack(state.probes).float().cpu()
        if state.debug:
            if x[0].device.type == "cuda":
                torch.cuda.synchronize(x[0].device)
            LOG.info(
                "H3 ACR Depth step %d/%d | %s | blocks %d computed + %d skipped | %.2fs",
                state.step_index + 1,
                state.expected_steps,
                "exact" if state.exact_this_step else "adaptive-depth",
                state.n_exact,
                state.n_skipped,
                time.perf_counter() - started,
            )
        return result

    return wrapper


def patch_h3_acr_depth(model, mode="safe", expected_steps=12, debug=False):
    require_native_minimax_h3(model)
    resolved = str(mode).lower()
    if resolved not in _PRESETS:
        raise ValueError("H3 ACR Depth mode must be safe, balanced, or fast")
    dm = model.get_model_object("diffusion_model")
    blocks = getattr(dm, "blocks", None)
    if blocks is None or len(blocks) < 8:
        raise RuntimeError("H3 ACR Depth requires the native MiniMax H3 transformer blocks")
    n_blocks = len(blocks)
    state = _DepthState(dict(_PRESETS[resolved]), max(4, int(expected_steps)), bool(debug))
    patched = model.clone()
    replace = _make_block_replace(state, n_blocks)
    for i in range(n_blocks):
        patched.set_model_patch_replace(replace, "dit", "double_block", i)
    patched.add_wrapper_with_key(
        WrappersMP.DIFFUSION_MODEL,
        WRAPPER_KEY,
        _make_wrapper(state, n_blocks),
    )
    return patched


class H3ACRDepthMiniMaxH3:
    """Learns low-impact H3 blocks during exact steps and skips only those blocks."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "enabled": ("BOOLEAN", {"default": True}),
                "mode": (["safe", "balanced", "fast"], {"default": "safe"}),
                "expected_steps": ("INT", {"default": 12, "min": 4, "max": 100, "step": 1}),
            },
            "optional": {"debug": ("BOOLEAN", {"default": False})},
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "apply"
    CATEGORY = "sampling/spectrum"

    def apply(self, model, enabled, mode, expected_steps, debug=False):
        if not enabled:
            return (model,)
        return (patch_h3_acr_depth(model, mode, expected_steps, debug),)


__all__ = ["H3ACRDepthMiniMaxH3", "patch_h3_acr_depth"]
