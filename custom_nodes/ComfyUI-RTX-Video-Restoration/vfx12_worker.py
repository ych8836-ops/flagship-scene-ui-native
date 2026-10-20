from __future__ import annotations

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for vendor_candidate in (
    ROOT / "vendor",
    ROOT.parent / "third_party_downloads" / "nvidia_vfx" / "wheel_extracted",
):
    if vendor_candidate.is_dir():
        sys.path.insert(0, str(vendor_candidate))
        break

from nvvfx import VideoSuperRes, get_sdk_version


UPSCALE_MODES = {
    "Ultra": VideoSuperRes.QualityLevel.ULTRA,
    "High": VideoSuperRes.QualityLevel.HIGH,
    "High-Bitrate Ultra": VideoSuperRes.QualityLevel.HIGHBITRATE_ULTRA,
    "High-Bitrate High": VideoSuperRes.QualityLevel.HIGHBITRATE_HIGH,
}

RESTORE_MODES = {
    "Deblur Low": (VideoSuperRes.QualityLevel.DEBLUR_LOW,),
    "Deblur Medium": (VideoSuperRes.QualityLevel.DEBLUR_MEDIUM,),
    "Denoise Low": (VideoSuperRes.QualityLevel.DENOISE_LOW,),
    "Denoise Low + Deblur Low": (
        VideoSuperRes.QualityLevel.DENOISE_LOW,
        VideoSuperRes.QualityLevel.DEBLUR_LOW,
    ),
    "Chain Late Recovery 90": (
        VideoSuperRes.QualityLevel.DENOISE_LOW,
        VideoSuperRes.QualityLevel.DEBLUR_MEDIUM,
    ),
}

AUTO_RESTORE_MODE = "Auto Scan (Clean/Chain90)"

TEMPORAL_MODES = (
    "Auto Temporal",
    "Face Lock",
    "Action Stable",
    "Off",
)

SUBJECT_RECOVERY_MODES = (
    "Auto",
    "Full Shot Strong",
    "Off",
)

SUBJECT_BODY_CANVAS_SIZE = 1024
SUBJECT_FACE_CANVAS_SIZE = 768

QUALITY_TARGETS = {
    "100% Restore": 0.0,
    "105% Master": 0.05,
    "110% Master": 0.10,
}

COLOR_TREATMENTS = {
    "Off": None,
    "Auto Natural": {"target_median": 0.44, "min_gamma": 0.82, "blend": 0.78, "wb_limit": 0.035},
    "Auto Bright": {"target_median": 0.50, "min_gamma": 0.72, "blend": 1.00, "wb_limit": 0.055},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--input-width", required=True, type=int)
    parser.add_argument("--input-height", required=True, type=int)
    parser.add_argument("--output-width", required=True, type=int)
    parser.add_argument("--output-height", required=True, type=int)
    parser.add_argument("--upscale-quality", choices=UPSCALE_MODES, default="Ultra")
    parser.add_argument(
        "--restore-mode",
        choices=[AUTO_RESTORE_MODE, *RESTORE_MODES],
        default=AUTO_RESTORE_MODE,
    )
    parser.add_argument("--quality-target", choices=QUALITY_TARGETS, default="110% Master")
    parser.add_argument("--color-treatment", choices=COLOR_TREATMENTS, default="Auto Natural")
    parser.add_argument("--temporal-mode", choices=TEMPORAL_MODES, default="Auto Temporal")
    parser.add_argument("--subject-recovery", choices=SUBJECT_RECOVERY_MODES, default="Auto")
    parser.add_argument(
        "--memory-profile",
        choices=("Auto", "Quality", "Low VRAM"),
        default="Auto",
    )
    return parser.parse_args()


def resolve_memory_profile(
    requested: str,
    output_width: int,
    output_height: int,
) -> tuple[bool, float, float, str]:
    """Resolve the memory path without changing the requested output scale."""
    free_bytes, total_bytes = torch.cuda.mem_get_info()
    gib = float(1024 ** 3)
    free_gib = free_bytes / gib
    total_gib = total_bytes / gib
    output_megapixels = (output_width * output_height) / 1_000_000.0

    if requested == "Low VRAM":
        low_vram = True
        reason = "forced"
    elif requested == "Quality":
        low_vram = False
        reason = "forced"
    else:
        low_vram = (
            total_gib <= 12.5
            or free_gib <= 8.0
            or (output_megapixels >= 12.0 and free_gib <= 12.0)
        )
        if total_gib <= 12.5:
            reason = "GPU capacity"
        elif free_gib <= 8.0:
            reason = "available VRAM"
        elif output_megapixels >= 12.0 and free_gib <= 12.0:
            reason = "large output"
        else:
            reason = "sufficient VRAM"
    return low_vram, free_gib, total_gib, reason


def make_effect(mode: VideoSuperRes.QualityLevel, width: int, height: int) -> VideoSuperRes:
    effect = VideoSuperRes(quality=mode)
    # The installed nvvfx binding exports planar output as tightly packed
    # DLPack. A pitched NvCVImage whose width is not 64-pixel aligned then
    # appears as diagonal RGB corruption. Keep SDK surfaces aligned and
    # remove the private padding on CUDA before subsequent processing.
    effect.output_width = ((width + 63) // 64) * 64
    effect.output_height = height
    effect.load()
    return effect


def _run_vfx_frame(
    effect: VideoSuperRes,
    image: torch.Tensor,
    output_width: int,
    output_height: int,
) -> torch.Tensor:
    """Return the requested CUDA image from a pitch-safe SDK surface."""
    input_width = image.shape[2]
    integer_scale = output_width // input_width if output_width % input_width == 0 else 0
    alignment = math.lcm(64, integer_scale) if integer_scale else 64
    surface_width = ((output_width + alignment - 1) // alignment) * alignment
    if integer_scale and surface_width != output_width:
        # Exact 1x/2x/3x/4x geometry: replicate only the right border,
        # then crop the corresponding output padding. No image resampling.
        extra_input = (surface_width - output_width) // integer_scale
        sdk_input = F.pad(image, (0, extra_input, 0, 0), mode="replicate").contiguous()
    else:
        sdk_input = image.contiguous()

    if effect.output_width != surface_width:
        effect.output_width = surface_width
    if effect.output_height != output_height:
        effect.output_height = output_height
    shape = (*sdk_input.shape[1:], output_height, surface_width)
    if getattr(effect, "_flagship_last_shape", None) != shape:
        # The first evaluation after a surface change can expose an old image.
        _ = torch.from_dlpack(effect.run(sdk_input).image).clone()
        setattr(effect, "_flagship_last_shape", shape)
    result = torch.from_dlpack(effect.run(sdk_input).image).clone()
    if tuple(result.shape) != (3, output_height, surface_width):
        raise RuntimeError(f"Unexpected VFX output shape: {tuple(result.shape)}")
    if surface_width == output_width:
        return result
    if integer_scale:
        return result[:, :, :output_width].contiguous()
    # Fractional scales can require a non-integral input border. Resize the
    # aligned surface on CUDA instead of truncating or changing the framing.
    return F.interpolate(
        result.unsqueeze(0), size=(output_height, output_width),
        mode="bicubic", align_corners=False, antialias=True,
    ).squeeze(0).clamp(0, 1)


def write_rgba(
    stream,
    image: torch.Tensor,
    host_buffer: torch.Tensor,
    device_buffer: torch.Tensor,
) -> None:
    """Download once into reusable pinned memory and write without a bytes copy."""
    rgb = (
        image.clamp(0, 1)
        .mul(255)
        .round()
        .to(torch.uint8)
        .permute(1, 2, 0)
    )
    device_buffer[..., :3].copy_(rgb)
    host_buffer.copy_(device_buffer, non_blocking=True)
    torch.cuda.current_stream().synchronize()
    stream.write(memoryview(host_buffer.numpy()).cast("B"))


def perceptual_master(image: torch.Tensor, amount: float) -> torch.Tensor:
    """Add only bounded luminance micro-detail so color and broad tone stay stable."""
    if amount <= 0:
        return image
    luma = (
        image[0:1] * 0.2126
        + image[1:2] * 0.7152
        + image[2:3] * 0.0722
    ).unsqueeze(0)
    low_frequency = F.avg_pool2d(luma, kernel_size=5, stride=1, padding=2)
    detail = luma - low_frequency
    # Ignore tiny fluctuations and cap stronger transitions to suppress halos/noise.
    detail = torch.sign(detail) * torch.relu(torch.abs(detail) - (1.0 / 1024.0))
    detail = detail.clamp(-0.06, 0.06).squeeze(0)
    return (image + detail.expand_as(image) * amount).clamp(0, 1)


def frame_quality_score(image: torch.Tensor) -> float:
    """Estimate normalized edge integrity while penalizing 8-pixel block boundaries."""
    luma = (
        image[0:1] * 0.2126
        + image[1:2] * 0.7152
        + image[2:3] * 0.0722
    )
    dx = torch.abs(luma[:, :, 1:] - luma[:, :, :-1])
    dy = torch.abs(luma[:, 1:, :] - luma[:, :-1, :])
    edge = (dx.mean() + dy.mean()) * 0.5
    contrast = luma.std().clamp_min(0.02)
    block_x = dx[:, :, 7::8].mean() if dx.shape[2] >= 16 else edge
    block_y = dy[:, 7::8, :].mean() if dy.shape[1] >= 16 else edge
    block_ratio = ((block_x + block_y) * 0.5 / edge.clamp_min(1e-6)).clamp_min(1.0)
    score = (edge / contrast) / (1.0 + (block_ratio - 1.0) * 0.75)
    return float(score.item())


def frame_motion_score(
    image: torch.Tensor,
    previous_luma: torch.Tensor | None,
) -> tuple[float, torch.Tensor]:
    """Estimate inter-frame motion on a small luma proxy.

    The score intentionally treats camera movement as motion too. Strong temporal
    restoration is unsafe in both cases because it can turn motion blur and fine
    backgrounds into painted color fields.
    """
    luma = (
        image[0:1] * 0.2126
        + image[1:2] * 0.7152
        + image[2:3] * 0.0722
    ).unsqueeze(0)
    scale = min(1.0, 192.0 / max(image.shape[1:]))
    if scale < 1.0:
        luma = F.interpolate(
            luma,
            scale_factor=scale,
            mode="bilinear",
            align_corners=False,
            antialias=True,
        )
    current = luma.squeeze(0)
    if previous_luma is None or previous_luma.shape != current.shape:
        return 0.0, current

    # Remove global exposure drift before measuring structural motion.
    current_centered = current - current.mean()
    previous_centered = previous_luma - previous_luma.mean()
    score = torch.abs(current_centered - previous_centered).mean()
    return float(score.item()), current


def _analysis_gray(frame_rgb: np.ndarray, max_side: int = 288) -> np.ndarray:
    gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    scale = min(1.0, float(max_side) / max(height, width))
    if scale < 1.0:
        gray = cv2.resize(
            gray,
            (max(16, round(width * scale)), max(16, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return gray.astype(np.float32) / 255.0


def _analysis_cuda(frame: torch.Tensor, max_side: int = 288) -> torch.Tensor:
    """Build an HWC RGB analysis frame without leaving CUDA memory."""
    _channels, height, width = frame.shape
    scale = min(1.0, float(max_side) / max(height, width))
    analysis_height = max(32, int(round(height * scale / 8.0) * 8))
    analysis_width = max(32, int(round(width * scale / 8.0) * 8))
    image = frame.unsqueeze(0)
    if (analysis_height, analysis_width) != (height, width):
        image = F.interpolate(
            image, size=(analysis_height, analysis_width),
            mode="bilinear", align_corners=False,
        )
    return image[0].permute(1, 2, 0).contiguous()


def _effect_frame(effect: VideoSuperRes, image: torch.Tensor) -> torch.Tensor:
    """Run one VFX effect while allowing efficient dynamically sized ROI input."""
    height, width = image.shape[1:]
    return _run_vfx_frame(effect, image, width, height)


def _box_iou(first: np.ndarray, second: np.ndarray) -> float:
    x1 = max(float(first[0]), float(second[0]))
    y1 = max(float(first[1]), float(second[1]))
    x2 = min(float(first[2]), float(second[2]))
    y2 = min(float(first[3]), float(second[3]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection <= 0:
        return 0.0
    first_area = max(1.0, float(first[2] - first[0])) * max(1.0, float(first[3] - first[1]))
    second_area = max(1.0, float(second[2] - second[0])) * max(1.0, float(second[3] - second[1]))
    return intersection / max(first_area + second_area - intersection, 1.0)


@dataclass(frozen=True)
class SubjectROI:
    x1: int
    y1: int
    x2: int
    y2: int
    strength: float
    kind: str
    residual_limit: float


class SubjectRecoveryTracker:
    """Lightweight face-led person ROI detector with temporally smoothed boxes.

    A full-frame quality score misses small subjects.  The installed face model
    gives us a reliable anchor, then the box is expanded to include hair, torso,
    hands, and most of a standing body.  Detection is sparse and the large,
    feathered ROI is held between scans to keep the extra cost small.
    """

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.model = None
        self.boxes: list[np.ndarray] = []
        # AUTO must inspect the whole timeline rather than requiring the user
        # to switch modes for individual shots.  Four-frame scans catch cuts
        # and camera reframing while the feathered tracked ROI covers the gaps.
        self.scan_interval = 4
        self.max_subjects = 4
        self.last_profile = "none"
        self.device: int | str = 0 if torch.cuda.is_available() else "cpu"
        if mode == "Off":
            return

        comfy_root = ROOT.parent.parent
        model_root = Path(os.environ.get("FLAGSHIP_COMFY_MODEL_ROOT", comfy_root / "models"))
        model_path = model_root / "ultralytics" / "bbox" / "face_yolov8m.pt"
        if not model_path.is_file():
            print(f"Subject Recovery disabled: face detector not found at {model_path}")
            self.mode = "Off"
            return
        try:
            from ultralytics import YOLO

            self.model = YOLO(str(model_path))
            print(f"Subject Recovery detector: {model_path.name} on {self.device}")
        except Exception as error:
            print(f"Subject Recovery disabled: {error}")
            self.mode = "Off"

    @property
    def enabled(self) -> bool:
        return self.mode != "Off" and self.model is not None

    def _smooth(
        self,
        detections: list[np.ndarray],
        responsive: bool = False,
    ) -> list[np.ndarray]:
        if not self.boxes:
            return detections
        smoothed: list[np.ndarray] = []
        unused = set(range(len(self.boxes)))
        for detected in detections:
            best_index = -1
            best_iou = 0.0
            for index in unused:
                overlap = _box_iou(detected, self.boxes[index])
                if overlap > best_iou:
                    best_iou = overlap
                    best_index = index
            if best_index >= 0 and best_iou >= 0.12:
                previous = self.boxes[best_index]
                previous_weight = 0.24 if responsive else 0.58
                smoothed.append(previous * previous_weight + detected * (1.0 - previous_weight))
                unused.remove(best_index)
            else:
                smoothed.append(detected)
        return smoothed

    def detect(
        self,
        frame_rgb: torch.Tensor,
        index: int,
        motion_score: float,
    ) -> list[np.ndarray]:
        if not self.enabled:
            return []
        fast_motion = motion_score >= 0.040
        if not fast_motion and index % self.scan_interval and self.boxes:
            return self.boxes
        try:
            input_height, input_width = frame_rgb.shape[-2:]
            scale = min(640.0 / max(input_width, 1), 640.0 / max(input_height, 1))
            scaled_height = max(32, int(round(input_height * scale)))
            scaled_width = max(32, int(round(input_width * scale)))
            prepared = F.interpolate(
                frame_rgb[None],
                size=(scaled_height, scaled_width),
                mode="bilinear",
                align_corners=False,
                antialias=True,
            )
            pad_height = ((scaled_height + 31) // 32) * 32 - scaled_height
            pad_width = ((scaled_width + 31) // 32) * 32 - scaled_width
            if pad_height or pad_width:
                prepared = F.pad(prepared, (0, pad_width, 0, pad_height), mode="replicate")
            result = self.model.predict(
                source=prepared.half(),
                imgsz=max(prepared.shape[-2:]),
                conf=0.24,
                iou=0.50,
                max_det=self.max_subjects,
                device=self.device,
                half=self.device != "cpu",
                verbose=False,
            )[0]
            if result.boxes is None or len(result.boxes) == 0:
                self.boxes = []
                return []
            boxes = result.boxes.xyxy.detach().float()
            boxes[:, [0, 2]].div_(scale).clamp_(0, input_width)
            boxes[:, [1, 3]].div_(scale).clamp_(0, input_height)
            detections = [box.astype(np.float32) for box in boxes.cpu().numpy()]
            detections.sort(key=lambda box: float((box[2] - box[0]) * (box[3] - box[1])), reverse=True)
            self.boxes = self._smooth(
                detections[: self.max_subjects],
                responsive=fast_motion,
            )
        except Exception as error:
            print(f"Subject Recovery detector warning at frame {index + 1}: {error}")
            return self.boxes
        return self.boxes

    def subject_rois(
        self,
        frame_rgb: torch.Tensor,
        index: int,
        output_width: int,
        output_height: int,
        motion_score: float,
    ) -> list[SubjectROI]:
        input_height, input_width = frame_rgb.shape[-2:]
        body_rois: list[SubjectROI] = []
        face_rois: list[SubjectROI] = []
        faces = self.detect(frame_rgb, index, motion_score)
        face_ratios = [max(4.0, float(face[3] - face[1])) / max(input_height, 1) for face in faces]
        # AUTO promotes the entire shot when its largest visible face is small,
        # or when several people share a wide frame.  This is the same internal
        # recovery profile as the manual FULL SHOT button.
        largest_face_ratio = max(face_ratios, default=1.0)
        auto_full_shot = self.mode == "Auto" and (
            largest_face_ratio < 0.165 or (len(faces) >= 3 and largest_face_ratio < 0.22)
        )
        self.last_profile = "fullshot" if auto_full_shot or self.mode == "Full Shot Strong" else "standard"

        for face in faces:
            x1, y1, x2, y2 = [float(value) for value in face]
            face_width = max(4.0, x2 - x1)
            face_height = max(4.0, y2 - y1)
            face_ratio = face_height / max(input_height, 1)
            # Close-ups already contain enough pixels and are handled by the
            # full-frame pass.  Subject recovery is specifically for full shots.
            if face_ratio >= (0.29 if self.mode == "Full Shot Strong" else 0.23):
                continue

            center_x = (x1 + x2) * 0.5
            strong = self.mode == "Full Shot Strong" or auto_full_shot or face_ratio < 0.145
            roi_half_width = face_width * (2.35 if strong else 1.95)
            roi_top = y1 - face_height * (0.95 if strong else 0.75)
            roi_bottom = y2 + face_height * (7.0 if strong else 5.7)

            source_x1 = max(0.0, center_x - roi_half_width)
            source_x2 = min(float(input_width), center_x + roi_half_width)
            source_y1 = max(0.0, roi_top)
            source_y2 = min(float(input_height), roi_bottom)

            scale_x = output_width / input_width
            scale_y = output_height / input_height
            out_x1 = max(0, int(source_x1 * scale_x) // 2 * 2)
            out_y1 = max(0, int(source_y1 * scale_y) // 2 * 2)
            out_x2 = min(output_width, (int(source_x2 * scale_x) + 1) // 2 * 2)
            out_y2 = min(output_height, (int(source_y2 * scale_y) + 1) // 2 * 2)
            if out_x2 - out_x1 < 96 or out_y2 - out_y1 < 96:
                continue

            scarcity = np.clip((0.16 - face_ratio) / 0.12, 0.0, 1.0)
            # The body pass restores clothes and silhouette only.  Keeping this
            # deliberately light prevents overlapping people from being
            # sharpened repeatedly and avoids waxy foreground skin.
            body_strength = (0.25 + 0.15 * scarcity) if strong else (0.20 + 0.12 * scarcity)
            body_rois.append(
                SubjectROI(
                    out_x1,
                    out_y1,
                    out_x2,
                    out_y2,
                    float(body_strength),
                    "body",
                    0.050,
                )
            )

            # Give every distant face its own canvas.  Previously the full
            # person crop was fitted to 1024px, making a small face tiny again
            # before VFX restoration.  A tight crop lets the same face occupy
            # most of a dedicated 768px surface.
            face_left = x1 - face_width * 0.72
            face_right = x2 + face_width * 0.72
            face_top = y1 - face_height * 0.72
            face_bottom = y2 + face_height * 1.05
            face_out_x1 = max(0, int(face_left * scale_x) // 2 * 2)
            face_out_y1 = max(0, int(face_top * scale_y) // 2 * 2)
            face_out_x2 = min(output_width, (int(face_right * scale_x) + 1) // 2 * 2)
            face_out_y2 = min(output_height, (int(face_bottom * scale_y) + 1) // 2 * 2)
            if face_out_x2 - face_out_x1 >= 48 and face_out_y2 - face_out_y1 >= 48:
                if face_ratio < 0.055:
                    face_strength = 0.72
                    residual_limit = 0.115
                elif face_ratio < 0.10:
                    face_strength = 0.60
                    residual_limit = 0.095
                elif face_ratio < 0.16:
                    face_strength = 0.44
                    residual_limit = 0.075
                else:
                    # Near faces already contain useful skin texture.  Only a
                    # small corrective blend is allowed so they do not become
                    # porcelain-like while distant faces are repaired.
                    face_strength = 0.18
                    residual_limit = 0.050
                face_rois.append(
                    SubjectROI(
                        face_out_x1,
                        face_out_y1,
                        face_out_x2,
                        face_out_y2,
                        face_strength,
                        "face",
                        residual_limit,
                    )
                )
        # Process broad clothing/silhouette first and finish with the tight
        # facial correction.  This ordering keeps the face pass from being
        # overwritten by a neighbouring person's larger body ROI.
        return [*body_rois, *face_rois]


def _feather_mask(
    height: int,
    width: int,
    device: torch.device,
    dtype: torch.dtype,
) -> torch.Tensor:
    feather = max(12.0, min(height, width) * 0.10)
    y = torch.arange(height, device=device, dtype=dtype)
    x = torch.arange(width, device=device, dtype=dtype)
    vertical = torch.minimum(y + 1, height - y).div(feather).clamp(0, 1)
    horizontal = torch.minimum(x + 1, width - x).div(feather).clamp(0, 1)
    mask = torch.minimum(vertical[:, None], horizontal[None, :])
    return (mask * mask * (3.0 - 2.0 * mask)).unsqueeze(0)


def recover_subjects(
    base: torch.Tensor,
    image: torch.Tensor,
    rois: list[SubjectROI],
    effects_by_kind: dict[str, list[VideoSuperRes]],
) -> tuple[torch.Tensor, torch.Tensor | None, torch.Tensor | None]:
    if not rois or not effects_by_kind:
        return image, None, None
    result = image
    subject_mask = torch.zeros(
        (1, image.shape[1], image.shape[2]),
        device=image.device,
        dtype=image.dtype,
    )
    face_mask = torch.zeros_like(subject_mask)
    has_face = False
    for roi in rois:
        x1, y1, x2, y2 = roi.x1, roi.y1, roi.x2, roi.y2
        effects = effects_by_kind.get(roi.kind, [])
        if not effects:
            continue
        canvas_size = SUBJECT_FACE_CANVAS_SIZE if roi.kind == "face" else SUBJECT_BODY_CANVAS_SIZE
        source_crop = base[:, y1:y2, x1:x2].contiguous()
        if source_crop.numel() == 0:
            continue
        crop_height, crop_width = source_crop.shape[1:]
        fit_scale = min(
            canvas_size / max(crop_width, 1),
            canvas_size / max(crop_height, 1),
        )
        fit_width = max(16, min(canvas_size, round(crop_width * fit_scale)))
        fit_height = max(16, min(canvas_size, round(crop_height * fit_scale)))
        resized = F.interpolate(
            source_crop.unsqueeze(0),
            size=(fit_height, fit_width),
            mode="bicubic",
            align_corners=False,
            antialias=True,
        ).squeeze(0)
        pad_left = (canvas_size - fit_width) // 2
        pad_right = canvas_size - fit_width - pad_left
        pad_top = (canvas_size - fit_height) // 2
        pad_bottom = canvas_size - fit_height - pad_top
        candidate = F.pad(
            resized.unsqueeze(0),
            (pad_left, pad_right, pad_top, pad_bottom),
            mode="replicate",
        ).squeeze(0)
        for effect in effects:
            candidate = _effect_frame(effect, candidate)
        candidate = candidate[
            :,
            pad_top : pad_top + fit_height,
            pad_left : pad_left + fit_width,
        ]
        candidate = F.interpolate(
            candidate.unsqueeze(0),
            size=(crop_height, crop_width),
            mode="bicubic",
            align_corners=False,
            antialias=True,
        ).squeeze(0)
        # VFX is restorative, not a face generator.  Bound the local residual
        # so malformed tiny features cannot turn into high-contrast invented
        # eyes or a plastic mask.  Distant faces receive a wider correction
        # allowance than already-detailed foreground faces.
        candidate = source_crop + (candidate - source_crop).clamp(
            -roi.residual_limit,
            roi.residual_limit,
        )
        local_mask = _feather_mask(
            y2 - y1,
            x2 - x1,
            image.device,
            image.dtype,
        ) * roi.strength
        original_crop = result[:, y1:y2, x1:x2]
        result[:, y1:y2, x1:x2] = torch.lerp(original_crop, candidate, local_mask)
        subject_mask[:, y1:y2, x1:x2] = torch.maximum(
            subject_mask[:, y1:y2, x1:x2],
            local_mask,
        )
        if roi.kind == "face":
            face_mask[:, y1:y2, x1:x2] = torch.maximum(
                face_mask[:, y1:y2, x1:x2],
                local_mask,
            )
            has_face = True
    return result.clamp(0, 1), subject_mask, face_mask if has_face else None


def temporal_detail_lock(
    base: torch.Tensor,
    restored: torch.Tensor,
    current_analysis: torch.Tensor,
    state: dict[str, object],
    mode: str,
    motion_score: float,
    scene_cut: bool,
    subject_mask: torch.Tensor | None,
    face_mask: torch.Tensor | None,
    history_dtype: torch.dtype | None = None,
) -> torch.Tensor:
    """Stabilize restoration detail with bidirectional flow and occlusion rejection."""
    # Track both the RTX VSR high-frequency layer and the optional restoration
    # residual.  Tracking only (restored - base) cannot stabilize action shots
    # because AUTO intentionally disables most extra restoration there.
    base_low = F.avg_pool2d(
        base.unsqueeze(0),
        kernel_size=5,
        stride=1,
        padding=2,
    ).squeeze(0)
    base_detail = (base - base_low).clamp(-0.24, 0.24)
    enhancement_detail = (restored - base).clamp(-0.18, 0.18)
    detail = (base_detail + enhancement_detail).clamp(-0.28, 0.28)
    previous_detail = state.get("detail")
    previous_analysis = state.get("analysis")
    reset = (
        mode == "Off"
        or scene_cut
        or not isinstance(previous_detail, torch.Tensor)
        or not isinstance(previous_analysis, torch.Tensor)
        or previous_detail.shape != detail.shape
        or previous_analysis.shape != current_analysis.shape
    )
    if reset:
        state["detail"] = detail.detach().to(dtype=history_dtype or detail.dtype)
        # The analysis proxy is tiny and NVOFA's warp grid is FP32. Keep this
        # buffer in FP32 for CUDA grid-sample compatibility.
        state["analysis"] = current_analysis.detach()
        return restored

    if mode == "Face Lock":
        static_weight, medium_weight, action_weight = 0.52, 0.36, 0.18
    elif mode == "Action Stable":
        static_weight, medium_weight, action_weight = 0.38, 0.28, 0.20
    else:
        # Preserve the validated Temporal 9.5 pipeline and raise only AUTO's
        # action history by a very small 3.6%.  No generated face restoration,
        # look-ahead frame synthesis, or extra recovery residual is involved.
        static_weight, medium_weight, action_weight = 0.46, 0.34, 0.29

    if motion_score >= 0.070:
        temporal_weight = action_weight * 0.80
    elif motion_score >= 0.045:
        temporal_weight = action_weight
    elif motion_score >= 0.022:
        temporal_weight = medium_weight
    else:
        temporal_weight = static_weight

    # Backward flow maps each current pixel to its previous position.  Forward
    # flow is used only as a consistency check so newly revealed/occluded areas
    # never inherit detail from the wrong object.
    try:
        from .nvofa_temporal import _flow_to_output, _gray, _nvofa_flow, _warp
    except ImportError:
        from nvofa_temporal import _flow_to_output, _gray, _nvofa_flow, _warp

    small_height, small_width = current_analysis.shape[:2]
    # NVOFA runs on the dedicated Optical Flow Accelerator. The analysis frames,
    # bidirectional vectors, consistency map and confidence masks stay on CUDA.
    backward_flow = _nvofa_flow(current_analysis, previous_analysis, 4, "balanced")
    forward_flow = _nvofa_flow(previous_analysis, current_analysis, 4, "balanced")
    backward_flow = _flow_to_output(
        backward_flow, small_height, small_width,
        current_analysis.shape[0], current_analysis.shape[1],
    )
    forward_flow = _flow_to_output(
        forward_flow, small_height, small_width,
        current_analysis.shape[0], current_analysis.shape[1],
    )
    warped_previous_rgb, valid = _warp(
        previous_analysis, backward_flow, return_valid=True
    )
    sampled_forward = _warp(forward_flow, backward_flow)
    consistency_error = (backward_flow + sampled_forward).square().sum(-1).sqrt()
    flow_magnitude = backward_flow.square().sum(-1).sqrt()

    flow_tensor = backward_flow.permute(2, 0, 1).unsqueeze(0).to(dtype=base.dtype)
    flow_tensor = F.interpolate(
        flow_tensor, size=base.shape[1:], mode="bilinear", align_corners=True,
    )
    output_height, output_width = base.shape[1:]
    flow_tensor[:, 0].mul_(output_width / max(small_width, 1))
    flow_tensor[:, 1].mul_(output_height / max(small_height, 1))

    y, x = torch.meshgrid(
        torch.arange(output_height, device=base.device, dtype=base.dtype),
        torch.arange(output_width, device=base.device, dtype=base.dtype),
        indexing="ij",
    )
    grid_x = ((x + flow_tensor[0, 0]) / max(output_width - 1, 1)) * 2.0 - 1.0
    grid_y = ((y + flow_tensor[0, 1]) / max(output_height - 1, 1)) * 2.0 - 1.0
    grid = torch.stack((grid_x, grid_y), dim=-1).unsqueeze(0)
    if grid.dtype != previous_detail.dtype:
        grid = grid.to(dtype=previous_detail.dtype)
    warped_detail = F.grid_sample(
        previous_detail.unsqueeze(0),
        grid,
        mode="bilinear",
        padding_mode="border",
        align_corners=True,
    ).squeeze(0).to(dtype=base.dtype)

    difference = (_gray(current_analysis) - _gray(warped_previous_rgb)).abs()
    photometric_confidence = (1.0 - difference / 0.16).clamp(0, 1).square()
    flow_confidence = (1.0 - consistency_error / 2.50).clamp(0, 1).square()
    # Preserve history on stable parts of an action shot while aggressively
    # rejecting trails on rapidly moving limbs, hair, and camera-edge reveals.
    local_stability = 1.0 - ((flow_magnitude - 1.25) / 8.0).clamp(0, 1)
    confidence = photometric_confidence * flow_confidence * valid * (0.20 + 0.80 * local_stability)

    # Distant faces occupy very few pixels in the full-frame flow proxy.  Use a
    # slightly more tolerant confidence gate only inside tracked subject ROIs;
    # forward/backward consistency and the local motion guard still reject
    # occlusions, cuts, fast hands, and newly revealed background.
    subject_lock_active = subject_mask is not None and motion_score < 0.045
    if subject_lock_active:
        subject_small = F.interpolate(
            subject_mask.unsqueeze(0).float(),
            size=(small_height, small_width),
            mode="bilinear",
            align_corners=False,
        ).squeeze()
        subject_presence = (subject_small / 0.28).clamp(0, 1)
        subject_photo = (1.0 - difference / 0.22).clamp(0, 1).square()
        subject_flow = (1.0 - consistency_error / 3.20).clamp(0, 1).square()
        subject_stability = 1.0 - ((flow_magnitude - 1.60) / 9.5).clamp(0, 1)
        subject_confidence = (
            subject_photo
            * subject_flow
            * valid
            * (0.16 + 0.84 * subject_stability)
        )
        confidence = torch.maximum(confidence, subject_confidence * subject_presence)
    confidence_tensor = confidence.to(device=base.device, dtype=base.dtype)
    confidence_tensor = F.interpolate(
        confidence_tensor[None, None],
        size=base.shape[1:],
        mode="bilinear",
        align_corners=False,
    ).squeeze(0)

    local_stability_tensor = local_stability.to(device=base.device, dtype=base.dtype)
    local_stability_tensor = F.interpolate(
        local_stability_tensor[None, None],
        size=base.shape[1:],
        mode="bilinear",
        align_corners=False,
    ).squeeze(0)

    # Suppress only the unstable restoration residual; the current VSR base is
    # never temporally blurred.  This is what protects rapid hands and hair.
    action_guard_floor = 0.28 if mode == "Action Stable" else 0.34
    detail_guard = action_guard_floor + (1.0 - action_guard_floor) * local_stability_tensor
    if motion_score < 0.035:
        detail_guard = torch.ones_like(detail_guard)
    # Keep genuine VSR edges at full strength.  Only the more speculative
    # Denoise/Deblur/Master residual is attenuated on rapid local motion.
    guarded_detail = (
        base_detail + enhancement_detail * detail_guard
    ).clamp(-0.28, 0.28)

    # Even high-confidence optical flow can be a few pixels wrong on thin
    # objects.  Bound historical detail around the current frame so it cannot
    # create a second edge or face contour.
    history_limit = 0.040 if motion_score >= 0.045 else 0.055
    history_delta = warped_detail - guarded_detail
    face_presence = None
    face_temporal_active = face_mask is not None and motion_score < 0.085
    if face_temporal_active:
        # Motion-time face masks are intentionally weak, so normalize their
        # presence before using them as a temporal guard.  This affects only
        # tracked eye/nose/mouth detail and never introduces generated pixels.
        face_presence = (face_mask / 0.12).clamp(0.0, 1.0)
    if subject_lock_active:
        # Permit a little more identity-bearing eye/hair/clothing detail to
        # survive inside distant tracked subjects, while retaining a strict
        # bounded residual so a bad flow vector cannot create double contours.
        history_limit_map = history_limit + subject_mask * (
            0.010 if motion_score >= 0.045 else 0.020
        )
        history_delta = torch.maximum(
            torch.minimum(history_delta, history_limit_map),
            -history_limit_map,
        )
    else:
        if face_presence is not None:
            # Eye and nostril pixels are the first places where VSR residuals
            # jump.  Permit temporal agreement there, but cap the transferred
            # contrast more tightly than the rest of the frame.
            history_limit_map = history_limit - face_presence * 0.010
            history_delta = torch.maximum(
                torch.minimum(history_delta, history_limit_map),
                -history_limit_map,
            )
        else:
            history_delta = history_delta.clamp(-history_limit, history_limit)
    safe_warped_detail = guarded_detail + history_delta

    weight = confidence_tensor * temporal_weight
    if subject_mask is not None:
        # Up to roughly 65% historical detail is allowed on a stable distant
        # subject.  The confidence maps above, not this multiplier, decide
        # whether the history is safe to use on each pixel.
        boost = 0.58 if subject_lock_active else 0.14
        weight = weight * (1.0 + subject_mask * boost)
    if face_presence is not None:
        # A small extra history preference stabilizes facial feature pixels;
        # confidence/occlusion gates above still reject mismatched motion.
        weight = weight * (1.0 + face_presence * 0.24)
    weight = weight.clamp(0.0, 0.66 if subject_lock_active else 0.54)
    stable_detail = torch.lerp(guarded_detail, safe_warped_detail, weight)
    result = (base_low + stable_detail).clamp(0, 1)
    state["detail"] = stable_detail.detach().to(
        dtype=history_dtype or stable_detail.dtype
    )
    state["analysis"] = current_analysis.detach()
    return result


def auto_clean_color(
    image: torch.Tensor,
    mode: str,
    state: dict[str, torch.Tensor | float],
) -> torch.Tensor:
    """Temporally smoothed exposure and neutral-balance correction with highlight protection."""
    settings = COLOR_TREATMENTS[mode]
    if settings is None:
        return image

    height, width = image.shape[1:]
    analysis_scale = min(1.0, 320.0 / max(height, width))
    if analysis_scale < 1.0:
        analysis = F.interpolate(
            image.unsqueeze(0),
            scale_factor=analysis_scale,
            mode="bilinear",
            align_corners=False,
            antialias=True,
        ).squeeze(0)
    else:
        analysis = image

    luma = analysis[0] * 0.2126 + analysis[1] * 0.7152 + analysis[2] * 0.0722
    median = torch.quantile(luma.flatten(), 0.50).clamp(0.025, 0.975)
    highlight = torch.quantile(luma.flatten(), 0.97)
    gamma_target = torch.log(torch.tensor(settings["target_median"], device=image.device)) / torch.log(median)
    gamma_target = gamma_target.clamp(settings["min_gamma"], 1.08)
    if highlight > 0.90:
        gamma_target = torch.maximum(gamma_target, torch.tensor(0.90, device=image.device))

    previous_gamma = float(state.get("gamma", float(gamma_target.item())))
    gamma = previous_gamma * 0.86 + float(gamma_target.item()) * 0.14
    state["gamma"] = gamma

    channel_means = analysis.flatten(1).mean(dim=1).clamp_min(0.02)
    neutral = channel_means.mean()
    limit = settings["wb_limit"]
    wb_target = (neutral / channel_means).clamp(1.0 - limit, 1.0 + limit)
    previous_wb = state.get("white_balance")
    if isinstance(previous_wb, torch.Tensor):
        white_balance = previous_wb * 0.88 + wb_target * 0.12
    else:
        white_balance = wb_target
    state["white_balance"] = white_balance

    corrected = image.clamp_min(1.0 / 4096.0).pow(gamma)
    corrected = corrected * white_balance[:, None, None]
    corrected_luma = (
        corrected[0:1] * 0.2126
        + corrected[1:2] * 0.7152
        + corrected[2:3] * 0.0722
    )
    # Slight chroma restraint removes the dense AI cast without washing out skin.
    corrected = corrected_luma + (corrected - corrected_luma) * 0.985
    corrected = corrected.clamp(0, 1)
    return torch.lerp(image, corrected, settings["blend"]).clamp(0, 1)


def main() -> int:
    args = parse_args()
    frame_bytes = args.input_width * args.input_height * 4
    input_size = args.input.stat().st_size
    if input_size <= 0 or input_size % frame_bytes:
        raise ValueError("Input RGBA size is not an exact number of frames")
    frame_count = input_size // frame_bytes

    print(f"NVIDIA VFX SDK {get_sdk_version()} | {torch.cuda.get_device_name(0)}")
    print(
        f"Pipeline: {args.upscale_quality} {args.input_width}x{args.input_height} -> "
        f"{args.output_width}x{args.output_height} -> mandatory {args.restore_mode} "
        f"-> {args.quality_target} -> {args.temporal_mode} -> "
        f"Subject {args.subject_recovery} -> {args.color_treatment}"
    )
    if args.output_width % 64:
        print("VFX pitch-safe CUDA surface enabled; requested output size preserved")

    low_vram, free_gib, total_gib, memory_reason = resolve_memory_profile(
        args.memory_profile,
        args.output_width,
        args.output_height,
    )
    active_memory_profile = "Low VRAM" if low_vram else "Quality"
    print(
        f"Memory profile: {active_memory_profile} "
        f"(requested {args.memory_profile}; {free_gib:.1f}/{total_gib:.1f} GiB free; "
        f"reason={memory_reason}; output scale unchanged)"
    )

    upscale = make_effect(UPSCALE_MODES[args.upscale_quality], args.output_width, args.output_height)
    auto_scan = args.restore_mode == AUTO_RESTORE_MODE
    if auto_scan:
        clean_restorers = [
            make_effect(VideoSuperRes.QualityLevel.DEBLUR_LOW, args.output_width, args.output_height)
        ]
        if low_vram:
            # Reuse one resident restorer for both AUTO routes.  This preserves
            # the selected scale and avoids three full-resolution VFX models.
            chain_restorers = clean_restorers
            restorers = clean_restorers
        else:
            chain_restorers = [
                make_effect(VideoSuperRes.QualityLevel.DENOISE_LOW, args.output_width, args.output_height),
                make_effect(VideoSuperRes.QualityLevel.DEBLUR_MEDIUM, args.output_width, args.output_height),
            ]
            restorers = [*clean_restorers, *chain_restorers]
    else:
        requested_restorers = RESTORE_MODES[args.restore_mode]
        if low_vram and len(requested_restorers) > 1:
            # Prefer the low deblur pass when a multi-effect preset was chosen.
            requested_restorers = [
                VideoSuperRes.QualityLevel.DEBLUR_LOW
                if VideoSuperRes.QualityLevel.DEBLUR_LOW in requested_restorers
                else requested_restorers[0]
            ]
        clean_restorers = [
            make_effect(mode, args.output_width, args.output_height)
            for mode in requested_restorers
        ]
        chain_restorers = clean_restorers
        restorers = clean_restorers

    subject_tracker = SubjectRecoveryTracker(args.subject_recovery)
    subject_restorers: dict[str, list[VideoSuperRes]] = {}
    if subject_tracker.enabled:
        if low_vram:
            # A face-only local pass retains the highest-value identity detail
            # while avoiding the body model and the second face model.
            subject_restorers = {
                "face": [
                    make_effect(
                        VideoSuperRes.QualityLevel.DEBLUR_LOW,
                        SUBJECT_FACE_CANVAS_SIZE,
                        SUBJECT_FACE_CANVAS_SIZE,
                    ),
                ],
            }
        else:
            subject_restorers = {
            # Broad person regions get one gentle pass.  Tight faces get their
            # own restoration chain at a separate fixed resolution.
            "body": [
                make_effect(
                    VideoSuperRes.QualityLevel.DEBLUR_LOW,
                    SUBJECT_BODY_CANVAS_SIZE,
                    SUBJECT_BODY_CANVAS_SIZE,
                ),
            ],
            "face": [
                make_effect(
                    VideoSuperRes.QualityLevel.DENOISE_LOW,
                    SUBJECT_FACE_CANVAS_SIZE,
                    SUBJECT_FACE_CANVAS_SIZE,
                ),
                make_effect(
                    VideoSuperRes.QualityLevel.DEBLUR_LOW,
                    SUBJECT_FACE_CANVAS_SIZE,
                    SUBJECT_FACE_CANVAS_SIZE,
                ),
            ],
            }

    baseline_score: float | None = None
    quality_ema: float | None = None
    degraded_streak = 0
    recovered_streak = 0
    chain_active = False
    clean_frames = 0
    chain_frames = 0
    switch_frames: list[int] = []
    color_state: dict[str, torch.Tensor | float] = {}
    previous_motion_luma: torch.Tensor | None = None
    motion_guard_frames = 0
    scene_cut_frames: list[int] = []
    restoration_blend_total = 0.0
    restore_blend_ema: float | None = None
    temporal_state: dict[str, object] = {}
    subject_frames = 0
    subject_regions = 0
    subject_body_regions = 0
    subject_face_regions = 0
    auto_fullshot_frames = 0

    started = time.perf_counter()
    input_host = torch.empty(
        (args.input_height, args.input_width, 4),
        dtype=torch.uint8,
        pin_memory=True,
    )
    input_device = torch.empty_like(input_host, device="cuda")
    output_host = torch.empty(
        (args.output_height, args.output_width, 4),
        dtype=torch.uint8,
        pin_memory=True,
    )
    output_device = torch.empty_like(output_host, device="cuda")
    output_device[..., 3].fill_(255)
    input_view = memoryview(input_host.numpy()).cast("B")
    try:
        with args.input.open("rb") as source, args.output.open("wb") as destination:
            with torch.inference_mode():
                for index in range(frame_count):
                    read_count = source.readinto(input_view)
                    if read_count != frame_bytes:
                        raise RuntimeError(
                            f"Unexpected end of input at frame {index + 1}: "
                            f"expected {frame_bytes} bytes, got {read_count}"
                        )
                    input_device.copy_(input_host, non_blocking=True)
                    tensor = (
                        input_device[..., :3]
                        .to(dtype=torch.float32)
                        .div_(255.0)
                        .permute(2, 0, 1)
                        .contiguous()
                    )

                    active_restorers = clean_restorers
                    motion_score = 0.0
                    scene_cut = False
                    restore_blend = 1.0
                    motion_score, previous_motion_luma = frame_motion_score(
                        tensor, previous_motion_luma
                    )
                    scene_cut = motion_score >= 0.16
                    if scene_cut:
                        color_state.clear()
                        temporal_state.clear()
                        subject_tracker.boxes = []
                        if not auto_scan:
                            scene_cut_frames.append(index + 1)
                    if auto_scan:
                        score = frame_quality_score(tensor)
                        fast_motion = motion_score >= 0.045

                        if scene_cut:
                            baseline_score = score
                            quality_ema = score
                            degraded_streak = 0
                            recovered_streak = 0
                            chain_active = False
                            scene_cut_frames.append(index + 1)

                        quality_ema = score if quality_ema is None else quality_ema * 0.82 + score * 0.18
                        if baseline_score is None:
                            baseline_score = quality_ema
                        elif index < min(16, frame_count):
                            baseline_score = baseline_score * 0.8 + quality_ema * 0.2
                        else:
                            # Keep a slowly adapting per-shot reference instead of the
                            # strongest frame in the entire video.
                            baseline_score = max(baseline_score * 0.9975, quality_ema)

                        relative_quality = quality_ema / max(baseline_score, 1e-6)
                        if not chain_active:
                            degraded = relative_quality < 0.86 and motion_score < 0.035
                            degraded_streak = degraded_streak + 1 if degraded else 0
                            if degraded_streak >= 18:
                                chain_active = True
                                recovered_streak = 0
                                switch_frames.append(index + 1)
                        else:
                            recovered = relative_quality > 0.93 or fast_motion
                            recovered_streak = recovered_streak + 1 if recovered else 0
                            if recovered_streak >= 4:
                                chain_active = False
                                degraded_streak = 0
                                switch_frames.append(index + 1)
                        active_restorers = chain_restorers if chain_active else clean_restorers

                        # Blend restoration instead of stacking it at full strength.
                        # Cuts and fast motion stay VSR-first to preserve real texture.
                        if scene_cut or motion_score >= 0.070:
                            target_restore_blend = 0.0
                        elif fast_motion:
                            target_restore_blend = 0.10
                        elif chain_active:
                            severity = max(0.0, min(1.0, (0.90 - relative_quality) / 0.18))
                            target_restore_blend = 0.32 + severity * 0.23
                        elif motion_score >= 0.025:
                            target_restore_blend = 0.18
                        else:
                            target_restore_blend = 0.32

                        # Avoid visible strength jumps when AUTO changes between
                        # clean and late-chain recovery.  Release quickly on
                        # motion, but introduce stronger restoration gradually.
                        if scene_cut:
                            restore_blend_ema = 0.0
                        elif restore_blend_ema is None:
                            restore_blend_ema = target_restore_blend
                        else:
                            rate = 0.20 if target_restore_blend > restore_blend_ema else 0.58
                            restore_blend_ema += (target_restore_blend - restore_blend_ema) * rate
                        restore_blend = float(restore_blend_ema or 0.0)

                        if restore_blend < 0.18:
                            motion_guard_frames += 1

                    upscaled = _run_vfx_frame(
                        upscale, tensor, args.output_width, args.output_height
                    )
                    if float(upscaled.mean().item()) < 0.008 and float(tensor.mean().item()) > 0.03:
                        upscaled = F.interpolate(
                            tensor.unsqueeze(0),
                            size=(args.output_height, args.output_width),
                            mode="bicubic",
                            align_corners=False,
                            antialias=True,
                        ).squeeze(0).clamp(0, 1)
                    restored_effect = upscaled
                    if restore_blend > 0.0:
                        for effect in active_restorers:
                            restored_effect = _effect_frame(effect, restored_effect)
                    restored = torch.lerp(upscaled, restored_effect, restore_blend).clamp(0, 1)
                    restoration_blend_total += restore_blend

                    if chain_active:
                        chain_frames += 1
                    else:
                        clean_frames += 1

                    master_amount = QUALITY_TARGETS[args.quality_target]
                    if auto_scan:
                        if motion_score >= 0.045:
                            master_amount = 0.0
                        elif motion_score >= 0.025:
                            master_amount *= 0.35
                    restored = perceptual_master(restored, master_amount)

                    rois = subject_tracker.subject_rois(
                        tensor,
                        index,
                        args.output_width,
                        args.output_height,
                        motion_score,
                    )
                    if scene_cut or motion_score >= 0.085:
                        rois = []
                    elif motion_score >= 0.045:
                        rois = [
                            SubjectROI(
                                roi.x1,
                                roi.y1,
                                roi.x2,
                                roi.y2,
                                # Preserve a little more eye/mouth definition
                                # than the broad body pass, but lower the hard
                                # residual ceiling so isolated pixels cannot
                                # jump between frames.  This is VFX-only and
                                # never generates a replacement face.
                                roi.strength * (0.34 if roi.kind == "face" else 0.28),
                                roi.kind,
                                roi.residual_limit * (0.78 if roi.kind == "face" else 1.0),
                            )
                            for roi in rois
                        ]
                    # Low VRAM has a face-only subject restorer.  Ignore ROIs
                    # without an active local effect so masks/stats stay exact.
                    rois = [roi for roi in rois if roi.kind in subject_restorers]
                    restored, subject_mask, face_mask = recover_subjects(
                        upscaled,
                        restored,
                        rois,
                        subject_restorers,
                    )
                    if rois:
                        subject_frames += 1
                        subject_regions += len(rois)
                        subject_body_regions += sum(roi.kind == "body" for roi in rois)
                        subject_face_regions += sum(roi.kind == "face" for roi in rois)
                        if subject_tracker.last_profile == "fullshot":
                            auto_fullshot_frames += 1

                    # Full-shot faces can be only a few dozen source pixels.
                    # Preserve enough structure for stable optical flow instead
                    # of collapsing them into the default low-resolution proxy.
                    flow_analysis_size = (
                        448
                        if subject_tracker.last_profile == "fullshot"
                        and motion_score < 0.045
                        else 288
                    )
                    current_analysis = _analysis_cuda(
                        tensor,
                        max_side=flow_analysis_size,
                    )
                    restored = temporal_detail_lock(
                        upscaled,
                        restored,
                        current_analysis,
                        temporal_state,
                        args.temporal_mode,
                        motion_score,
                        scene_cut,
                        subject_mask,
                        face_mask,
                        torch.float16 if low_vram else None,
                    )
                    restored = auto_clean_color(restored, args.color_treatment, color_state)
                    write_rgba(destination, restored, output_host, output_device)

                    if (index + 1) % 10 == 0 or index + 1 == frame_count:
                        print(f"Processed {index + 1}/{frame_count} frames", flush=True)
    finally:
        upscale.close()
        for effect in restorers:
            effect.close()
        for effect_group in subject_restorers.values():
            for effect in effect_group:
                effect.close()
        torch.cuda.empty_cache()

    elapsed = time.perf_counter() - started
    if auto_scan:
        print(
            f"Auto scan routing: clean={clean_frames}, chain90={chain_frames}, "
            f"switches={switch_frames or 'none'}, motion_guard={motion_guard_frames}, "
            f"scene_cuts={scene_cut_frames or 'none'}, "
            f"mean_restore_blend={restoration_blend_total / max(frame_count, 1):.3f}"
        )
    print(
        f"Memory profile={active_memory_profile}; Temporal mode={args.temporal_mode}; "
        f"Subject Recovery={args.subject_recovery}, "
        f"subject_frames={subject_frames}, regions={subject_regions} "
        f"(body={subject_body_regions}, face={subject_face_regions}), "
        f"fullshot_profile_frames={auto_fullshot_frames}"
    )
    print(f"VFX 1.2 mandatory restoration completed in {elapsed:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
