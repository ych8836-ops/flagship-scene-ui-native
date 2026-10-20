from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

import torch
import torch.nn.functional as F

import comfy.model_management
import comfy.patcher_extension
import comfy.quant_ops
from comfy.patcher_extension import WrappersMP

from .minimax_h3 import require_native_minimax_h3


LOG = logging.getLogger(__name__)
WRAPPER_KEY = "h3_acr_partial_v1"


_PRESETS = {
    "safe": {
        "active_video_fraction": 0.55,
        "exact_block_stride": 4,
        "warmup_steps": 2,
        "tail_steps": 3,
    },
    "balanced": {
        "active_video_fraction": 0.40,
        "exact_block_stride": 6,
        "warmup_steps": 2,
        "tail_steps": 3,
    },
    "fast": {
        "active_video_fraction": 0.30,
        "exact_block_stride": 10,
        "warmup_steps": 1,
        "tail_steps": 3,
    },
}


def _check_core_compat(dm):
    problems = []
    blocks = getattr(dm, "blocks", None)
    if blocks is None or len(blocks) == 0:
        problems.append("diffusion_model.blocks missing")
    else:
        blk = blocks[0]
        for name in ("adaln_proj", "norm1", "norm2", "attn", "mlp"):
            if not hasattr(blk, name):
                problems.append("block.%s missing" % name)
        attn = getattr(blk, "attn", None)
        if attn is not None:
            for name in ("qkv_proj", "q_norm", "k_norm", "out_proj", "heads", "head_dim"):
                if not hasattr(attn, name):
                    problems.append("block.attn.%s missing" % name)
    ck = getattr(comfy.quant_ops, "ck", None)
    if ck is None or not hasattr(ck, "rms_rope_split_half_"):
        problems.append("comfy.quant_ops.ck.rms_rope_split_half_ missing")
    if problems:
        raise RuntimeError(
            "H3 ACR Partial is incompatible with this ComfyUI MiniMax H3 core (%s). "
            "Bypass the node until it is updated." % "; ".join(problems)
        )


def _mod_rows_from_segments(mod_segments, seq_len, device):
    rows = torch.empty(seq_len, dtype=torch.long, device=device)
    covered = 0
    for a, b, row in mod_segments:
        a, b = int(a), int(b)
        if a != covered or b < a:
            raise ValueError("MiniMax H3 modulation segments are not contiguous")
        rows[a:b] = int(row)
        covered = b
    if covered != seq_len:
        raise ValueError("MiniMax H3 modulation segments do not cover the packed sequence")
    return rows


def _find_target_video_segment(layout):
    found = [(int(a), int(b)) for a, b, kind in layout.segments if kind == "video"]
    if len(found) != 1:
        return None
    return found[0]


def _motion_detail_scores(video):
    """Return one GPU score per H3 video patch in t/h/w flattening order."""
    if video.ndim != 5 or video.shape[0] != 1:
        raise ValueError("expected MiniMax H3 video latent shaped [1,C,T,H,W]")
    v = video.detach().float()[0]
    _, t, h, w = v.shape
    if h % 2 or w % 2:
        v = F.pad(v, (0, w % 2, 0, h % 2, 0, 0))

    motion = torch.zeros((t, v.shape[-2], v.shape[-1]), dtype=torch.float32, device=v.device)
    if t > 1:
        d = (v[:, 1:] - v[:, :-1]).abs().mean(dim=0)
        motion[1:] = torch.maximum(motion[1:], d)
        motion[:-1] = torch.maximum(motion[:-1], d)

    detail = torch.zeros_like(motion)
    if v.shape[-1] > 1:
        dx = (v[:, :, :, 1:] - v[:, :, :, :-1]).abs().mean(dim=0)
        detail[:, :, 1:] = torch.maximum(detail[:, :, 1:], dx)
        detail[:, :, :-1] = torch.maximum(detail[:, :, :-1], dx)
    if v.shape[-2] > 1:
        dy = (v[:, :, 1:, :] - v[:, :, :-1, :]).abs().mean(dim=0)
        detail[:, 1:, :] = torch.maximum(detail[:, 1:, :], dy)
        detail[:, :-1, :] = torch.maximum(detail[:, :-1, :], dy)

    def normalize(x):
        flat = x.flatten()
        scale = flat.mean().clamp_min(1e-6)
        return (x / scale).clamp_max(12.0)

    score = 0.68 * normalize(motion) + 0.32 * normalize(detail)
    score = F.avg_pool3d(score[None, None], kernel_size=(1, 2, 2), stride=(1, 2, 2))[0, 0]
    return score.flatten()


def _select_active_indices(video, video_start, video_stop, fraction):
    scores = _motion_detail_scores(video)
    expected = video_stop - video_start
    if scores.numel() != expected:
        raise ValueError(
            "video patch count mismatch: selector=%d packed=%d" % (scores.numel(), expected)
        )
    keep = max(1, min(expected, int(math.ceil(expected * float(fraction)))))
    local = torch.topk(scores, k=keep, largest=True, sorted=False).indices
    local = torch.sort(local).values + int(video_start)
    prefix = torch.arange(int(video_start), dtype=torch.long, device=video.device)
    return torch.cat((prefix, local)), keep


def _attn_qkv_rope(attn, h, rope_freqs):
    """Core-equivalent full K/V construction; Q is gathered after RoPE."""
    s = h.shape[0]
    q, k, v = attn.qkv_proj(h).split(attn.heads * attn.head_dim, dim=-1)
    v = v.view(s, attn.heads, attn.head_dim)
    q = q.view(1, s, attn.heads, attn.head_dim)
    k = k.view(1, s, attn.heads, attn.head_dim)
    qw = comfy.model_management.cast_to(attn.q_norm.weight, device=h.device)
    kw = comfy.model_management.cast_to(attn.k_norm.weight, device=h.device)
    rot = rope_freqs.shape[-3] * 2
    if comfy.model_management.in_training:
        q, k = comfy.quant_ops.ck.rms_rope_split_half(
            q, k, rope_freqs, qw, kw, epsilon=attn.q_norm.eps, rot_dim=rot
        )
    else:
        comfy.quant_ops.ck.rms_rope_split_half_(
            q, k, rope_freqs, qw, kw, epsilon=attn.q_norm.eps, rot_dim=rot
        )
    return q[0], k[0], v


def _apply_modulation(h, shift, scale, rows):
    return h.mul(1.0 + scale.index_select(0, rows).to(h.dtype)).add_(
        shift.index_select(0, rows).to(h.dtype)
    )


def _apply_segment_modulation(h, shift, scale, segments):
    for a, b, row in segments:
        h[int(a):int(b)].mul_(1.0 + scale[int(row)].to(h.dtype)).add_(
            shift[int(row)].to(h.dtype)
        )
    return h


def _partial_block(blk, args, active_indices, mod_rows):
    x = args["img"]
    t_emb = args["t_emb"]
    rope_freqs = args["rope_freqs"]
    transformer_options = args["transformer_options"]
    shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = blk.adaln_proj(t_emb)

    # K/V remain global. Only selected Q rows continue through attention output,
    # output projection, second norm and MLP.
    h = _apply_segment_modulation(
        blk.norm1(x), shift_msa, scale_msa, args["mod_segments"]
    )
    q, k, v = _attn_qkv_rope(blk.attn, h, rope_freqs)
    qa = q.index_select(0, active_indices)
    # SageAttention's H3 patch assumes self-attention with equal Q/K lengths.
    # P2 deliberately has fewer queries than keys, so use PyTorch SDPA here.
    # On current NVIDIA cards this dispatches to the fused CUDA SDPA kernel.
    q4 = qa.transpose(0, 1).unsqueeze(0)
    k4 = k.transpose(0, 1).unsqueeze(0)
    v4 = v.clone().transpose(0, 1).unsqueeze(0)
    out = F.scaled_dot_product_attention(
        q4, k4, v4, attn_mask=None, dropout_p=0.0, is_causal=False
    )
    out = out.transpose(1, 2).reshape(1, qa.shape[0], -1)

    rows = mod_rows.index_select(0, active_indices)
    xa = x.index_select(0, active_indices)
    xa.addcmul_(
        blk.attn.out_proj(out.squeeze(0)).to(xa.dtype),
        gate_msa.index_select(0, rows).to(xa.dtype),
    )
    hm = _apply_modulation(blk.norm2(xa), shift_mlp, scale_mlp, rows)
    xa.addcmul_(
        blk.mlp(hm).to(xa.dtype),
        gate_mlp.index_select(0, rows).to(xa.dtype),
    )
    x.index_copy_(0, active_indices, xa)
    return {"img": x}


@dataclass
class _PartialState:
    preset: dict
    expected_steps: int
    debug: bool
    last_sigma: float | None = None
    step_index: int = -1
    partial_this_step: bool = False
    active_indices: torch.Tensor | None = None
    mod_rows: torch.Tensor | None = None
    exact_blocks: set[int] = field(default_factory=set)
    n_partial: int = 0
    n_exact: int = 0
    active_video: int = 0
    total_video: int = 0

    def begin_step(self, sigma):
        is_new_run = (
            self.last_sigma is None
            or sigma > self.last_sigma + 1e-6
        )
        changed = self.last_sigma is None or abs(sigma - self.last_sigma) > 1e-6
        if is_new_run:
            self.step_index = 0
        elif changed:
            self.step_index += 1
        self.last_sigma = sigma
        warm = int(self.preset["warmup_steps"])
        tail = int(self.preset["tail_steps"])
        self.partial_this_step = not (
            self.step_index < warm or self.step_index >= max(warm, self.expected_steps - tail)
        )
        self.active_indices = None
        self.mod_rows = None
        self.n_partial = 0
        self.n_exact = 0
        self.active_video = 0
        self.total_video = 0


def _make_block_replace(state, dm, n_blocks):
    def replace(args, extra):
        i = state.n_partial + state.n_exact
        if i >= n_blocks:
            return extra["original_block"](args)
        use_partial = state.partial_this_step and i not in state.exact_blocks
        if not use_partial:
            state.n_exact += 1
            return extra["original_block"](args)
        if state.mod_rows is None:
            state.mod_rows = _mod_rows_from_segments(
                args["mod_segments"], args["img"].shape[0], args["img"].device
            )
        state.n_partial += 1
        return _partial_block(dm.blocks[i], args, state.active_indices, state.mod_rows)

    return replace


def _make_model_wrapper(state, n_blocks):
    def wrapper(executor, x, timestep, context, transformer_options={}, **kwargs):
        started = time.perf_counter()
        payload = kwargs.get("minimax_payload") or {}
        layout = payload.get("layout")
        control = kwargs.get("control")
        compatible = (
            layout is not None
            and control is None
            and isinstance(x, (list, tuple))
            and len(x) == 2
            and torch.is_tensor(x[0])
        )
        if not compatible:
            return executor(x, timestep, context, transformer_options, **kwargs)

        segment = _find_target_video_segment(layout)
        if segment is None:
            return executor(x, timestep, context, transformer_options, **kwargs)
        sigma = float(timestep.flatten()[0])
        state.begin_step(sigma)
        if state.partial_this_step:
            try:
                state.active_indices, state.active_video = _select_active_indices(
                    x[0], segment[0], segment[1], state.preset["active_video_fraction"]
                )
                state.total_video = segment[1] - segment[0]
            except Exception as exc:
                state.partial_this_step = False
                LOG.warning("H3 ACR Partial selector fell back to exact step: %s", exc)

        result = executor(x, timestep, context, transformer_options, **kwargs)
        if state.debug:
            if x[0].device.type == "cuda":
                torch.cuda.synchronize(x[0].device)
            elapsed = time.perf_counter() - started
            LOG.info(
                "H3 ACR Partial step %d/%d | %s | video %d/%d | blocks %d partial + %d exact | %.2fs",
                state.step_index + 1,
                state.expected_steps,
                "partial" if state.partial_this_step else "exact",
                state.active_video,
                state.total_video,
                state.n_partial,
                state.n_exact,
                elapsed,
            )
        return result

    return wrapper


def patch_h3_acr_partial(model, mode="safe", expected_steps=12, debug=False):
    require_native_minimax_h3(model)
    resolved = str(mode).lower()
    if resolved not in _PRESETS:
        raise ValueError("H3 ACR Partial mode must be safe, balanced, or fast")
    steps = max(4, int(expected_steps))
    dm = model.get_model_object("diffusion_model")
    _check_core_compat(dm)
    n_blocks = len(dm.blocks)
    stride = int(_PRESETS[resolved]["exact_block_stride"])
    exact_blocks = set(range(0, n_blocks, stride)) | {n_blocks - 1}
    state = _PartialState(
        preset=dict(_PRESETS[resolved]),
        expected_steps=steps,
        debug=bool(debug),
        exact_blocks=exact_blocks,
    )
    patched = model.clone()
    replace = _make_block_replace(state, dm, n_blocks)
    for i in range(n_blocks):
        patched.set_model_patch_replace(replace, "dit", "double_block", i)
    patched.add_wrapper_with_key(
        WrappersMP.DIFFUSION_MODEL,
        WRAPPER_KEY,
        _make_model_wrapper(state, n_blocks),
    )
    return patched


class H3ACRPartialMiniMaxH3:
    """Motion/detail-selected MiniMax H3 acceleration with full audio queries."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "enabled": ("BOOLEAN", {"default": True}),
                "mode": (["safe", "balanced", "fast"], {"default": "safe"}),
                "expected_steps": (
                    "INT",
                    {"default": 12, "min": 4, "max": 100, "step": 1},
                ),
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
        return (patch_h3_acr_partial(model, mode, expected_steps, debug),)


__all__ = [
    "H3ACRPartialMiniMaxH3",
    "patch_h3_acr_partial",
    "_motion_detail_scores",
    "_mod_rows_from_segments",
    "_select_active_indices",
]
