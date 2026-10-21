"""VRAM-safe color matching for long video frame batches."""

from __future__ import annotations

import torch

from comfy import model_management


class ColorMatchLABChunked:
    """Reinhard Lab color transfer in small GPU chunks.

    KJNodes' GPU implementation moves the complete IMAGE batch to VRAM. For a
    long 1088x1920 video that single tensor can exceed 17 GiB before Kornia's
    temporary tensors are allocated. This node keeps the batch in system RAM
    and transfers only ``chunk_size`` frames at a time.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_target": ("IMAGE",),
                "image_ref": ("IMAGE",),
                "strength": (
                    "FLOAT",
                    {"default": 0.30, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "chunk_size": (
                    "INT",
                    {
                        "default": 2,
                        "min": 1,
                        "max": 32,
                        "step": 1,
                        "tooltip": "Frames processed on GPU at once. Use 1-2 for long 1088p videos.",
                    },
                ),
                "free_vram_first": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Unload completed generation/audio models before final color matching.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "match"
    CATEGORY = "MiniMax H3/Video Postprocess"
    DESCRIPTION = (
        "VRAM-safe Reinhard Lab color matching for long videos. Processes only a "
        "few frames on GPU at once and keeps the full batch in system RAM."
    )

    def match(self, image_target, image_ref, strength, chunk_size, free_vram_first):
        if strength == 0 or image_target.shape[0] == 0:
            return (image_target,)

        import kornia

        if free_vram_first:
            model_management.unload_all_models()
            model_management.soft_empty_cache(force=True)

        device = model_management.get_torch_device()
        batch_size = int(image_target.shape[0])
        chunk_size = max(1, min(int(chunk_size), batch_size))
        output = torch.empty_like(image_target, device="cpu", dtype=torch.float32)

        # The workflow uses one anchor frame. If a reference batch is supplied,
        # matching reference frames are sliced per chunk instead.
        single_ref = image_ref.shape[0] == 1
        ref_std_one = ref_mean_one = None
        if single_ref:
            ref_one = image_ref[:1].to(device=device, dtype=torch.float32)
            ref_one = ref_one.permute(0, 3, 1, 2).contiguous()
            ref_lab = kornia.color.rgb_to_lab(ref_one)
            ref_flat = ref_lab.flatten(2)
            ref_std_one, ref_mean_one = torch.std_mean(
                ref_flat, dim=-1, keepdim=True, unbiased=False
            )
            del ref_one, ref_lab, ref_flat

        for start in range(0, batch_size, chunk_size):
            model_management.throw_exception_if_processing_interrupted()
            end = min(start + chunk_size, batch_size)
            src = image_target[start:end].to(device=device, dtype=torch.float32)
            src = src.permute(0, 3, 1, 2).contiguous()
            src_lab = kornia.color.rgb_to_lab(src)
            src_flat = src_lab.flatten(2)
            src_std, src_mean = torch.std_mean(
                src_flat, dim=-1, keepdim=True, unbiased=False
            )
            src_std = src_std.clamp_min_(1e-6)

            if single_ref:
                ref_mean = ref_mean_one.expand(end - start, -1, -1)
                ref_std = ref_std_one.expand(end - start, -1, -1)
            else:
                ref = image_ref[start:end].to(device=device, dtype=torch.float32)
                ref = ref.permute(0, 3, 1, 2).contiguous()
                ref_lab = kornia.color.rgb_to_lab(ref)
                ref_flat = ref_lab.flatten(2)
                ref_std, ref_mean = torch.std_mean(
                    ref_flat, dim=-1, keepdim=True, unbiased=False
                )

            corrected_flat = (src_flat - src_mean) * (ref_std / src_std) + ref_mean
            corrected_lab = corrected_flat.view_as(src_lab)
            corrected = kornia.color.lab_to_rgb(corrected_lab)
            corrected = (1.0 - strength) * src + strength * corrected
            corrected = corrected.permute(0, 2, 3, 1).contiguous()
            output[start:end].copy_(corrected.detach().cpu().clamp_(0, 1))

            del src, src_lab, src_flat, src_std, src_mean
            del corrected_flat, corrected_lab, corrected
            if not single_ref:
                del ref, ref_lab, ref_flat, ref_std, ref_mean

        if single_ref:
            del ref_std_one, ref_mean_one
        model_management.soft_empty_cache()
        return (output,)


NODE_CLASS_MAPPINGS = {"ColorMatchLABChunked": ColorMatchLABChunked}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ColorMatchLABChunked": "Color Match LAB — Chunked (VRAM Safe)"
}
