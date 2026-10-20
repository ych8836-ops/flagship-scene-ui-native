"""Deterministic 2D reframing. Not a novel-view renderer or generative camera."""
import json
import logging
import math
import torch
import torch.nn.functional as F

SHOTS = {"wide shot": 1.0, "medium shot": 1.25, "medium close-up": 1.5,
         "close-up": 1.9, "extreme close-up": 2.5}
MOVES = {"static camera", "slow pan left", "slow pan right", "slow tilt up",
         "slow tilt down", "slow dolly in", "slow dolly out", "smooth tracking shot"}
SPEEDS = {"very slow": .4, "slow": .65, "moderate": 1., "fast": 1.4}


def camera_path(camera, count, source_w, source_h, width, height):
    shot = camera.get("shot", "wide shot")
    move = camera.get("movement", "static camera")
    speed = camera.get("speed", "slow")
    if shot not in SHOTS or move not in MOVES or speed not in SPEEDS:
        raise ValueError(f"2D camera does not support {shot} / {move} / {speed}. "
                         "Orbit, tracking and new viewpoints require a different renderer; choose zoom/pan/tilt.")
    strength = float(camera.get("strength", .35))
    # With no user anchor, portrait close-ups should not magnify the torso.
    # center_y remains an explicit 0..1 crop-travel override when supplied.
    automatic_y = {"wide shot": .5, "medium shot": .20, "medium close-up": .12,
                   "close-up": .05, "extreme close-up": .02}[shot]
    ax, ay = float(camera.get("center_x", .5)), float(camera.get("center_y", automatic_y))
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in (strength, ax, ay)):
        raise ValueError("Camera strength and center must be finite values in 0..1.")
    if min(count, source_w, source_h, width, height) < 1:
        raise ValueError("Empty frames or invalid camera dimensions.")
    # Largest source crop with the requested aspect ratio.
    base_w = min(float(source_w), source_h * width / height)
    base_h = base_w * height / width
    amount = strength * SPEEDS[speed]
    result = []
    for i in range(count):
        t = i / max(1, count - 1)
        ease = t*t*(3-2*t)
        zoom = SHOTS[shot]
        if move in {"slow dolly in", "slow dolly out"}:
            phase = ease if move.endswith("in") else 1-ease
            zoom *= 1 + .8 * amount * phase
        elif move != "static camera":
            zoom *= 1 + .65 * amount  # create real travel room, no invented borders
        cw, ch = base_w / zoom, base_h / zoom
        dx = dy = 0.
        if move in {"slow pan left", "slow pan right"}:
            dx = (ease-.5) * min(1., amount*1.6) * (1 if move.endswith("right") else -1)
        elif move == "smooth tracking shot":
            # A deterministic lateral slider move. It cannot infer or follow a
            # subject in 3D, but unlike a prompt request it always moves pixels.
            dx = (ease-.5) * min(.72, amount*1.25)
            dy = math.sin(ease * math.pi) * min(.10, amount*.10)
        if move in {"slow tilt up", "slow tilt down"}:
            dy = (ease-.5) * min(1., amount*1.6) * (1 if move.endswith("down") else -1)
        x = max(0., min(1., ax+dx)) * (source_w-cw)
        y = max(0., min(1., ay+dy)) * (source_h-ch)
        result.append((x, y, cw, ch))
    return result


def render_reframe(images, camera, width, height, device="cpu", progress=None):
    if not torch.is_tensor(images) or images.ndim != 4 or not len(images):
        raise ValueError("Expected nonempty IMAGE tensor [frames, height, width, channels].")
    if width % 32 or height % 32 or not 32 <= min(width, height) <= max(width, height) <= 4096:
        raise ValueError("Output dimensions must be 32..4096 and multiples of 32.")
    n, sh, sw, channels = images.shape
    path = camera_path(camera, n, sw, sh, width, height)
    # Identical framing and size: preserve the original pixels exactly.
    if width == sw and height == sh and all(b == (0., 0., float(sw), float(sh)) for b in path):
        return images, path
    result = torch.empty((n, height, width, channels), dtype=torch.float32, device="cpu")
    yy, xx = torch.meshgrid((torch.arange(height, device=device)+.5)/height,
                           (torch.arange(width, device=device)+.5)/width, indexing="ij")
    with torch.inference_mode():
        for i, (x, y, cw, ch) in enumerate(path):
            if progress: progress(i, n)
            # Pixel-center mapping, subpixel camera path, bounded source crop.
            grid = torch.stack((2*(x+xx*cw)/sw-1, 2*(y+yy*ch)/sh-1), dim=-1)[None]
            frame = images[i:i+1].to(device=device, dtype=torch.float32).movedim(-1, 1)
            # Anti-alias large downscales before resampling the fractional crop.
            factor = min(cw/width, ch/height)
            if factor > 1.5:
                frame = F.interpolate(frame, size=(max(1, round(sh/factor)), max(1, round(sw/factor))),
                                      mode="bilinear", align_corners=False, antialias=True)
            out = F.grid_sample(frame, grid, mode="bilinear", padding_mode="border", align_corners=False)
            result[i].copy_(out[0].movedim(0, -1).clamp(0, 1).cpu())
    if progress: progress(n, n)
    return result, path


class H3CameraReframe:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "segment_plan": ("STRING", {"forceInput": True}),
                             "width": ("INT", {"default": 960, "min": 32, "max": 4096, "step": 32}),
                             "height": ("INT", {"default": 544, "min": 32, "max": 4096, "step": 32})}}
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("reframed_source_frames", "camera_path_report")
    FUNCTION = "render"
    CATEGORY = "MiniMax H3/Camera 2D"

    def render(self, images, segment_plan, width, height):
        from comfy import model_management
        from comfy.utils import ProgressBar
        plan = json.loads(segment_plan)
        camera = plan.get("camera", {})
        bar = ProgressBar(len(images))
        def update(i, n):
            model_management.throw_exception_if_processing_interrupted()
            bar.update_absolute(i, n)
        frames, path = render_reframe(images, camera, width, height,
                                      device=model_management.get_torch_device(), progress=update)
        report = {"method": "enforced_pixel_camera", "new_viewpoint": False, "camera": camera,
                  "frame_count": len(frames), "first_crop_xywh": path[0], "last_crop_xywh": path[-1],
                  "source_size": list(images.shape[1:3]), "output_size": [height, width]}
        logging.getLogger("h3_camera_reframe").info("Camera 2D applied: %s", json.dumps(report))
        return frames, json.dumps(report, ensure_ascii=False)

NODE_CLASS_MAPPINGS = {"H3CameraReframe": H3CameraReframe}
NODE_DISPLAY_NAME_MAPPINGS = {"H3CameraReframe": "H3 Camera · Actual 2D Reframe (No Generation)"}
