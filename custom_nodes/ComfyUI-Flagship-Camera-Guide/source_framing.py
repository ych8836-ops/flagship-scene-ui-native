"""Source-pixel framing for a fixed viewpoint; never synthesizes unseen surfaces."""
import numpy as np
import torch
import torch.nn.functional as F
import comfy.model_management


FRAMINGS = ['medium wide shot', 'medium shot', 'close-up', 'extreme close-up', 'head tracking', 'yoyo zoom']


def framing_boxes(transform, mode, strength, width, height):
    count = transform['frames']
    sw, sh = transform['src_size']
    cw, ch = transform['canvas']
    faces = []
    for box, rect in zip(transform['boxes'], transform['face_rect']):
        bx, by, bw, bh = box
        rx, ry, rw, rh = rect
        faces.append([bx + rx / cw * bw, by + ry / ch * bh, rw / cw * bw, rh / ch * bh])
    faces = np.asarray(faces, dtype=np.float64)
    if len(faces) != count or not np.isfinite(faces).all() or not any(transform['detected']):
        raise ValueError('Source framing requires a visible tracked face; no invented subject target.')
    anchor = np.median(faces, axis=0)
    fx, fy, fw, fh = anchor
    aspect = width / height
    if mode in ['medium wide shot', 'medium shot', 'close-up', 'extreme close-up']:
        multiple = {'medium wide shot': 7.7, 'medium shot': 3.8, 'close-up': 2.15, 'extreme close-up': 1.05}[mode]
        h = min(sh, sw / aspect, fh * multiple)
        w = h * aspect
        cx = fx + fw / 2
        cy = fy - fh * .5 + h / 2 if mode != 'extreme close-up' else fy + fh * .42
        cx = float(np.clip(cx, w / 2, sw - w / 2))
        cy = float(np.clip(cy, h / 2, sh - h / 2))
        return np.tile([cx - w / 2, cy - h / 2, w, h], (count, 1))
    result = []
    full_h = min(sh, sw / aspect)
    full_w = full_h * aspect
    for i, face in enumerate(faces):
        if mode == 'head tracking':
            h = full_h * (1 - .45 * float(strength))
            w = h * aspect
            # A constant head location in the output, without face-size stabilization.
            cx, cy = face[0] + face[2] / 2, face[1] + face[3] / 2
            left = cx - (fx + fw / 2) / sw * w
            top = cy - (fy + fh / 2) / sh * h
        elif mode == 'yoyo zoom':
            t = i / max(count - 1, 1)
            zoom = np.sin(np.pi * t) ** 2 * min(.6, float(strength))
            h, w = full_h * (1 - zoom), full_w * (1 - zoom)
            cx, cy = fx + fw / 2, fy + fh / 2
            left, top = cx - cx / sw * w, cy - cy / sh * h
        else:
            raise ValueError('Source framing cannot perform a novel viewpoint or physical dolly.')
        left = float(np.clip(left, 0, sw - w))
        top = float(np.clip(top, 0, sh - h))
        result.append([left, top, w, h])
    return np.asarray(result)


def resample_source(images, boxes, width, height):
    count, sh, sw, _ = images.shape
    if len(boxes) != count or not np.isfinite(boxes).all():
        raise ValueError('One finite framing box per source frame is required')
    device = comfy.model_management.get_torch_device()
    xx = (torch.arange(width, device=device, dtype=torch.float32) + .5) / width
    yy = (torch.arange(height, device=device, dtype=torch.float32) + .5) / height
    output = []
    for i, (left, top, w, h) in enumerate(boxes):
        gx = (left + xx * w) / sw * 2 - 1
        gy = (top + yy * h) / sh * 2 - 1
        y, x = torch.meshgrid(gy, gx, indexing='ij')
        grid = torch.stack((x, y), dim=-1)[None]
        source = images[i:i + 1, ..., :3].movedim(-1, 1).to(device=device, dtype=torch.float32)
        framed = F.grid_sample(source, grid, mode='bilinear', padding_mode='border', align_corners=False)
        output.append(framed.clamp(0, 1).movedim(1, -1).cpu())
    return torch.cat(output)


class FlagshipCameraSourceFraming:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'face_transform': ('H3FACEXFORM',),
            'mode': (FRAMINGS,), 'width': ('INT', {'default': 320, 'min': 32, 'max': 4096, 'step': 32}),
            'height': ('INT', {'default': 576, 'min': 32, 'max': 4096, 'step': 32}),
            'strength': ('FLOAT', {'default': .35, 'min': 0, 'max': 1})}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'frame'
    CATEGORY = 'Flagship/Camera'

    def frame(self, images, face_transform, mode, width, height, strength):
        count, sh, sw, _ = images.shape
        if face_transform['frames'] != count or tuple(face_transform['src_size']) != (sw, sh):
            raise ValueError('Source framing face coordinates do not match the original frame batch.')
        boxes = framing_boxes(face_transform, mode, strength, width, height)
        return (resample_source(images, boxes, width, height),)
