from __future__ import annotations

import gc
import importlib.util
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
import torch.nn.functional as F


_BODY_LIMBS = (
    (5, 6),
    (5, 7), (7, 9),
    (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15),
    (12, 14), (14, 16),
)


def _max_box(mask: np.ndarray, box: np.ndarray, value: float) -> None:
    height, width = mask.shape
    x1, y1, x2, y2 = np.rint(box).astype(np.int32)
    x1, x2 = int(np.clip(x1, 0, width)), int(np.clip(x2, 0, width))
    y1, y2 = int(np.clip(y1, 0, height)), int(np.clip(y2, 0, height))
    if x2 > x1 and y2 > y1:
        view = mask[y1:y2, x1:x2]
        np.maximum(view, float(value), out=view)


class HumanStructureGuard:
    """Build a conservative human-region prior from local DWPose assets.

    The NVIDIA midpoint is still accepted only by the optical-flow quality test.
    This guard adds a second question: does the midpoint preserve or improve the
    detected human skeleton?  It never replaces a frame or increases the user's
    blend-strength ceiling.
    """

    def __init__(self, comfy_root: Path, width: int, height: int) -> None:
        self.width = int(width)
        self.height = int(height)
        self.enabled = False
        self.error = ""
        self.frames = 0
        self.pose_wins = 0
        self.pose_losses = 0
        self.neutral = 0
        self.temporal_wins = 0
        self.temporal_rejects = 0
        self.collapse_protected = 0
        self.defensive_recoveries = 0
        self.overlap_protections = 0
        self.output_checks = 0
        self.output_rejects = 0
        self.post_upscale_checks = 0
        self.post_upscale_rejects = 0
        self.last_post_upscale_score = 0.0
        self.fallbacks = 0
        self.faces_seen = 0
        self._last_faces: list[np.ndarray] = []
        self._misses = 0
        self.face_model = None
        self.pose_model = None
        self.pose_ops = None
        self._pending_output_audit = None

        face_path = comfy_root / "models" / "ultralytics" / "bbox" / "face_yolov8m.pt"
        aux_root = comfy_root / "custom_nodes" / "comfyui_controlnet_aux"
        pose_path = (
            aux_root / "ckpts" / "hr16" / "DWPose-TorchScript-BatchSize5"
            / "dw-ll_ucoco_384_bs5.torchscript.pt"
        )
        pose_code = (
            aux_root / "src" / "custom_controlnet_aux" / "dwpose"
            / "dw_torchscript" / "jit_pose.py"
        )
        missing = [str(path) for path in (face_path, pose_path, pose_code) if not path.is_file()]
        if missing or not torch.cuda.is_available():
            self.error = "missing local model or CUDA: " + ", ".join(missing)
            return

        try:
            from ultralytics import YOLO

            spec = importlib.util.spec_from_file_location("rtx_fruc_dwpose_ops", pose_code)
            if spec is None or spec.loader is None:
                raise RuntimeError("DWPose pose helper could not be loaded")
            pose_ops = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pose_ops)

            self.face_model = YOLO(str(face_path))
            self.pose_model = torch.jit.load(str(pose_path), map_location="cuda").eval().half()
            torch.backends.cudnn.benchmark = True
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            self.pose_ops = pose_ops
            self.enabled = True
            print(
                "NVIDIA FRUC human-structure guard active: CUDA face tracking + FP16 Tensor Core DWPose",
                flush=True,
            )
        except Exception as exc:
            self.error = str(exc)
            self.close()

    def _faces(self, *images: np.ndarray) -> list[np.ndarray]:
        detections: list[np.ndarray] = []
        valid_images = [np.ascontiguousarray(image) for image in images if image is not None]
        if valid_images:
            results = self.face_model.predict(
                source=valid_images,
                imgsz=640,
                conf=0.20,
                iou=0.50,
                max_det=4,
                device=0,
                half=True,
                verbose=False,
            )
            # Keep positions from the current frame when possible, then add
            # faces that only survive in the midpoint or neighbouring anchors.
            # This is essential for the reacting/defending subject, whose face
            # is often hidden while an attacker's face remains detectable.
            for result in results:
                if result.boxes is None or not len(result.boxes):
                    continue
                for raw_box in result.boxes.xyxy.detach().cpu().numpy():
                    box = raw_box.astype(np.float32)
                    if not any(self._same_face(box, known) for known in detections):
                        detections.append(box)

        return self._finalize_faces(detections)

    def _finalize_faces(self, detections: list[np.ndarray]) -> list[np.ndarray]:
        if detections:
            detections.sort(
                key=lambda box: float((box[2] - box[0]) * (box[3] - box[1])),
                reverse=True,
            )
            self._last_faces = detections[:4]
            detections = self._last_faces
            self._misses = 0
        elif self._last_faces and self._misses < 2:
            self._misses += 1
            detections = self._last_faces
        else:
            self._last_faces = []
            self._misses = 0
        return detections

    def _faces_cuda(self, *images: torch.Tensor) -> list[np.ndarray]:
        """Detect faces from CUDA tensors without downloading video frames."""
        valid = [image[..., :3] for image in images if isinstance(image, torch.Tensor)]
        if not valid:
            return self._finalize_faces([])
        batch = torch.stack(valid, dim=0).permute(0, 3, 1, 2).contiguous()
        if batch.dtype == torch.uint8:
            batch = batch.to(dtype=torch.float32).div_(255.0)
        else:
            batch = batch.to(dtype=torch.float32).clamp_(0, 1)
        # Match Ultralytics' 640-pixel analysis scale while keeping the complete
        # image on CUDA. Dimensions are multiples of 32 for the detector.
        detect_width = 640
        detect_height = max(32, int(round(self.height * detect_width / self.width / 32.0)) * 32)
        detect_height = min(640, detect_height)
        small = F.interpolate(
            batch, size=(detect_height, detect_width), mode="bilinear", align_corners=False
        ).to(dtype=torch.float16)
        results = self.face_model.predict(
            source=small,
            imgsz=(detect_height, detect_width),
            conf=0.20,
            iou=0.50,
            max_det=4,
            device=0,
            half=True,
            verbose=False,
        )
        scale = torch.tensor(
            [
                self.width / detect_width,
                self.height / detect_height,
                self.width / detect_width,
                self.height / detect_height,
            ],
            device=small.device,
            dtype=torch.float32,
        )
        detections: list[np.ndarray] = []
        for result in results:
            if result.boxes is None or not len(result.boxes):
                continue
            scaled = result.boxes.xyxy.to(dtype=torch.float32).mul(scale).cpu().numpy()
            for raw_box in scaled:
                box = raw_box.astype(np.float32)
                if not any(self._same_face(box, known) for known in detections):
                    detections.append(box)
        return self._finalize_faces(detections)

    @staticmethod
    def _same_face(first: np.ndarray, second: np.ndarray) -> bool:
        left = max(float(first[0]), float(second[0]))
        top = max(float(first[1]), float(second[1]))
        right = min(float(first[2]), float(second[2]))
        bottom = min(float(first[3]), float(second[3]))
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        first_area = max(1.0, float(first[2] - first[0]) * float(first[3] - first[1]))
        second_area = max(1.0, float(second[2] - second[0]) * float(second[3] - second[1]))
        union = first_area + second_area - intersection
        if intersection / max(1.0, union) >= 0.12:
            return True
        first_center = 0.5 * (first[:2] + first[2:4])
        second_center = 0.5 * (second[:2] + second[2:4])
        first_diag = float(np.linalg.norm(first[2:4] - first[:2]))
        second_diag = float(np.linalg.norm(second[2:4] - second[:2]))
        size_ratio = min(first_area, second_area) / max(first_area, second_area)
        return (
            size_ratio >= 0.40
            and float(np.linalg.norm(first_center - second_center))
            <= 0.55 * max(first_diag, second_diag, 1.0)
        )

    def _body_boxes(self, faces: list[np.ndarray]) -> np.ndarray:
        boxes = []
        for face in faces:
            x1, y1, x2, y2 = [float(value) for value in face]
            fw = max(6.0, x2 - x1)
            fh = max(6.0, y2 - y1)
            cx = 0.5 * (x1 + x2)
            boxes.append(
                [
                    max(0.0, cx - fw * 2.55),
                    max(0.0, y1 - fh * 1.05),
                    min(float(self.width), cx + fw * 2.55),
                    min(float(self.height), y2 + fh * 7.2),
                ]
            )
        return np.asarray(boxes, dtype=np.float32)

    def _paired_poses(
        self,
        current_rgb: np.ndarray,
        candidate_rgb: np.ndarray,
        boxes: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        current_crops, current_centers, current_scales = self.pose_ops.preprocess(
            current_rgb, boxes, (288, 384)
        )
        candidate_crops, candidate_centers, candidate_scales = self.pose_ops.preprocess(
            candidate_rgb, boxes, (288, 384)
        )
        count = len(current_crops)
        outputs = self.pose_ops.inference(
            self.pose_model, [*current_crops, *candidate_crops]
        )
        current_points, current_scores = self.pose_ops.postprocess(
            outputs[:count], (288, 384), current_centers, current_scales
        )
        candidate_points, candidate_scores = self.pose_ops.postprocess(
            outputs[count:], (288, 384), candidate_centers, candidate_scales
        )
        return current_points, current_scores, candidate_points, candidate_scores

    def _single_pose(
        self,
        frame_rgb: np.ndarray,
        boxes: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        crops, centers, scales = self.pose_ops.preprocess(frame_rgb, boxes, (288, 384))
        outputs = self.pose_ops.inference(self.pose_model, crops)
        return self.pose_ops.postprocess(outputs, (288, 384), centers, scales)

    def _poses_cuda(
        self,
        frames: list[torch.Tensor],
        boxes: np.ndarray,
    ) -> list[tuple[np.ndarray, np.ndarray]]:
        """Run all requested DWPose crops in one CUDA batch.

        Only the small keypoint coordinates and confidence values return to the
        host. Full video frames and model input crops stay on the GPU.
        """
        if len(boxes) == 0:
            empty_points = np.empty((0, 17, 2), dtype=np.float32)
            empty_scores = np.empty((0, 17), dtype=np.float32)
            return [(empty_points, empty_scores) for _ in frames]

        count = int(len(boxes))
        centers = torch.as_tensor(
            np.stack(((boxes[:, 0] + boxes[:, 2]) * 0.5,
                      (boxes[:, 1] + boxes[:, 3]) * 0.5), axis=1),
            device="cuda", dtype=torch.float32,
        )
        scales = torch.as_tensor(
            np.stack((boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]), axis=1),
            device="cuda", dtype=torch.float32,
        ).mul_(1.25)
        target_aspect = 288.0 / 384.0
        scale_w = scales[:, 0].clone()
        scale_h = scales[:, 1].clone()
        wider = scale_w > scale_h * target_aspect
        scales[:, 0] = torch.where(wider, scale_w, scale_h * target_aspect)
        scales[:, 1] = torch.where(wider, scale_w / target_aspect, scale_h)

        x_axis = torch.linspace(-0.5, 0.5, 288, device="cuda", dtype=torch.float32)
        y_axis = torch.linspace(-0.5, 0.5, 384, device="cuda", dtype=torch.float32)
        yy, xx = torch.meshgrid(y_axis, x_axis, indexing="ij")
        base_x = xx.unsqueeze(0)
        base_y = yy.unsqueeze(0)
        grid_x = centers[:, 0, None, None] + base_x * scales[:, 0, None, None]
        grid_y = centers[:, 1, None, None] + base_y * scales[:, 1, None, None]
        grid_x = grid_x.mul(2.0 / max(1, self.width - 1)).sub(1.0)
        grid_y = grid_y.mul(2.0 / max(1, self.height - 1)).sub(1.0)
        grid = torch.stack((grid_x, grid_y), dim=-1)

        all_crops = []
        for frame in frames:
            image = frame[..., :3].permute(2, 0, 1).unsqueeze(0)
            if image.dtype == torch.uint8:
                image = image.to(dtype=torch.float32)
            else:
                image = image.to(dtype=torch.float32).mul(255.0)
            image = image.expand(count, -1, -1, -1)
            crops = F.grid_sample(
                image, grid, mode="bilinear", padding_mode="zeros", align_corners=True
            )
            mean = torch.tensor([123.675, 116.28, 103.53], device=crops.device)[:, None, None]
            std = torch.tensor([58.395, 57.12, 57.375], device=crops.device)[:, None, None]
            all_crops.append((crops - mean) / std)

        model_input = torch.cat(all_crops, dim=0)
        model_dtype = next(self.pose_model.parameters()).dtype
        model_input = model_input.to(dtype=model_dtype)
        original_count = int(model_input.shape[0])
        remainder = original_count % 5
        if remainder:
            padding = torch.zeros(
                (5 - remainder, *model_input.shape[1:]),
                device=model_input.device, dtype=model_input.dtype,
            )
            model_input = torch.cat((model_input, padding), dim=0)

        out_x, out_y = [], []
        for start in range(0, int(model_input.shape[0]), 5):
            current_x, current_y = self.pose_model(model_input[start:start + 5])
            out_x.append(current_x.float())
            out_y.append(current_y.float())
        simcc_x = torch.cat(out_x, dim=0)[:original_count]
        simcc_y = torch.cat(out_y, dim=0)[:original_count]
        score_x, location_x = simcc_x.max(dim=-1)
        score_y, location_y = simcc_y.max(dim=-1)
        scores = torch.minimum(score_x, score_y)
        locations = torch.stack((location_x, location_y), dim=-1).to(torch.float32).div_(2.0)

        repeated_centers = centers.repeat(len(frames), 1)
        repeated_scales = scales.repeat(len(frames), 1)
        input_size = torch.tensor([288.0, 384.0], device=locations.device)
        locations = (
            locations.div(input_size)
            .mul(repeated_scales[:, None, :])
            .add(repeated_centers[:, None, :])
            .sub(repeated_scales[:, None, :] * 0.5)
        )
        locations = torch.where(scores[..., None] > 0, locations, torch.full_like(locations, -1.0))
        locations_cpu = locations.cpu().numpy()
        scores_cpu = scores.cpu().numpy()
        return [
            (
                locations_cpu[index * count:(index + 1) * count],
                scores_cpu[index * count:(index + 1) * count],
            )
            for index in range(len(frames))
        ]

    @staticmethod
    def _draw_pose_region(
        mask: np.ndarray,
        points: np.ndarray,
        scores: np.ndarray,
        box: np.ndarray,
        value: float,
        improvement: Optional[np.ndarray] = None,
    ) -> None:
        body_height = max(48.0, float(box[3] - box[1]))
        radius = max(7, int(round(body_height * 0.035)))
        line_width = max(9, int(round(body_height * 0.055)))
        valid_joints = [
            joint for joint in range(min(17, len(points)))
            if scores[joint] >= 0.25
            and (improvement is None or bool(improvement[joint]))
        ]
        valid_limbs = [
            (first, second) for first, second in _BODY_LIMBS
            if scores[first] >= 0.25 and scores[second] >= 0.25
            and (
                improvement is None
                or bool(improvement[first])
                or bool(improvement[second])
            )
        ]
        if not valid_joints and not valid_limbs:
            return

        used = set(valid_joints)
        for first, second in valid_limbs:
            used.add(first)
            used.add(second)
        used_points = points[list(used)]
        sigma = max(2.0, radius * 0.45)
        padding = radius + line_width + int(round(sigma * 4.0))
        height, width = mask.shape
        crop_x1 = max(0, int(np.floor(used_points[:, 0].min())) - padding)
        crop_x2 = min(width, int(np.ceil(used_points[:, 0].max())) + padding + 1)
        crop_y1 = max(0, int(np.floor(used_points[:, 1].min())) - padding)
        crop_y2 = min(height, int(np.ceil(used_points[:, 1].max())) + padding + 1)
        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return

        layer = np.zeros((crop_y2 - crop_y1, crop_x2 - crop_x1), dtype=np.uint8)
        offset = np.asarray([crop_x1, crop_y1], dtype=np.float32)
        for first, second in valid_limbs:
            p1 = tuple(np.rint(points[first] - offset).astype(np.int32))
            p2 = tuple(np.rint(points[second] - offset).astype(np.int32))
            cv2.line(layer, p1, p2, 255, line_width, cv2.LINE_AA)
        for joint in valid_joints:
            point = tuple(np.rint(points[joint] - offset).astype(np.int32))
            cv2.circle(layer, point, radius, 255, -1, cv2.LINE_AA)
        if layer.any():
            feather = cv2.GaussianBlur(
                layer.astype(np.float32) / 255.0,
                (0, 0),
                sigmaX=sigma,
                sigmaY=sigma,
                borderType=cv2.BORDER_DEFAULT,
            )
            target = mask[crop_y1:crop_y2, crop_x1:crop_x2]
            np.maximum(target, feather * float(value), out=target)

    def priority_map(
        self,
        current_rgb: np.ndarray,
        candidate_rgb: np.ndarray,
        frame_index: int,
        previous_rgb: Optional[np.ndarray] = None,
        next_rgb: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        if not self.enabled:
            self.fallbacks += 1
            return np.ones((self.height, self.width), dtype=np.float32)
        self.frames += 1
        self._pending_output_audit = None
        try:
            # A blurred action frame can hide every face. Search the immediate
            # anchors as well so that the structure gate stays active exactly
            # where fast motion makes the current frame hardest to detect.
            cuda_path = isinstance(current_rgb, torch.Tensor) and isinstance(candidate_rgb, torch.Tensor)
            if cuda_path:
                face_inputs = [current_rgb, candidate_rgb]
                if isinstance(previous_rgb, torch.Tensor):
                    face_inputs.append(previous_rgb)
                if isinstance(next_rgb, torch.Tensor):
                    face_inputs.append(next_rgb)
                faces = self._faces_cuda(*face_inputs)
            else:
                faces = self._faces(current_rgb, candidate_rgb, previous_rgb, next_rgb)
            if not faces:
                self.fallbacks += 1
                return np.full((self.height, self.width), 0.25, dtype=np.float32)
            self.faces_seen += len(faces)
            boxes = self._body_boxes(faces)
            temporal_available = previous_rgb is not None and next_rgb is not None
            if cuda_path:
                pose_frames = [current_rgb, candidate_rgb]
                if temporal_available:
                    pose_frames.extend((previous_rgb, next_rgb))
                pose_results = self._poses_cuda(pose_frames, boxes)
                current_points, current_scores = pose_results[0]
                candidate_points, candidate_scores = pose_results[1]
            else:
                current_points, current_scores, candidate_points, candidate_scores = self._paired_poses(
                    current_rgb, candidate_rgb, boxes
                )
            self._pending_output_audit = {
                "frame_index": int(frame_index),
                "boxes": boxes.copy(),
                "faces": [face.copy() for face in faces],
                "current_points": current_points.copy(),
                "current_scores": current_scores.copy(),
            }
            if temporal_available:
                if cuda_path:
                    previous_points, previous_scores = pose_results[2]
                    next_points, next_scores = pose_results[3]
                else:
                    previous_points, previous_scores, next_points, next_scores = self._paired_poses(
                        previous_rgb, next_rgb, boxes
                    )

            # Small background corrections are strongly de-emphasized.  Human
            # regions remain eligible, and joints that become clearer in the
            # midpoint receive the full user-selected strength.
            base_prior = 0.20
            boost = np.zeros((self.height, self.width), dtype=np.float32)
            reject = np.zeros((self.height, self.width), dtype=np.float32)
            critical_reject = np.zeros((self.height, self.width), dtype=np.float32)
            for person, (face, body) in enumerate(zip(faces, boxes)):
                current_body = current_scores[person, :17]
                candidate_body = candidate_scores[person, :17]
                visible_current = int(np.count_nonzero(current_body >= 0.30))
                visible_candidate = int(np.count_nonzero(candidate_body >= 0.30))
                quality_current = float(np.mean(np.sort(current_body)[-12:]))
                quality_candidate = float(np.mean(np.sort(candidate_body)[-12:]))
                quality_delta = quality_candidate - quality_current

                diagonal = max(48.0, float(np.linalg.norm(body[2:4] - body[:2])))
                displacement = np.linalg.norm(
                    candidate_points[person, :17] - current_points[person, :17], axis=1
                ) / diagonal
                plausible = displacement < 0.18
                improved = (
                    ((candidate_body - current_body) > 0.035) & plausible
                ) | ((current_body < 0.25) & (candidate_body > 0.40))

                temporal_win = False
                temporal_reject = False
                defensive_recovery = False
                consecutive_collapse = False
                if temporal_available:
                    previous_body = previous_scores[person, :17]
                    next_body = next_scores[person, :17]
                    anchor_valid = (previous_body >= 0.25) & (next_body >= 0.25)
                    anchor_count = int(np.count_nonzero(anchor_valid))
                    quality_previous = float(np.mean(np.sort(previous_body)[-12:]))
                    quality_next = float(np.mean(np.sort(next_body)[-12:]))
                    visible_previous = int(np.count_nonzero(previous_body >= 0.30))
                    visible_next = int(np.count_nonzero(next_body >= 0.30))

                    if anchor_count >= 6:
                        expected = 0.5 * (
                            previous_points[person, :17] + next_points[person, :17]
                        )
                        anchor_span = np.linalg.norm(
                            next_points[person, :17] - previous_points[person, :17], axis=1
                        ) / diagonal
                        current_error = np.linalg.norm(
                            current_points[person, :17] - expected, axis=1
                        ) / diagonal
                        candidate_error = np.linalg.norm(
                            candidate_points[person, :17] - expected, axis=1
                        ) / diagonal
                        valid = anchor_valid & (anchor_span < 0.34)
                        if int(np.count_nonzero(valid)) >= 6:
                            current_temporal = float(np.median(current_error[valid]))
                            candidate_temporal = float(np.median(candidate_error[valid]))
                            allowed_error = float(np.clip(
                                0.055 + 0.70 * np.median(anchor_span[valid]), 0.08, 0.22
                            ))
                            temporal_win = (
                                candidate_temporal + 0.012 < current_temporal
                                and candidate_temporal <= allowed_error
                                and quality_candidate + 0.010 >= quality_current
                            )
                            temporal_reject = (
                                candidate_temporal > allowed_error
                                and candidate_temporal > current_temporal + 0.025
                            )
                            # Reactions often fold behind the attacker for one
                            # frame. If both real anchors still see the person
                            # and FRUC moves the collapsed pose back toward that
                            # trajectory, give the reacting subject priority.
                            anchor_quality = min(quality_previous, quality_next)
                            anchor_visible = min(visible_previous, visible_next)
                            defensive_collapse = (
                                anchor_quality >= 0.46
                                and anchor_quality >= quality_current + 0.045
                                and anchor_visible >= visible_current + 2
                            )
                            defensive_recovery = (
                                defensive_collapse
                                and candidate_temporal <= allowed_error
                                and candidate_temporal + 0.006 < current_temporal
                                and (
                                    quality_candidate + 0.005 >= quality_current
                                    or visible_candidate >= visible_current + 1
                                )
                            )

                    consecutive_collapse = (
                        max(quality_previous, quality_current, quality_next) < 0.30
                        or max(visible_previous, visible_current, visible_next) < 6
                    )
                    if consecutive_collapse and not temporal_win:
                        self.collapse_protected += 1
                    if temporal_win:
                        self.temporal_wins += 1
                    if temporal_reject:
                        self.temporal_rejects += 1

                if temporal_reject or consecutive_collapse:
                    body_value = 0.0
                    self.pose_losses += 1
                elif defensive_recovery:
                    body_value = 0.96
                    self.defensive_recoveries += 1
                    self.pose_wins += 1
                elif temporal_win or quality_delta >= 0.012 or visible_candidate >= visible_current + 2:
                    body_value = 0.86
                    self.pose_wins += 1
                elif quality_delta <= -0.025 or visible_candidate + 2 <= visible_current:
                    body_value = 0.38
                    self.pose_losses += 1
                else:
                    body_value = 0.68
                    self.neutral += 1

                x1, y1, x2, y2 = face
                fw, fh = max(6.0, x2 - x1), max(6.0, y2 - y1)
                head_box = np.asarray(
                    [x1 - fw * 0.65, y1 - fh * 0.75, x2 + fw * 0.65, y2 + fh * 1.0],
                    dtype=np.float32,
                )
                if body_value <= 0.0:
                    # Suppress the complete tracked person region when the
                    # midpoint loses joints or leaves the trajectory between
                    # the two real anchor frames. This prevents a plausible but
                    # incorrect FRUC limb from overriding the current action.
                    _max_box(reject, body, 1.0)
                    _max_box(reject, head_box, 1.0)
                    _max_box(critical_reject, head_box, 1.0)
                    self._draw_pose_region(
                        critical_reject,
                        current_points[person],
                        current_scores[person],
                        body,
                        1.0,
                    )
                    if temporal_available:
                        self._draw_pose_region(
                            critical_reject,
                            previous_points[person],
                            previous_scores[person],
                            body,
                            0.82,
                        )
                        self._draw_pose_region(
                            critical_reject,
                            next_points[person],
                            next_scores[person],
                            body,
                            0.82,
                        )
                else:
                    _max_box(boost, body, body_value)
                    _max_box(boost, head_box, 0.90 if body_value >= 0.68 else 0.58)
                    self._draw_pose_region(
                        boost,
                        candidate_points[person],
                        candidate_scores[person],
                        body,
                        0.92 if body_value >= 0.86 else 0.68,
                    )
                    if np.any(improved):
                        self._draw_pose_region(
                            boost,
                            candidate_points[person],
                            candidate_scores[person],
                            body,
                            1.0,
                            improvement=improved,
                        )
            prior = np.maximum(base_prior, boost)
            # Preserve a rejected/reacting subject's head and joint trajectory
            # even when an accepted attacker overlaps the same broad body box.
            # The narrow critical map prevents that overlap rule from erasing
            # the defender while leaving the rest of the attacking motion free.
            overlap = (critical_reject > 0.08) & (boost >= 0.50)
            if overlap.any():
                self.overlap_protections += 1
            protected = ((reject > 0.0) & (boost < 0.50)) | (critical_reject > 0.08)
            prior[protected] = np.minimum(prior[protected], 0.035)
            return np.clip(prior, 0.0, 1.0)
        except Exception as exc:
            self.fallbacks += 1
            if self.fallbacks <= 3:
                print(
                    f"NVIDIA FRUC human-structure guard fallback at frame {frame_index + 1}: {exc}",
                    flush=True,
                )
            return np.full((self.height, self.width), 0.25, dtype=np.float32)

    def audit_output(
        self,
        current_rgb: np.ndarray | torch.Tensor,
        repaired_rgb: np.ndarray | torch.Tensor,
        frame_index: int,
    ) -> np.ndarray:
        """Revert only people whose pose becomes worse after the final blend."""
        pending = self._pending_output_audit
        self._pending_output_audit = None
        if not self.enabled or pending is None or pending["frame_index"] != int(frame_index):
            return repaired_rgb
        cuda_path = isinstance(current_rgb, torch.Tensor) and isinstance(repaired_rgb, torch.Tensor)
        if cuda_path:
            if float((repaired_rgb - current_rgb).abs().amax()) < (2.0 / 255.0):
                return repaired_rgb
        elif np.max(np.abs(repaired_rgb.astype(np.int16) - current_rgb.astype(np.int16))) < 2:
            return repaired_rgb

        try:
            boxes = pending["boxes"]
            if cuda_path:
                repaired_points, repaired_scores = self._poses_cuda([repaired_rgb], boxes)[0]
            else:
                repaired_points, repaired_scores = self._single_pose(repaired_rgb, boxes)
            current_points = pending["current_points"]
            current_scores = pending["current_scores"]
            restore = np.zeros((self.height, self.width), dtype=np.float32)
            rejected_people = 0
            self.output_checks += len(boxes)

            for person, (face, body) in enumerate(zip(pending["faces"], boxes)):
                current_body = current_scores[person, :17]
                repaired_body = repaired_scores[person, :17]
                quality_current = float(np.mean(np.sort(current_body)[-12:]))
                quality_repaired = float(np.mean(np.sort(repaired_body)[-12:]))
                visible_current = int(np.count_nonzero(current_body >= 0.30))
                visible_repaired = int(np.count_nonzero(repaired_body >= 0.30))
                stable = (current_body >= 0.28) & (repaired_body >= 0.28)
                diagonal = max(48.0, float(np.linalg.norm(body[2:4] - body[:2])))
                displacement = np.linalg.norm(
                    repaired_points[person, :17] - current_points[person, :17], axis=1
                ) / diagonal
                displaced = int(np.count_nonzero(stable & (displacement > 0.055)))
                lost = int(np.count_nonzero(
                    (current_body >= 0.32) & (repaired_body + 0.045 < current_body)
                ))

                reject_person = (
                    quality_repaired + 0.012 < quality_current
                    or visible_repaired + 1 < visible_current
                    or lost >= 3
                    or displaced >= 4
                )
                if not reject_person:
                    continue
                rejected_people += 1
                _max_box(restore, body, 1.0)
                x1, y1, x2, y2 = face
                fw, fh = max(6.0, x2 - x1), max(6.0, y2 - y1)
                _max_box(
                    restore,
                    np.asarray(
                        [x1 - fw * 0.65, y1 - fh * 0.75, x2 + fw * 0.65, y2 + fh],
                        dtype=np.float32,
                    ),
                    1.0,
                )

            if rejected_people == 0:
                return repaired_rgb
            self.output_rejects += rejected_people
            restore = cv2.GaussianBlur(restore, (0, 0), sigmaX=3.0, sigmaY=3.0)
            restore = np.clip(restore, 0.0, 1.0)[..., None]
            if cuda_path:
                restore_cuda = torch.from_numpy(restore).to(
                    device=repaired_rgb.device, dtype=repaired_rgb.dtype, non_blocking=True
                )
                return repaired_rgb * (1.0 - restore_cuda) + current_rgb * restore_cuda
            result = (
                repaired_rgb.astype(np.float32) * (1.0 - restore)
                + current_rgb.astype(np.float32) * restore
            )
            return np.clip(np.rint(result), 0, 255).astype(np.uint8)
        except Exception as exc:
            self.fallbacks += 1
            if self.fallbacks <= 3:
                print(
                    f"NVIDIA FRUC output audit fallback at frame {frame_index + 1}: {exc}",
                    flush=True,
                )
            return current_rgb

    def post_upscale_restore_mask(
        self,
        source_rgb: np.ndarray,
        restored_rgb: np.ndarray,
        frame_index: int,
    ) -> np.ndarray:
        """Mark reliable source people whose structure regressed in VSR."""
        self.last_post_upscale_score = 0.0
        if not self.enabled:
            return np.zeros((self.height, self.width), dtype=np.float32)
        try:
            cuda_path = isinstance(source_rgb, torch.Tensor) and isinstance(restored_rgb, torch.Tensor)
            if cuda_path:
                faces = self._faces_cuda(source_rgb, restored_rgb)
            else:
                faces = self._faces(source_rgb, restored_rgb)
            if not faces:
                return np.zeros((self.height, self.width), dtype=np.float32)
            boxes = self._body_boxes(faces)
            if cuda_path:
                pose_results = self._poses_cuda([source_rgb, restored_rgb], boxes)
                source_points, source_scores = pose_results[0]
                restored_points, restored_scores = pose_results[1]
            else:
                source_points, source_scores, restored_points, restored_scores = self._paired_poses(
                    source_rgb, restored_rgb, boxes
                )
            restore = np.zeros((self.height, self.width), dtype=np.float32)
            for person, (face, body) in enumerate(zip(faces, boxes)):
                source_body = source_scores[person, :17]
                restored_body = restored_scores[person, :17]
                quality_source = float(np.mean(np.sort(source_body)[-12:]))
                quality_restored = float(np.mean(np.sort(restored_body)[-12:]))
                visible_source = int(np.count_nonzero(source_body >= 0.30))
                visible_restored = int(np.count_nonzero(restored_body >= 0.30))
                stable = (source_body >= 0.28) & (restored_body >= 0.28)
                diagonal = max(48.0, float(np.linalg.norm(body[2:4] - body[:2])))
                displacement = np.linalg.norm(
                    restored_points[person, :17] - source_points[person, :17], axis=1
                ) / diagonal
                lost = int(np.count_nonzero(
                    (source_body >= 0.34) & (restored_body + 0.035 < source_body)
                ))
                displaced = int(np.count_nonzero(stable & (displacement > 0.045)))
                self.post_upscale_checks += 1

                # Low-confidence source poses are not trustworthy restoration
                # anchors. Limit correction to substantial regressions so VSR
                # detail is preserved on the other roughly 95% of people.
                reject_person = quality_source >= 0.52 and (
                    quality_restored + 0.020 < quality_source
                    or visible_restored + 3 < visible_source
                    or lost >= 4
                    or displaced >= 6
                )
                if not reject_person:
                    continue
                severity = max(
                    quality_source - quality_restored,
                    max(0, visible_source - visible_restored - 3) * 0.012,
                    max(0, lost - 3) * 0.010,
                    max(0, displaced - 5) * 0.008,
                )
                self.last_post_upscale_score = max(
                    self.last_post_upscale_score, float(severity)
                )
                self.post_upscale_rejects += 1
                _max_box(restore, body, 1.0)
                x1, y1, x2, y2 = face
                fw, fh = max(6.0, x2 - x1), max(6.0, y2 - y1)
                _max_box(
                    restore,
                    np.asarray(
                        [x1 - fw * 0.65, y1 - fh * 0.75, x2 + fw * 0.65, y2 + fh],
                        dtype=np.float32,
                    ),
                    1.0,
                )
            if restore.any():
                restore = cv2.GaussianBlur(restore, (0, 0), sigmaX=2.5, sigmaY=2.5)
            return np.clip(restore, 0.0, 1.0)
        except Exception as exc:
            self.fallbacks += 1
            if self.fallbacks <= 3:
                print(
                    f"NVIDIA FRUC post-upscale audit fallback at frame {frame_index + 1}: {exc}",
                    flush=True,
                )
            return np.zeros((self.height, self.width), dtype=np.float32)

    def summary(self) -> str:
        if not self.enabled:
            return "human-structure guard unavailable" + (f": {self.error}" if self.error else "")
        return (
            f"human poses={self.frames}, faces={self.faces_seen}, "
            f"pose wins={self.pose_wins}, protected={self.pose_losses}, "
            f"temporal wins={self.temporal_wins}, temporal rejects={self.temporal_rejects}, "
            f"defender recoveries={self.defensive_recoveries}, "
            f"overlap protections={self.overlap_protections}, "
            f"collapse protected={self.collapse_protected}, neutral={self.neutral}, "
            f"output checks={self.output_checks}, output rejects={self.output_rejects}, "
            f"post-VSR checks={self.post_upscale_checks}, post-VSR restores={self.post_upscale_rejects}, "
            f"fallbacks={self.fallbacks}"
        )

    def close(self) -> None:
        self.enabled = False
        self.face_model = None
        self.pose_model = None
        self.pose_ops = None
        self._pending_output_audit = None
        self.last_post_upscale_score = 0.0
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
