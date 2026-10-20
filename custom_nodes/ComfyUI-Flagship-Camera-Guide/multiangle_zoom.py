"""Source-pixel optical zoom for views completely inside the observed image."""
import numpy as np
import torch
import torch.nn.functional as F
import comfy.model_management
from .multiangle import parse_path, sample_path, radius_scale


class FlagshipMultiAngleSourceZoom:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "path_json": ("STRING", {"multiline": True}),
            "width": ("INT", {"default": 320, "min": 32, "max": 8192}),
            "height": ("INT", {"default": 576, "min": 32, "max": 8192})}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "zoom"
    CATEGORY = "Flagship/Camera"

    def zoom(self, images, path_json, width, height):
        spec = parse_path(path_json)
        values = sample_path(spec, np.linspace(0, 1, len(images))) if spec['enabled'] else np.tile([0.,0.,5.],(len(images),1))
        if spec['zoom_mode'] != 'optical' or np.any(abs(values[:, :2]) > 1e-10) or np.any(values[:, 2] < 5):
            raise ValueError('Source-only zoom needs optical mode, zero camera angles and zoom >=5; use the depth guide for unseen viewpoints')
        _, sh, sw, _ = images.shape
        base_w = min(sw, sh*width/height)
        base_h = base_w*height/width
        device = comfy.model_management.get_torch_device()
        x = (torch.arange(width, device=device, dtype=torch.float32)+.5)/width-.5
        y = (torch.arange(height, device=device, dtype=torch.float32)+.5)/height-.5
        yy, xx = torch.meshgrid(y, x, indexing='ij')
        output = []
        for i, (_, _, zoom) in enumerate(values):
            scale = radius_scale(zoom)
            grid = torch.stack((xx*base_w*scale/sw*2, yy*base_h*scale/sh*2), dim=-1)[None]
            frame = images[i:i+1, ..., :3].movedim(-1, 1).to(device=device, dtype=torch.float32)
            result = F.grid_sample(frame, grid, mode='bilinear', padding_mode='border', align_corners=False)
            output.append(result.movedim(1,-1).clamp(0,1).cpu())
        print(f'[Flagship MultiAngle] optical zoom: {len(images)} source frames; no resampling of time')
        return (torch.cat(output),)
