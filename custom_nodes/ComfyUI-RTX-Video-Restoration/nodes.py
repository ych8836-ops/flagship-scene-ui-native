from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import folder_paths
import numpy as np
import torch
import torch.nn.functional as F
from comfy_api.latest import ComfyExtension, Input, InputImpl, io, ui
from typing_extensions import override


NODE_ROOT = Path(__file__).resolve().parent

# Developer defaults for the internal NVOFA post-pass. These are intentionally
# plain source constants so the owner can tune or disable the stage directly.
NVOFA_TEMPORAL_REPAIR_ENABLED = True
NVOFA_FLOW_QUALITY = "balanced"
NVOFA_FLOW_GRID = "4x4"
NVOFA_REPAIR_STRENGTH = 0.30
NVOFA_ARTIFACT_SENSITIVITY = 0.55
NVOFA_MOTION_GUARD = 0.70
NVOFA_SCENE_CUT_THRESHOLD = 0.22
NVOFA_MAX_REPAIR_RATIO = 0.15
NVOFA_ANALYSIS_MAX_SIDE = 960
NVFRUC_MODE = "NVIDIA 가변 프레임 보간"
NVFRUC_LEGACY_MODE = "Action Strong + NVIDIA FRUC"


def _uses_nvfruc(mode: str) -> bool:
    return str(mode) in {NVFRUC_MODE, NVFRUC_LEGACY_MODE}


def _apply_nvfruc_source_repair(
    input_raw: Path,
    output_raw: Path,
    width: int,
    height: int,
    motion_repair_strength: int,
) -> Path:
    """Use SDK midpoint frames only inside detected damaged regions."""
    frame_bytes = int(width) * int(height) * 4
    raw_size = input_raw.stat().st_size
    if raw_size <= 0 or raw_size % frame_bytes:
        raise RuntimeError("NVIDIA FRUC 입력 RGBA 스트림 크기가 올바르지 않습니다.")
    frame_count = raw_size // frame_bytes
    if frame_count < 3:
        return input_raw

    try:
        from .human_structure_guard import HumanStructureGuard
        from .nvofa_temporal import NVOFATemporalArtifactRepair
        from .nvfruc_runtime import find_nvfruc_dll, generate_midpoint_candidates_cuda
    except ImportError:
        from human_structure_guard import HumanStructureGuard
        from nvofa_temporal import NVOFATemporalArtifactRepair
        from nvfruc_runtime import find_nvfruc_dll, generate_midpoint_candidates_cuda

    dll_path = find_nvfruc_dll(NODE_ROOT)
    source = np.memmap(
        input_raw, dtype=np.uint8, mode="r", shape=(frame_count, height, width, 4)
    )
    repair_node = NVOFATemporalArtifactRepair()
    structure_guard = HumanStructureGuard(Path(folder_paths.models_dir).parent, width, height)
    strength = max(0.10, min(0.50, float(motion_repair_strength) / 100.0))
    repaired_count = 0
    repeated_count = 0
    changed_frame_count = 0
    changed_ratio_sum = 0.0
    peak_changed_ratio = 0.0
    status = ""

    gpu_frames: dict[int, tuple[torch.Tensor, torch.Tensor]] = {}

    def source_cuda_frames():
        """Upload each source frame once and retain a rolling CUDA window."""
        for frame_index, frame in enumerate(source):
            host_rgba = np.asarray(frame)
            if not host_rgba.flags.c_contiguous or not host_rgba.flags.writeable:
                host_rgba = np.array(host_rgba, dtype=np.uint8, order="C", copy=True)
            rgba = torch.from_numpy(host_rgba).to(
                device="cuda", dtype=torch.uint8, non_blocking=False
            )
            rgb = rgba[..., :3].to(dtype=torch.float32).div_(255.0)
            gpu_frames[frame_index] = (rgba, rgb)
            yield rgba

    try:
        with output_raw.open("wb") as destination, torch.inference_mode():
            destination.write(np.asarray(source[0]).tobytes())
            for index, candidate_cuda, repeated in generate_midpoint_candidates_cuda(
                source_cuda_frames(), width, height, dll_path
            ):
                current = np.asarray(source[index]).copy()
                if repeated:
                    repeated_count += 1
                    destination.write(current.tobytes())
                    gpu_frames.pop(index - 1, None)
                    continue

                frames = torch.stack(
                    (
                        gpu_frames[index - 1][1],
                        gpu_frames[index][1],
                        gpu_frames[index + 1][1],
                    ),
                    dim=0,
                )
                candidates = frames.clone()
                candidates[1].copy_(
                    candidate_cuda[..., :3].to(dtype=torch.float32).div_(255.0)
                )
                region_prior = structure_guard.priority_map(
                    frames[1],
                    candidates[1],
                    index,
                    previous_rgb=frames[0],
                    next_rgb=frames[2],
                )
                repaired, status = repair_node.repair(
                    frames,
                    enabled=True,
                    backend="nvofa",
                    flow_quality="quality",
                    flow_grid="2x2",
                    repair_strength=strength,
                    artifact_sensitivity=0.60,
                    motion_guard=0.95,
                    scene_cut_threshold=NVOFA_SCENE_CUT_THRESHOLD,
                    max_repair_ratio=0.08,
                    analysis_max_side=min(NVOFA_ANALYSIS_MAX_SIDE, max(width, height)),
                    candidate_images=candidates,
                    region_prior=torch.from_numpy(region_prior).to(
                        device="cuda", dtype=torch.float32, non_blocking=True
                    ),
                )
                middle_cuda = (
                    repaired[1]
                )
                middle_cuda = structure_guard.audit_output(
                    frames[1], middle_cuda, index
                )
                middle_rgb = (
                    middle_cuda.mul(255.0)
                    .round()
                    .clamp(0, 255)
                    .to(torch.uint8)
                    .cpu()
                    .numpy()
                )
                changed_ratio = float(
                    (np.max(np.abs(middle_rgb.astype(np.int16) - current[..., :3].astype(np.int16)), axis=-1) >= 2).mean()
                )
                if changed_ratio > 0.10:
                    # A broad replacement means the candidate is describing a
                    # different action phase. Preserve the generated frame.
                    middle_rgb = current[..., :3]
                elif changed_ratio > 0.0:
                    changed_frame_count += 1
                    changed_ratio_sum += changed_ratio
                    peak_changed_ratio = max(peak_changed_ratio, changed_ratio)
                current[..., :3] = middle_rgb
                destination.write(current.tobytes())
                repaired_count += 1
                gpu_frames.pop(index - 1, None)
                if (index + 1) % 100 == 0:
                    print(
                        f"NVIDIA FRUC selective repair {index + 1}/{frame_count} frames",
                        flush=True,
                    )
            destination.write(np.asarray(source[-1]).tobytes())

    finally:
        gpu_frames.clear()
        # Drop the memmap before launching the VSR subprocess. Assignment is
        # also compatible with the protected Cython build's closure analysis.
        source = None
        structure_summary = structure_guard.summary()
        structure_guard.close()
        # The VSR worker starts in a separate process immediately after this
        # pass. Return cached allocations so 4x upscale gets the full VRAM.
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

    if not output_raw.is_file() or output_raw.stat().st_size != raw_size:
        raise RuntimeError("NVIDIA FRUC 수리 출력 프레임 수가 원본과 일치하지 않습니다.")
    print(
        f"{status}; FRUC candidates checked={repaired_count}, SDK repeats skipped={repeated_count}, "
        f"changed frames={changed_frame_count}, mean changed area="
        f"{(100.0 * changed_ratio_sum / max(1, changed_frame_count)):.3f}%, "
        f"peak changed area={100.0 * peak_changed_ratio:.3f}%; "
        f"source-resolution repair={width}x{height}; {structure_summary}",
        flush=True,
    )
    return output_raw


def _apply_nvofa_temporal_repair(
    input_raw: Path,
    output_raw: Path,
    width: int,
    height: int,
    motion_repair: str = "Auto",
    motion_repair_strength: int = 30,
) -> Path:
    """Repair only the middle frame of each real prev/current/next triplet."""
    mode = str(motion_repair or "Auto")
    if not NVOFA_TEMPORAL_REPAIR_ENABLED or mode == "Off":
        return input_raw

    strength = max(0.0, min(1.0, float(motion_repair_strength) / 100.0))
    # Auto keeps automatic artifact-region detection, but repairs every detected
    # region with the same quality floor and safeguards as Action Strong.
    if mode in {"Auto", "Action Strong"}:
        flow_quality = "quality"
        flow_grid = "2x2"
        strength = max(strength, 0.38)
        motion_guard = 0.78
        max_repair_ratio = 0.18
    else:
        flow_quality = NVOFA_FLOW_QUALITY
        flow_grid = NVOFA_FLOW_GRID
        motion_guard = NVOFA_MOTION_GUARD
        max_repair_ratio = NVOFA_MAX_REPAIR_RATIO

    frame_bytes = int(width) * int(height) * 4
    raw_size = input_raw.stat().st_size
    if raw_size <= 0 or raw_size % frame_bytes:
        print("NVOFA temporal repair skipped: invalid RGBA raw stream")
        return input_raw
    frame_count = raw_size // frame_bytes
    if frame_count < 3:
        print("NVOFA temporal repair skipped: fewer than 3 frames")
        return input_raw

    try:
        from .nvofa_temporal import NVOFATemporalArtifactRepair
    except ImportError:
        from nvofa_temporal import NVOFATemporalArtifactRepair

    repair_node = NVOFATemporalArtifactRepair()

    def read_frame(stream) -> np.ndarray:
        payload = stream.read(frame_bytes)
        if len(payload) != frame_bytes:
            raise RuntimeError("Unexpected end of NVOFA RGBA stream")
        return np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4).copy()

    try:
        with input_raw.open("rb") as source, output_raw.open("wb") as destination:
            previous = read_frame(source)
            current = read_frame(source)
            destination.write(previous.tobytes())
            status = ""

            with torch.inference_mode():
                for index in range(1, frame_count - 1):
                    following = read_frame(source)
                    rgb_triplet = np.stack(
                        (previous[..., :3], current[..., :3], following[..., :3]),
                        axis=0,
                    )
                    frames = (
                        torch.from_numpy(rgb_triplet)
                        .to(device="cuda", dtype=torch.float32, non_blocking=True)
                        .div_(255.0)
                    )
                    repaired, status = repair_node.repair(
                        frames,
                        enabled=True,
                        backend="nvofa",
                        flow_quality=flow_quality,
                        flow_grid=flow_grid,
                        repair_strength=strength,
                        artifact_sensitivity=NVOFA_ARTIFACT_SENSITIVITY,
                        motion_guard=motion_guard,
                        scene_cut_threshold=NVOFA_SCENE_CUT_THRESHOLD,
                        max_repair_ratio=max_repair_ratio,
                        analysis_max_side=NVOFA_ANALYSIS_MAX_SIDE,
                    )
                    middle_rgb = (
                        repaired[1]
                        .mul(255.0)
                        .round()
                        .clamp(0, 255)
                        .to(torch.uint8)
                        .cpu()
                        .numpy()
                    )
                    output_frame = current.copy()
                    output_frame[..., :3] = middle_rgb
                    destination.write(output_frame.tobytes())
                    previous, current = current, following

                    if (index + 1) % 100 == 0:
                        print(
                            f"NVOFA temporal repair {index + 1}/{frame_count} frames",
                            flush=True,
                        )

            destination.write(current.tobytes())
        print(f"{status}; repaired raw stream={output_raw.name}")
        return output_raw
    except Exception as exc:
        if output_raw.exists():
            output_raw.unlink(missing_ok=True)
        print(f"NVOFA temporal repair skipped safely: {exc}")
        return input_raw


def _apply_post_upscale_human_guard(
    source_raw: Path,
    restored_raw: Path,
    source_width: int,
    source_height: int,
    output_width: int,
    output_height: int,
) -> None:
    """Audit VSR geometry and restore only regressed, reliable people."""
    import cv2

    try:
        from .human_structure_guard import HumanStructureGuard
    except ImportError:
        from human_structure_guard import HumanStructureGuard

    source_frame_bytes = int(source_width) * int(source_height) * 4
    output_frame_bytes = int(output_width) * int(output_height) * 4
    source_size = source_raw.stat().st_size
    output_size = restored_raw.stat().st_size
    if source_size % source_frame_bytes or output_size % output_frame_bytes:
        raise RuntimeError("NVIDIA post-VSR 인체 검사 입력 스트림 크기가 올바르지 않습니다.")
    frame_count = source_size // source_frame_bytes
    if frame_count != output_size // output_frame_bytes:
        raise RuntimeError("NVIDIA post-VSR 인체 검사 프레임 수가 일치하지 않습니다.")

    source = np.memmap(
        source_raw, dtype=np.uint8, mode="r",
        shape=(frame_count, source_height, source_width, 4),
    )
    restored = np.memmap(
        restored_raw, dtype=np.uint8, mode="r+",
        shape=(frame_count, output_height, output_width, 4),
    )
    guard = HumanStructureGuard(Path(folder_paths.models_dir).parent, source_width, source_height)
    changed_frames = 0
    candidates: list[tuple[float, int, np.ndarray]] = []
    compact_width = max(1, (int(source_width) + 3) // 4)
    compact_height = max(1, (int(source_height) + 3) // 4)
    try:
        with torch.inference_mode():
            for index in range(frame_count):
                source_rgb = np.asarray(source[index, ..., :3])
                output_rgb = np.asarray(restored[index, ..., :3])
                source_cuda = (
                    torch.from_numpy(np.array(source_rgb, copy=True))
                    .to(device="cuda", dtype=torch.float16, non_blocking=False)
                    .div_(255.0)
                )
                output_cuda_chw = (
                    torch.from_numpy(np.array(output_rgb, copy=True))
                    .to(device="cuda", dtype=torch.float16, non_blocking=False)
                    .permute(2, 0, 1)
                    .div_(255.0)
                )
                output_small_cuda = F.interpolate(
                    output_cuda_chw.unsqueeze(0),
                    size=(source_height, source_width),
                    mode="area",
                )[0].permute(1, 2, 0).contiguous()
                mask = guard.post_upscale_restore_mask(
                    source_cuda, output_small_cuda, index
                )
                if not mask.any():
                    continue
                compact_mask = cv2.resize(
                    mask, (compact_width, compact_height), interpolation=cv2.INTER_AREA
                )
                candidates.append((
                    float(guard.last_post_upscale_score),
                    int(index),
                    np.clip(np.rint(compact_mask * 255.0), 0, 255).astype(np.uint8),
                ))
                if (index + 1) % 100 == 0:
                    print(
                        f"NVIDIA post-VSR human guard {index + 1}/{frame_count} frames",
                        flush=True,
                    )

        maximum_changed_frames = max(1, int(round(frame_count * 0.05)))
        selected = sorted(candidates, key=lambda item: item[0], reverse=True)[
            :maximum_changed_frames
        ]
        for _severity, index, compact_mask in selected:
            source_rgb = np.asarray(source[index, ..., :3])
            output_rgb = np.asarray(restored[index, ..., :3])
            source_cuda = (
                torch.from_numpy(np.array(source_rgb, copy=True))
                .to(device="cuda", dtype=torch.float32, non_blocking=False)
                .permute(2, 0, 1)
            )
            output_cuda = (
                torch.from_numpy(np.array(output_rgb, copy=True))
                .to(device="cuda", dtype=torch.float32, non_blocking=False)
                .permute(2, 0, 1)
            )
            output_small_cuda = F.interpolate(
                output_cuda.unsqueeze(0),
                size=(source_height, source_width),
                mode="area",
            )[0]
            baseline = F.interpolate(
                source_cuda.unsqueeze(0),
                size=(output_height, output_width),
                mode="bicubic",
                align_corners=False,
                antialias=True,
            )[0]
            # Match the VSR frame's global color before restoring geometry,
            # avoiding a one-frame brightness or saturation pulse.
            source_mean = source_cuda.mean(dim=(1, 2), keepdim=True)
            output_mean = output_small_cuda.mean(dim=(1, 2), keepdim=True)
            source_std = source_cuda.std(dim=(1, 2), keepdim=True).clamp_min(1.0)
            output_std = output_small_cuda.std(dim=(1, 2), keepdim=True).clamp_min(1.0)
            scale = (output_std / source_std).clamp(0.88, 1.14)
            baseline = ((baseline - source_mean) * scale + output_mean).clamp(0.0, 255.0)

            mask_cuda = torch.from_numpy(compact_mask).to(
                device="cuda", dtype=torch.float32, non_blocking=False
            ).div_(255.0)
            mask_large = F.interpolate(
                mask_cuda[None, None],
                size=(output_height, output_width),
                mode="bilinear",
                align_corners=False,
            )[0]
            blend = mask_large.mul_(0.80).clamp_(0.0, 0.80)
            corrected = output_cuda * (1.0 - blend) + baseline * blend
            restored[index, ..., :3] = (
                corrected.round().clamp(0, 255).to(torch.uint8)
                .permute(1, 2, 0).cpu().numpy()
            )
            changed_frames += 1
        restored.flush()
        print(
            f"NVIDIA post-VSR human guard complete; candidate frames={len(candidates)}, "
            f"selected frames={changed_frames}/{frame_count} (5% cap); "
            f"{guard.summary()}",
            flush=True,
        )
    finally:
        del restored
        del source
        guard.close()
def _resolve_ffmpeg() -> str:
    # Prefer ComfyUI's bundled FFmpeg. Its NVENC API matches the installed driver,
    # while a newer system FFmpeg may require a newer NVIDIA driver.
    try:
        import imageio_ffmpeg

        candidate = imageio_ffmpeg.get_ffmpeg_exe()
        if candidate and Path(candidate).is_file():
            return candidate
    except Exception:
        pass
    discovered = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
    if discovered:
        return discovered
    raise FileNotFoundError("FFmpeg를 찾지 못했습니다. FFmpeg가 PATH에 등록되어 있어야 합니다.")


def _stage_video(video: Any, job_dir: Path) -> Path:
    source = video.get_stream_source()
    start_time, trim_duration = (0.0, 0.0)
    if hasattr(video, "get_active_trim_window"):
        start_time, trim_duration = video.get_active_trim_window()

    if isinstance(source, (str, os.PathLike)) and not start_time and not trim_duration:
        source_path = Path(source)
        if source_path.is_file():
            return source_path.resolve()

    staged = job_dir / "source.mp4"
    video.save_to(str(staged))
    return staged


def _video_fps(path: Path) -> Fraction:
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise RuntimeError("입력에 비디오 스트림이 없습니다.")
        stream = container.streams.video[0]
        rate = stream.average_rate or stream.base_rate or stream.guessed_rate
        if rate is None or rate <= 0:
            return Fraction(24, 1)
        return Fraction(rate)


def _nvdec_download_format(path: Path) -> str:
    """Return the CUDA surface format required by FFmpeg hwdownload."""
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise RuntimeError("입력에 비디오 스트림이 없습니다.")
        context = container.streams.video[0].codec_context
        pixel_format = str(getattr(getattr(context, "format", None), "name", "") or "").lower()

    # Our SDR 10-bit and HDR outputs are HEVC Main10. NVDEC exposes those CUDA
    # frames as P010, while ordinary 8-bit H.264/HEVC surfaces are NV12.
    if pixel_format in {"p010le", "yuv420p10le"} or "420p10" in pixel_format:
        return "p010le"
    return "nv12"


def _run(command: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        details = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip()
        )
        raise RuntimeError(details[-12000:] or "외부 영상 처리 프로그램이 실패했습니다.")
    if completed.stdout and completed.stdout.strip():
        print(completed.stdout.strip())


def _snap_even(value: float) -> int:
    return max(2, int(round(float(value) / 2.0) * 2))


def _quality_to_quantizer(quality: int) -> int:
    """Map the user-facing 80-99 range to a conservative H.264 QP/CRF 18-4."""
    bounded = min(99, max(80, int(quality)))
    return round(18 - ((bounded - 80) * 14 / 19))


def _nvenc_preset(profile: str) -> str:
    return {"medium": "p5", "slow": "p6", "slower": "p7"}.get(profile, "p6")


def _hdr_filter(gpu: bool = False) -> str:
    # The restoration core emits full-range, transfer-encoded Rec.709 RGBA8.
    # Decode the transfer in float before mapping reference white to 203 cd/m².
    # Do not merely tag SDR pixels as PQ, invent highlights, or claim 10-bit
    # source precision. zscale performs both gamut and transfer conversion.
    result = (
        "format=gbrpf32le,"
        "zscale=pin=bt709:tin=bt709:min=gbr:rin=full:"
        "p=bt2020:t=linear:m=gbr:r=full,"
        "zscale=pin=bt2020:tin=linear:min=gbr:rin=full:"
        "p=bt2020:t=smpte2084:m=bt2020nc:r=limited:npl=203:dither=error_diffusion,"
        "format=yuv420p10le"
    )
    return result + (",format=p010le,hwupload_cuda" if gpu else "")


def _resolve_output_mode(output_mode: str | None = None, hdr_enabled: bool = False) -> str:
    if output_mode is None:
        return "HDR" if hdr_enabled else "SDR"
    if output_mode not in ("SDR", "SDR 10bit", "HDR"):
        raise ValueError(f"지원하지 않는 출력 모드: {output_mode}")
    return output_mode


def _sdr10_filter(gpu: bool = False) -> str:
    result = (
        "format=gbrpf32le,"
        "zscale=pin=bt709:tin=bt709:min=gbr:rin=full:"
        "p=bt709:t=bt709:m=bt709:r=limited:dither=error_diffusion,"
        "format=yuv420p10le"
    )
    return result + (",format=p010le,hwupload_cuda" if gpu else "")


def _output_encoding(
    output_mode: str | bool, gpu: bool, preset: str, quantizer: int,
    output_size: tuple[int, int] | None = None,
) -> list[str]:
    if isinstance(output_mode, bool):
        output_mode = _resolve_output_mode(None, output_mode)
    output_mode = _resolve_output_mode(output_mode)
    if output_mode != "SDR":
        hdr_enabled = output_mode == "HDR"
        common = [
            "-vf", _hdr_filter(gpu) if hdr_enabled else _sdr10_filter(gpu), "-profile:v", "main10",
            "-color_primaries", "bt2020" if hdr_enabled else "bt709",
            "-color_trc", "smpte2084" if hdr_enabled else "bt709",
            "-colorspace", "bt2020nc" if hdr_enabled else "bt709",
            "-color_range", "tv", "-tag:v", "hvc1",
        ]
        if gpu:
            return common + ["-c:v", "hevc_nvenc", "-preset", _nvenc_preset(preset),
                             "-tune", "hq", "-rc", "constqp", "-qp", str(quantizer),
                             "-spatial-aq", "1", "-temporal-aq", "1", "-aq-strength", "8"]
        return common + ["-c:v", "libx265", "-preset", preset, "-crf", str(quantizer),
                         "-pix_fmt", "yuv420p10le"]
    # H.264 NVENC rejects oversized frames, including tall portrait videos.
    if gpu:
        use_hevc = output_size is not None and max(output_size) > 4096
        return ["-vf", "format=nv12,hwupload_cuda", "-c:v", "hevc_nvenc" if use_hevc else "h264_nvenc",
                "-preset", _nvenc_preset(preset), "-tune", "hq", "-rc", "constqp",
                "-qp", str(quantizer), "-spatial-aq", "1", "-temporal-aq", "1",
                "-aq-strength", "8"] + (["-tag:v", "hvc1"] if use_hevc else [])
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(quantizer), "-pix_fmt", "yuv420p"]


def _validate_hdr_source(path: Path) -> None:
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        context = stream.codec_context
        if context.color_trc in (16, 18) or context.color_primaries == 9:
            raise ValueError(
                "HDR 출력은 SDR Rec.709 원본을 변환하는 옵션입니다. "
                "현재 복원 엔진은 원본 HDR/BT.2020 보존을 지원하지 않으므로 "
                "먼저 별도로 SDR 톤매핑한 영상을 사용하세요."
            )


def _validate_hdr_output(path: Path) -> None:
    with av.open(str(path)) as container:
        context = container.streams.video[0].codec_context
        if (context.name != "hevc" or context.format.name != "yuv420p10le"
                or context.color_primaries != 9 or context.color_trc != 16
                or context.colorspace != 9 or context.color_range != 1):
            raise RuntimeError("HDR 출력 검증 실패: HEVC 10-bit / BT.2020 / PQ / limited 신호가 올바르지 않습니다.")


def _validate_sdr10_output(path: Path) -> None:
    with av.open(str(path)) as container:
        context = container.streams.video[0].codec_context
        if (context.name != "hevc" or context.format.name != "yuv420p10le"
                or context.color_primaries != 1 or context.color_trc != 1
                or context.colorspace != 1 or context.color_range != 1):
            raise RuntimeError("SDR 10bit 출력 검증 실패: HEVC Main10 / Rec.709 / limited 신호가 올바르지 않습니다.")


class RTXVideoVSRRestore(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="RTXVideoVSRRestore",
            display_name="SRFPTyp 업스케일러",
            category="video/upscaling",
            description=(
                "고품질 영상 확대, 움직임 보호형 디테일 복원과 시간축 안정화를 "
                "순서대로 적용합니다. 원본 오디오는 그대로 유지합니다."
            ),
            search_aliases=["srfptyp", "video upscale", "video restoration"],
            inputs=[
                io.Video.Input("video", tooltip="업스케일할 VIDEO 입력"),
                io.Float.Input(
                    "scale",
                    default=2.0,
                    min=1.0,
                    max=4.0,
                    step=0.05,
                    tooltip="출력 확대 배수. 1280×720에서 2.0이면 2560×1440입니다.",
                ),
                io.Combo.Input(
                    "upscale_quality",
                    options=["Ultra", "High", "High-Bitrate Ultra", "High-Bitrate High"],
                    default="Ultra",
                    tooltip="1차 고품질 확대 엔진",
                ),
                io.Combo.Input(
                    "restore_mode",
                    options=[
                        "Auto Scan (Clean/Chain90)",
                        "Deblur Low",
                        "Deblur Medium",
                        "Denoise Low",
                        "Denoise Low + Deblur Low",
                        "Chain Late Recovery 90",
                    ],
                    default="Auto Scan (Clean/Chain90)",
                    tooltip=(
                        "Auto Scan은 장면별 품질과 움직임을 함께 검사합니다. 빠른 동작과 "
                        "장면 전환에서는 강복원을 막고, 지속된 정적 열화에서만 제한적으로 "
                        "Chain 복원을 혼합해 수채화 현상과 윤곽 파손을 줄입니다."
                    ),
                ),
                io.Combo.Input(
                    "quality_target",
                    options=["100% Restore", "105% Master", "110% Master"],
                    default="110% Master",
                    tooltip=(
                        "기본 복원 뒤 미세 디테일을 최대 10% 추가합니다. "
                        "색상과 전체 밝기는 유지하며 링잉은 제한합니다."
                    ),
                ),
                io.Combo.Input(
                    "color_treatment",
                    options=["Off", "Auto Natural", "Auto Bright"],
                    default="Auto Natural",
                    tooltip=(
                        "프레임 밝기와 RGB 편차를 시간축으로 분석해 어두운 AI 색조를 "
                        "자동 보정합니다. Natural은 하이라이트와 야간 분위기를 보호합니다."
                    ),
                ),
                io.Int.Input(
                    "output_quality",
                    default=95,
                    min=80,
                    max=99,
                    step=1,
                    tooltip=(
                        "최종 저장 품질입니다. 80은 고품질/작은 파일, "
                        "95는 권장, 99는 최고품질/큰 파일입니다."
                    ),
                ),
                io.Combo.Input(
                    "encode_preset",
                    options=["medium", "slow", "slower"],
                    default="slow",
                ),
                io.Combo.Input(
                    "temporal_mode",
                    options=["Auto Temporal", "Face Lock", "Action Stable", "Off"],
                    default="Auto Temporal",
                    tooltip=(
                        "양방향 움직임 분석으로 고주파와 복원 디테일을 추적하고, "
                        "가림·새 영역·빠른 손발에서는 과거 디테일을 자동 차단합니다. "
                        "전신·원거리 장면은 분석 해상도와 인물 잠금을 자동 강화하고, "
                        "빠른 동작에서는 기존 Action Safe 강도로 즉시 복귀합니다. "
                        "Auto는 일반 영상, Face Lock은 느린 인물 클로즈업, "
                        "Action은 빠른 움직임의 잔상 방지에 적합합니다."
                    ),
                ),
                io.Combo.Input(
                    "subject_recovery",
                    options=["Auto", "Full Shot Strong", "Off"],
                    default="Auto",
                    tooltip=(
                        "Auto는 영상 전체에서 샷 크기를 계속 검사하고, 작은 얼굴이나 "
                        "다인 전신 장면에서는 얼굴과 전신을 서로 다른 크기로 자동 복원합니다. "
                        "가까운 얼굴은 피부 질감을 보호하고 작은 배경 얼굴은 별도 확대합니다. "
                        "Full Shot Strong은 전신·원거리 인물 복원을 강제로 유지합니다."
                    ),
                ),
                io.Boolean.Input(
                    "enabled",
                    default=True,
                    optional=True,
                    tooltip="끄면 복원 처리를 건너뛰고 입력 VIDEO를 그대로 전달합니다.",
                ),
                io.Boolean.Input(
                    "hdr_enabled",
                    default=False,
                    optional=True,
                    tooltip=(
                        "켜면 SDR 복원 결과를 HEVC 10-bit BT.2020/PQ HDR로 변환합니다. "
                        "기준 백색 203nit. 원본의 잃어버린 하이라이트를 복원하는 기능은 아닙니다. "
                        "HDR 화면/재생기 필요. 뒤쪽 Save Video는 format/codec을 auto로 유지하세요."
                    ),
                ),
                io.Combo.Input(
                    "output_mode", options=["SDR", "SDR 10bit", "HDR"],
                    default="SDR", optional=True,
                    tooltip="SDR: H.264 8bit. SDR 10bit: HEVC Main10 Rec.709. HDR: HEVC Main10 BT.2020/PQ 203nit 변환. Save Video codec/format은 auto로 유지하세요.",
                ),
                io.Combo.Input(
                    "motion_repair",
                    options=["Auto", "Action Strong", NVFRUC_MODE, "Off"],
                    default="Auto",
                    optional=True,
                    tooltip=(
                        "NVOFA Optical Flow로 앞·현재·뒤 실제 프레임을 비교해 빠른 움직임의 "
                        "순간 프레임 터짐, 이중 윤곽, 계단식 경계와 색 번짐이 감지된 작은 영역만 복원합니다. "
                        "NVIDIA 가변 프레임 보간은 생성 원본에서 SDK 중간 프레임을 만들고 "
                        "얼굴·관절 구조가 더 안정적인 사람 영역만 자동 선택합니다. 폭발·충격 섬광은 보존한 뒤 "
                        "업스케일하며 프레임 수와 FPS는 유지됩니다."
                    ),
                ),
                io.Int.Input(
                    "motion_repair_strength",
                    default=30,
                    min=10,
                    max=50,
                    step=5,
                    optional=True,
                    tooltip="국소 모션 복원 혼합 강도입니다. 일반 복원은 30, NVIDIA 액션 영상은 40을 권장합니다.",
                ),
                io.Combo.Input(
                    "memory_profile",
                    options=["Auto", "Quality", "Low VRAM"],
                    default="Auto",
                    optional=True,
                    tooltip=(
                        "Auto는 현재 GPU의 전체/남은 VRAM과 출력 해상도를 확인해 "
                        "기존 Quality 경로 또는 저VRAM 경로를 자동 선택합니다. "
                        "Quality는 기존 최고품질 복원 체인을 그대로 강제하고, Low VRAM은 "
                        "선택한 배율을 유지하면서 동시 복원 모델과 시간축 버퍼 메모리를 줄입니다."
                    ),
                ),
            ],
            outputs=[
                io.Video.Output("video"),
                io.String.Output("output_path"),
            ],
            is_output_node=False,
        )

    @classmethod
    def execute(
        cls,
        video: Input.Video,
        scale: float,
        upscale_quality: str,
        restore_mode: str,
        quality_target: str,
        color_treatment: str,
        output_quality: int,
        encode_preset: str,
        temporal_mode: str,
        subject_recovery: str,
        enabled: bool = True,
        hdr_enabled: bool = False,
        output_mode: str | None = None,
        motion_repair: str = "Auto",
        motion_repair_strength: int = 30,
        memory_profile: str = "Auto",
    ) -> io.NodeOutput:
        if not enabled:
            return io.NodeOutput(video, "")

        output_mode = _resolve_output_mode(output_mode, hdr_enabled)
        hdr_enabled = output_mode == "HDR"

        if not any(NODE_ROOT.glob("srfptyp_core*.pyd")):
            raise FileNotFoundError(
                "필수 영상 복원 런타임이 없습니다. 설치 상태를 확인하세요."
            )

        ffmpeg = _resolve_ffmpeg()
        input_width, input_height = video.get_dimensions()
        output_width = _snap_even(input_width * scale)
        output_height = _snap_even(input_height * scale)

        temp_root = Path(folder_paths.get_temp_directory()).resolve()
        jobs_root = temp_root / "srfptyp_video_jobs"
        jobs_root.mkdir(parents=True, exist_ok=True)
        job_dir = jobs_root / uuid.uuid4().hex
        job_dir.mkdir()

        output_name = f"srfptyp_{uuid.uuid4().hex[:12]}_{output_width}x{output_height}.mp4"
        output_path = temp_root / output_name
        input_raw = job_dir / "input.rgba"
        output_raw = job_dir / "output.rgba"

        try:
            input_path = _stage_video(video, job_dir)
            if output_mode != "SDR":
                _validate_hdr_source(input_path)
                # Fail before the expensive restoration if this FFmpeg cannot
                # perform a real SDR -> PQ transform. Never silently emit SDR.
                _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                      "-i", "color=white:size=64x64:rate=1", "-frames:v", "1",
                      "-vf", _hdr_filter(False) if hdr_enabled else _sdr10_filter(False), "-f", "null", "-"])
            fps = _video_fps(input_path)
            fps_text = f"{fps.numerator}/{fps.denominator}"
            nvdec_download_format = _nvdec_download_format(input_path)

            try:
                _run([
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-hwaccel", "cuda",
                    "-hwaccel_output_format", "cuda",
                    "-i", str(input_path),
                    "-map", "0:v:0",
                    "-vf", f"hwdownload,format={nvdec_download_format},format=rgba",
                    "-pix_fmt", "rgba",
                    "-f", "rawvideo",
                    "-fps_mode", "passthrough",
                    str(input_raw),
                ])
                print(f"SRFPTyp decode acceleration enabled ({nvdec_download_format})")
            except RuntimeError as gpu_decode_error:
                print(f"NVDEC unavailable; using CPU decode: {gpu_decode_error}")
                _run([
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-i", str(input_path),
                    "-map", "0:v:0",
                    "-pix_fmt", "rgba",
                    "-f", "rawvideo",
                    "-fps_mode", "passthrough",
                    str(input_raw),
                ])

            worker_input_raw = input_raw
            if _uses_nvfruc(motion_repair):
                worker_input_raw = _apply_nvfruc_source_repair(
                    input_raw,
                    job_dir / "input_nvfruc.rgba",
                    input_width,
                    input_height,
                    motion_repair_strength,
                )

            bridge_command = [
                sys.executable,
                "-s",
                "-c",
                (
                    "import sys;root=sys.argv[1];sys.path.insert(0,root);"
                    "from vfx12_worker import main;"
                    "sys.argv=['vfx12_worker']+sys.argv[2:];main()"
                ),
                str(NODE_ROOT),
                "--input", str(worker_input_raw),
                "--output", str(output_raw),
                "--input-width", str(input_width),
                "--input-height", str(input_height),
                "--output-width", str(output_width),
                "--output-height", str(output_height),
                "--upscale-quality", upscale_quality,
                "--restore-mode", restore_mode,
                "--quality-target", quality_target,
                "--color-treatment", color_treatment,
                "--temporal-mode", temporal_mode,
                "--subject-recovery", subject_recovery,
                "--memory-profile", memory_profile,
            ]
            _run(bridge_command, cwd=NODE_ROOT)

            if _uses_nvfruc(motion_repair):
                _apply_post_upscale_human_guard(
                    worker_input_raw,
                    output_raw,
                    input_width,
                    input_height,
                    output_width,
                    output_height,
                )

            nvofa_raw = job_dir / "output_nvofa.rgba"
            if not _uses_nvfruc(motion_repair):
                output_raw = _apply_nvofa_temporal_repair(
                    output_raw,
                    nvofa_raw,
                    output_width,
                    output_height,
                    motion_repair,
                    motion_repair_strength,
                )

            quantizer = _quality_to_quantizer(output_quality)
            try:
                _run([
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-f", "rawvideo",
                    "-pix_fmt", "rgba",
                    "-video_size", f"{output_width}x{output_height}",
                    "-framerate", fps_text,
                    "-i", str(output_raw),
                    "-i", str(input_path),
                    "-map", "0:v:0",
                    "-map", "1:a:0?",
                    *_output_encoding(output_mode, True, encode_preset, quantizer,
                                      (output_width, output_height)),
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    str(output_path),
                ])
                print("SRFPTyp GPU encode completed (HEVC)" if output_mode != "SDR" or
                      max(output_width, output_height) > 4096 else "SRFPTyp GPU encode completed (H.264)")
            except RuntimeError as gpu_encode_error:
                reason = str(gpu_encode_error).splitlines()[0]
                print(f"SRFPTyp GPU encode unavailable; starting CPU encode: {reason}")
                _run([
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-f", "rawvideo",
                    "-pix_fmt", "rgba",
                    "-video_size", f"{output_width}x{output_height}",
                    "-framerate", fps_text,
                    "-i", str(output_raw),
                    "-i", str(input_path),
                    "-map", "0:v:0",
                    "-map", "1:a:0?",
                    *_output_encoding(output_mode, False, encode_preset, quantizer),
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    str(output_path),
                ])
                print("SRFPTyp CPU encode completed")

            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("SRFPTyp 출력 영상이 생성되지 않았습니다.")
            if hdr_enabled:
                _validate_hdr_output(output_path)
                print("SRFPTyp HDR: HEVC Main10 / BT.2020 / PQ verified; SDR reference white 203 nits")
            elif output_mode == "SDR 10bit":
                _validate_sdr10_output(output_path)
                print("SRFPTyp SDR 10bit: HEVC Main10 / Rec.709 verified")
        finally:
            resolved_jobs = jobs_root.resolve()
            resolved_job = job_dir.resolve()
            if resolved_job.parent == resolved_jobs and job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)

        result_video = InputImpl.VideoFromFile(str(output_path))
        preview = ui.PreviewVideo([ui.SavedResult(output_name, "", io.FolderType.temp)])
        return io.NodeOutput(result_video, str(output_path), ui=preview)


class RTXVideoVSRExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [RTXVideoVSRRestore]


async def comfy_entrypoint() -> RTXVideoVSRExtension:
    return RTXVideoVSRExtension()
