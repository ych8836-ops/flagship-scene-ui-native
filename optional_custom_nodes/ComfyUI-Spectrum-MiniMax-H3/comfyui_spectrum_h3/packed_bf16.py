from __future__ import annotations

"""Exact dense MiniMax H3 attention with a copy-minimized BF16 path.

The native H3 attention implementation already uses ComfyUI's fused RMSNorm
and RoPE kernel.  The remaining Python path wraps the three Q/K/V views in
single-owner containers and clones V before dispatching SDPA.  This patch keeps
the same math and backend dispatch, but feeds the native [1, heads, seq, dim]
views directly to SDPA and leaves V aliased to the QKV projection buffer.

It is deliberately an opt-in research node.  It does not skip tokens, frames,
audio rows, or denoising steps, and it never changes the attention precision.
"""

import logging
import types
from typing import Any

import torch

import comfy.model_management
from comfy.ldm.modules.attention import optimized_attention

from .minimax_h3 import require_native_minimax_h3


LOG = logging.getLogger(__name__)


def _native_dense_attention_forward(self, x, rope_freqs=None, transformer_options={}):
    """Drop-in equivalent of comfy.ldm.minimax.model.Attention.forward.

    Q/K normalization and split-half RoPE intentionally call the same ComfyUI
    kernels as the native implementation.  Only container creation and V's
    defensive clone are removed.  The layout passed to SDPA is identical to
    the native PyTorch attention path.
    """
    s = x.shape[0]
    inner = self.heads * self.head_dim
    q, k, v = self.qkv_proj(x).split(inner, dim=-1)
    v = v.view(s, self.heads, self.head_dim)

    if rope_freqs is not None:
        q = q.view(1, s, self.heads, self.head_dim)
        k = k.view(1, s, self.heads, self.head_dim)
        qw = comfy.model_management.cast_to(self.q_norm.weight, device=x.device)
        kw = comfy.model_management.cast_to(self.k_norm.weight, device=x.device)
        rot = rope_freqs.shape[-3] * 2
        if comfy.model_management.in_training:
            q, k = comfy.quant_ops.ck.rms_rope_split_half(
                q,
                k,
                rope_freqs,
                qw,
                kw,
                epsilon=self.q_norm.eps,
                rot_dim=rot,
            )
        else:
            comfy.quant_ops.ck.rms_rope_split_half_(
                q,
                k,
                rope_freqs,
                qw,
                kw,
                epsilon=self.q_norm.eps,
                rot_dim=rot,
            )
        q = q[0]
        k = k[0]
    else:
        q = self.q_norm(q.view(s, self.heads, self.head_dim))
        k = self.k_norm(k.view(s, self.heads, self.head_dim))

    # This is the exact [B,H,S,D] layout used by native attention_pytorch.
    # No clone or AttentionTensorContainer is needed because SDPA is read-only.
    q4 = q.transpose(0, 1).unsqueeze(0)
    k4 = k.transpose(0, 1).unsqueeze(0)
    v4 = v.transpose(0, 1).unsqueeze(0)
    # Keep ComfyUI's selected backend and transformer override contract.  This
    # is the same dispatcher used by native Attention.forward, only without
    # the container path that clones V for single ownership.
    out = optimized_attention(
        q4,
        k4,
        v4,
        self.heads,
        mask=None,
        skip_reshape=True,
        transformer_options=transformer_options,
    )
    out = out.reshape(1, s, inner)
    return self.out_proj(out.squeeze(0))


def patch_h3_packed_bf16_dense(model: Any):
    """Return a cloned MODEL with exact copy-minimized H3 attention patches."""
    inner, _ = require_native_minimax_h3(model)
    blocks = getattr(inner, "blocks", None)
    if not blocks:
        raise RuntimeError("H3 packed BF16 dense attention requires native transformer blocks")

    patched = model.clone()
    applied = 0
    for index, block in enumerate(blocks):
        attn = getattr(block, "attn", None)
        if attn is None:
            raise RuntimeError(f"native H3 block {index} has no attention module")
        key = f"diffusion_model.blocks.{index}.attn.forward"
        original = patched.object_patches.get(key, attn.forward)
        if getattr(original, "__func__", original) is _native_dense_attention_forward:
            continue
        forward = types.MethodType(_native_dense_attention_forward, attn)
        patched.add_object_patch(key, forward)
        applied += 1

    LOG.info("H3 packed BF16 dense attention active: %d blocks", applied)
    return patched


class H3ACRPackedBF16DenseAttention:
    """Exact all-token H3 attention path with QKV copy overhead removed."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "enabled": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "apply"
    CATEGORY = "sampling/spectrum/experimental"
    DESCRIPTION = (
        "Exact BF16 dense MiniMax H3 attention. Keeps all tokens and steps, "
        "and removes only QKV container/V-clone overhead."
    )

    def apply(self, model, enabled=True):
        if not enabled:
            return (model,)
        return (patch_h3_packed_bf16_dense(model),)


__all__ = ["H3ACRPackedBF16DenseAttention", "patch_h3_packed_bf16_dense"]
