"""Standalone MiniMax H3 R2V camera segmentation and source-audio/lip lock.

This node does not replace the H3 sampler. It prepares synchronized reference
frames, synchronized audio, and a per-segment camera/lip-sync prompt for the
stock MiniMaxH3ReferenceToVideo node. The full source audio is also returned
unchanged so the final VideoCombine can mux the original track.
"""

import json
import logging
import math
import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import torch
from aiohttp import web

import folder_paths
from server import PromptServer


LOG = logging.getLogger("h3_r2v_camera_lip_lock")
FPS_DEFAULT = 24.0
H3_LENGTH_MIN = 5
H3_LENGTH_MAX = 3600
ASPECT_RATIOS = ["source", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21",
                 "3:2", "2:3", "4:5", "5:4", "1:2", "2:1", "custom"]
DEFAULT_H3_MODEL = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"


def _camera_source_path(source_video):
    path = str(source_video or "").strip().strip('"')
    return path if not path or os.path.isabs(path) else folder_paths.get_annotated_filepath(path)


def _camera_resolution(source_width, source_height, aspect_ratio="source", megapixels=0.5,
                       custom_width=960, custom_height=544):
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"Unknown aspect ratio: {aspect_ratio}")
    def snap(value):
        return max(32, int(math.floor(float(value)/32 + 0.5))*32)
    if aspect_ratio == "custom":
        if not all(math.isfinite(float(v)) and 32 <= float(v) <= 4096 for v in (custom_width, custom_height)):
            raise ValueError("Custom dimensions must be between 32 and 4096.")
        width, height = snap(custom_width), snap(custom_height)
    else:
        if not math.isfinite(float(megapixels)) or not 0.1 <= float(megapixels) <= 4.0:
            raise ValueError("Megapixels must be between 0.1 and 4.0.")
        if source_width <= 0 or source_height <= 0:
            raise ValueError("Source dimensions must be positive.")
        if aspect_ratio == "source":
            ratio = source_width/source_height
        else:
            a,b = map(int, aspect_ratio.split(":"))
            ratio = a/b
        width = snap(math.sqrt(float(megapixels)*1_000_000*ratio))
        height = snap(math.sqrt(float(megapixels)*1_000_000/ratio))
    if max(width, height) > 4096:
        raise ValueError("Calculated dimension exceeds 4096; reduce megapixels or use a narrower aspect ratio.")
    return width, height

CAMERA_SHOTS = [
    "wide shot",
    "medium shot",
    "medium close-up",
    "close-up",
    "extreme close-up",
    "low angle",
    "high angle",
    "over-the-shoulder",
]
CAMERA_MOVEMENTS = [
    "static camera",
    "slow pan left",
    "slow pan right",
    "slow tilt up",
    "slow tilt down",
    "slow dolly in",
    "slow dolly out",
    "smooth tracking shot",
    "smooth orbit left",
    "smooth orbit right",
    "subtle handheld",
]
CAMERA_SPEEDS = ["very slow", "slow", "moderate", "fast"]

DEFAULT_PLAN = json.dumps(
    {
        "segments": [
            {"start_frame": 0, "end_frame": 124, "shot": "wide shot", "movement": "slow dolly in", "speed": "slow", "strength": 0.35},
            {"start_frame": 124, "end_frame": 248, "shot": "medium shot", "movement": "smooth tracking shot", "speed": "moderate", "strength": 0.45},
            {"start_frame": 248, "end_frame": 372, "shot": "close-up", "movement": "static camera", "speed": "very slow", "strength": 0.20},
        ]
    },
    ensure_ascii=False,
    indent=2,
)


async def upload_source_video(request):
    """Store a UI-selected source video in ComfyUI's input directory.

    The frontend uses this small route only for the source-video convenience
    panel. Actual decoding remains delegated to the connected VHS loader, so
    the node keeps the normal ComfyUI IMAGE/AUDIO graph contract.
    """
    try:
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            return web.json_response({"ok": False, "error": "no file field"}, status=400)
        filename = Path(field.filename or "").name
        allowed = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".m4v"}
        if not filename or Path(filename).suffix.lower() not in allowed:
            return web.json_response({"ok": False, "error": "unsupported video format"}, status=400)
        input_dir = folder_paths.get_input_directory()
        os.makedirs(input_dir, exist_ok=True)
        # Unique names prevent same-name uploads from reusing Comfy's old cache.
        filename = f"h3camera_{uuid.uuid4().hex[:12]}_{filename}"
        dest = os.path.join(input_dir, filename)
        with open(dest, "xb") as output:
            while True:
                chunk = await field.read_chunk(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        return web.json_response({"ok": True, "filename": filename, "path": dest})
    except Exception as exc:
        LOG.exception("Source video upload failed")
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def runtime_workflow_template(_request):
    """Return the maintained internal graph used by the one-node canvas UI."""
    path = Path(__file__).resolve().parent / "workflows" / "H3_R2V_Camera_SourceEdit_8Step_API.json"
    if not path.is_file():
        return web.json_response({"error": "camera runtime workflow template is missing"}, status=500)
    try:
        return web.json_response(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        LOG.exception("Camera runtime workflow template failed to load")
        return web.json_response({"error": str(exc)}, status=500)


# ComfyUI normally has an active PromptServer while custom nodes are loaded.
# Keep direct module inspection/import safe as well, which is useful for
# portable installs and diagnostics before the server has finished starting.
if getattr(PromptServer, "instance", None) is not None:
    PromptServer.instance.routes.post("/h3r2v_camera_lip_lock/upload")(upload_source_video)
    PromptServer.instance.routes.get("/h3r2v_camera_lip_lock/runtime_template")(runtime_workflow_template)


def _fps_from_info(video_info: Any, fallback: float) -> float:
    if isinstance(video_info, dict):
        for key in ("loaded_fps", "fps", "frame_rate", "source_fps"):
            value = video_info.get(key)
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                return value
    return max(1.0, float(fallback))


def _plan_segments(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Camera plan JSON is invalid: {exc.msg} at character {exc.pos}") from exc
    if isinstance(data, list):
        segments = data
    elif isinstance(data, dict):
        segments = data.get("segments", [])
    else:
        raise ValueError("Camera plan must be a JSON object with a 'segments' array.")
    if not isinstance(segments, list):
        raise ValueError("Camera plan 'segments' must be an array.")
    return [item for item in segments if isinstance(item, dict)]


def _frame_range(
    segments: list[dict[str, Any]],
    index: int,
    segment_frames: int,
    fps: float,
    total_frames: int,
) -> tuple[int, int, dict[str, Any]]:
    item = segments[index] if index < len(segments) else {}
    if "start_seconds" in item:
        start = int(round(float(item["start_seconds"]) * fps))
    elif "start_frame" in item:
        start = int(item["start_frame"])
    elif "start" in item:
        start = int(round(float(item["start"]) * fps))
    else:
        start = index * segment_frames
    if "end_seconds" in item:
        end = int(round(float(item["end_seconds"]) * fps))
    elif "end_frame" in item:
        end = int(item["end_frame"])
    elif "duration_frames" in item:
        end = start + int(item["duration_frames"])
    else:
        duration = float(item.get("duration_seconds", item.get("duration", segment_frames / fps)))
        end = start + int(round(duration * fps))

    if start < 0 or start >= total_frames or end <= start:
        raise ValueError(f"Segment {index + 1} is outside the source video.")
    end = min(end, total_frames)
    if end-start < H3_LENGTH_MIN:
        raise ValueError(f"Segment {index+1} needs at least 5 source frames; adjust its time range.")
    # Keep the requested exact timeline. The editing encoder pads to H3's grid;
    # its decoder output is trimmed back, so intermediate tails are never lost.
    return start, end, item


def _normalize_audio(audio: Any) -> dict[str, Any]:
    """Accept standard AUDIO dictionaries and VHS's deferred LazyAudioMap.

    Materialize the mapping once; retain the original tensor and sample rate.
    This does not resample, normalize loudness, or copy the full waveform.
    """
    if not isinstance(audio, Mapping):
        raise ValueError("Source audio is missing. Select a source video with an audio track.")
    try:
        waveform = audio["waveform"]
        sample_rate = audio["sample_rate"]
    except KeyError as exc:
        raise ValueError(f"Source AUDIO is missing {exc.args[0]}. Check the source audio track.") from exc
    if not torch.is_tensor(waveform):
        raise ValueError("Source audio waveform is not a tensor.")
    if waveform.ndim != 3 or waveform.numel() == 0:
        raise ValueError("Source audio must contain a non-empty [batch, channels, samples] waveform.")
    try:
        valid_rate = math.isfinite(float(sample_rate)) and float(sample_rate) > 0
    except (TypeError, ValueError, OverflowError):
        valid_rate = False
    if not valid_rate:
        raise ValueError("Source audio sample_rate must be a positive finite number.")
    return audio if isinstance(audio, dict) else dict(audio)


def _slice_audio(audio: Mapping[str, Any], start_frame: int, end_frame: int, fps: float) -> dict[str, Any]:
    audio = _normalize_audio(audio)
    waveform = audio["waveform"]
    sample_rate = int(audio["sample_rate"])
    start_sample = max(0, int(round(start_frame / fps * sample_rate)))
    end_sample = max(start_sample + 1, int(round(end_frame / fps * sample_rate)))
    total_samples = int(waveform.shape[-1])
    if start_sample >= total_samples:
        raise ValueError("Source audio does not cover this video segment.")
    missing = max(0, end_sample-total_samples)
    if missing > max(2, int(sample_rate/fps)):
        raise ValueError("Source audio ends before this camera segment; select a covered time range.")
    sliced = dict(audio)
    sliced["waveform"] = waveform[..., start_sample:min(end_sample,total_samples)].clone()
    if missing:
        sliced["waveform"] = torch.nn.functional.pad(sliced["waveform"], (0, missing))
    return sliced


def _camera_prompt(item: dict[str, Any], default_shot: str, default_movement: str, default_speed: str, default_strength: float) -> tuple[str, dict[str, Any]]:
    shot = str(item.get("shot", default_shot))
    movement = str(item.get("movement", default_movement))
    speed = str(item.get("speed", default_speed))
    strength = max(0.0, min(1.0, float(item.get("strength", default_strength))))
    camera = {"shot": shot, "movement": movement, "speed": speed, "strength": round(strength, 3)}
    for name in ("center_x", "center_y"):
        if name in item:
            camera[name] = float(item[name])
    return (
        f"Camera instruction for this segment: {shot}; {movement}; {speed} speed; "
        f"controlled movement strength {strength:.2f}. Keep one continuous shot and avoid cuts, "
        "lens warping, sudden zooms, or unmotivated reframing.",
        camera,
    )


class H3R2VCameraLipLock:
    """Split a source video into synchronized R2V reference segments."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Full source video frames from VHS Load Video."}),
                "audio": ("AUDIO", {"tooltip": "The original source soundtrack. It is returned unchanged for final muxing."}),
                "segment_index": ("INT", {"default": 0, "min": 0, "max": 63, "step": 1}),
                "segment_frames": ("INT", {"default": 124, "min": 5, "max": H3_LENGTH_MAX, "step": 17}),
                "camera_plan_json": ("STRING", {"default": DEFAULT_PLAN, "multiline": True}),
                "camera_shot": (CAMERA_SHOTS, {"default": "medium shot"}),
                "camera_movement": (CAMERA_MOVEMENTS, {"default": "static camera"}),
                "camera_speed": (CAMERA_SPEEDS, {"default": "slow"}),
                "camera_strength": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.05}),
                "lip_lock_strength": ("FLOAT", {"default": 0.98, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Legacy prompt preference, NOT a measured or enforced lip-sync lock."}),
                "source_fps": ("FLOAT", {"default": FPS_DEFAULT, "min": 1.0, "max": 120.0, "step": 0.01}),
            },
            "optional": {
                "video_info": ("VHS_VIDEOINFO",),
                "camera_plan": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "AUDIO", "STRING", "STRING", "INT", "INT", "VHS_VIDEOINFO")
    RETURN_NAMES = ("segment_frames", "segment_audio", "source_audio", "segment_prompt", "camera_plan", "start_frame", "end_frame", "segment_video_info")
    FUNCTION = "prepare"
    CATEGORY = "MiniMax H3/R2V"

    def prepare(
        self,
        images,
        audio,
        segment_index,
        segment_frames,
        camera_plan_json,
        camera_shot,
        camera_movement,
        camera_speed,
        camera_strength,
        lip_lock_strength,
        source_fps,
        video_info=None,
        camera_plan=None,
    ):
        if not torch.is_tensor(images) or images.ndim < 4:
            raise ValueError("H3 R2V Camera + Lip Lock expects IMAGE frames shaped [frames, height, width, channels].")
        total_frames = int(images.shape[0])
        if total_frames < H3_LENGTH_MIN:
            raise ValueError("The source video must contain at least 5 frames.")

        fps = _fps_from_info(video_info, source_fps)
        plan_segments = _plan_segments(camera_plan if camera_plan else camera_plan_json)
        index = max(0, int(segment_index))
        start, end, item = _frame_range(plan_segments, index, int(segment_frames), fps, total_frames)
        segment = images[start:end].contiguous()
        audio = _normalize_audio(audio)
        segment_audio = _slice_audio(audio, start, end, fps)
        prompt_camera, camera = _camera_prompt(item, camera_shot, camera_movement, camera_speed, camera_strength)
        lip_strength = max(0.0, min(1.0, float(lip_lock_strength)))
        duration = (end - start) / fps

        prompt = (
            "subject_definitions:\n"
            "<Video 1> is the source segment being directly edited, defining its visible people, "
            "environment, actions, expressions, timing, and lighting.\n"
            "<Audio 1> is the enabled synchronized soundtrack from this exact source segment.\n\n"
            "summary:\n[video editing + audio reuse] The target video is an edited version of <Video 1>. "
            "Change only the requested camera framing and movement; retain the source performance and scene.\n\n"
            "retention_analysis:\n"
            "<Video 1>: partially_preserved - preserve the same cast, identities, wardrobe, location, "
            "action order, mouth motion, timing, lighting and colors; modify only camera viewpoint and framing.\n"
            "<Audio 1>: fully_copy - the source segment's waveform is the final soundtrack.\n\n"
            "detailed_description:\n"
            "Keep the photographic style, lighting and palette already present in <Video 1>.\n"
            f"[Shot 1] Over local time 0.000-{duration:.3f}s, retain the people and objects already "
            "visible in the source at each corresponding time, with the same physical actions, "
            "gaze and expression changes. Maintain their scene relationships and performance speed. "
            f"{prompt_camera} "
            "The visible speaker, if present, follows the existing mouth-opening, jaw and articulation "
            "sequence of <Video 1>, synchronized to <Audio 1>. Keep pauses and silent intervals at their "
            "original times. Reuse the recorded words or singing without rewriting or inventing speech. "
            "Keep the same scene throughout; the camera change is not a new narrative event.\n\n"
            "overall_soundscape:\nCopy the existing dialogue, ambience and physical sounds from <Audio 1>, "
            "with their original timing and mix.\n\n"
            "non_diegetic_music:\nRetain only the music already present in <Audio 1>, if any; add no new score."
        )

        plan = {
            "segment_index": index,
            "fps": fps,
            "start_frame": start,
            "end_frame": end,
            "frame_count": end - start,
            "duration_seconds": round(duration, 6),
            "camera": camera,
            "lip_lock_strength": round(lip_strength, 3),
            "reference_labels": {"audio": "<Audio 1>", "video": "<Video 1>"},
            "audio_policy": "source_audio_passthrough",
            "final_audio_connection": "Connect source_audio to the final VHS_VideoCombine/CreateVideo audio input.",
        }
        info = dict(video_info) if isinstance(video_info, dict) else {}
        info.update({
            "fps": fps,
            "frame_rate": fps,
            "source_fps": fps,
            "frame_count": end - start,
            "source_frame_count": end - start,
            "duration": duration,
            "source_duration": duration,
            "start_frame": start,
            "end_frame": end,
        })
        LOG.info("R2V Camera + Lip Lock segment %d: frames %d-%d, %.3fs, camera=%s %s, audio=source passthrough", index + 1, start, end - 1, duration, camera["shot"], camera["movement"])
        return (segment, segment_audio, audio, prompt, json.dumps(plan, ensure_ascii=False, indent=2), start, end, info)


class H3R2VCameraTimeline:
    """All-in-One-style timeline planner for the hidden R2V branches.

    The node only owns the editable plan. It passes the source media through
    unchanged and emits one STRING plan that can be wired to every hidden
    H3R2VCameraLipLock branch.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_video": ("STRING", {"default": "", "multiline": False, "placeholder": "Upload a source video in the UI"}),
                "camera_plan_json": ("STRING", {"default": DEFAULT_PLAN, "multiline": True}),
                "source_fps": ("FLOAT", {"default": FPS_DEFAULT, "min": 1.0, "max": 120.0, "step": 0.01}),
            },
            "optional": {
                "edit_strength": ("FLOAT", {"default": 0.95, "min": 0.70, "max": 1.0, "step": 0.05, "tooltip": "Camera regeneration strength. 0.95 is recommended; lower values preserve more of the original view but weaken camera changes."}),
                "expected_segments": ("INT", {"default": 0, "min": 0, "max": 64}),
                "lora_name": (["None"] + folder_paths.get_filename_list("loras"),),
                "lora_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
                "sage_enabled": ("BOOLEAN", {"default": True}),
                "spectrum_enabled": ("BOOLEAN", {"default": False}),
                "steps": ("INT", {"default": 8, "min": 1, "max": 100}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "source"}),
                "megapixels": ("FLOAT", {"default": 0.5, "min": 0.1, "max": 4.0, "step": 0.05}),
                "custom_width": ("INT", {"default": 960, "min": 32, "max": 4096, "step": 32}),
                "custom_height": ("INT", {"default": 544, "min": 32, "max": 4096, "step": 32}),
                "lip_sync_strict": ("BOOLEAN", {"default": True, "tooltip": "Pins exact source audio into H3 while sampling. Spectrum is automatically disabled; Sage remains available."}),
                "segment_preview": ("BOOLEAN", {"default": True, "tooltip": "Encode each completed camera segment to a temporary MP4 and show it in the All-in-One timeline."}),
                # Keep this last so older saved workflows retain every existing
                # widget value at the same index when the new selector appears.
                "unet_name": (folder_paths.get_filename_list("diffusion_models"), {"default": DEFAULT_H3_MODEL}),
                "upscale_enabled": ("BOOLEAN", {"default": False, "tooltip": "Insert SRFPTyp video restoration between final video assembly and Save Video."}),
                "upscale_scale": ("FLOAT", {"default": 2.0, "min": 1.0, "max": 4.0, "step": 0.05}),
                "upscale_quality": (["Ultra", "High", "High-Bitrate Ultra", "High-Bitrate High"], {"default": "Ultra"}),
                "upscale_restore_mode": (["Auto Scan (Clean/Chain90)", "Deblur Low", "Deblur Medium", "Denoise Low", "Denoise Low + Deblur Low", "Chain Late Recovery 90"], {"default": "Auto Scan (Clean/Chain90)"}),
                "upscale_quality_target": (["100% Restore", "105% Master", "110% Master"], {"default": "110% Master"}),
                "upscale_color_treatment": (["Off", "Auto Natural", "Auto Bright"], {"default": "Auto Natural"}),
                "upscale_output_quality": ("INT", {"default": 95, "min": 80, "max": 99, "step": 1}),
                "upscale_encode_preset": (["medium", "slow", "slower"], {"default": "slow"}),
                "upscale_temporal_mode": (["Auto Temporal", "Face Lock", "Action Stable", "Off"], {"default": "Auto Temporal"}),
                "upscale_subject_recovery": (["Auto", "Full Shot Strong", "Off"], {"default": "Auto"}),
                "upscale_output_mode": (["SDR", "SDR 10bit", "HDR"], {"default": "SDR"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "STRING", "VHS_VIDEOINFO", "FLOAT", "FLOAT", "INT", "INT", "H3_CAMERA_SETTINGS", "INT")
    RETURN_NAMES = ("images", "audio", "camera_plan", "video_info", "fps", "edit_strength", "width", "height", "model_settings", "steps")
    FUNCTION = "build_plan"
    CATEGORY = "MiniMax H3/R2V"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, source_video, **kwargs):
        try:
            stat = os.stat(_camera_source_path(source_video))
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return float("nan")

    def build_plan(self, source_video, camera_plan_json, source_fps=FPS_DEFAULT, edit_strength=0.95, expected_segments=0,
                   lora_name="None", lora_strength=1.0, sage_enabled=True, spectrum_enabled=False, steps=8,
                   aspect_ratio="source", megapixels=0.5, custom_width=960, custom_height=544,
                   lip_sync_strict=True, segment_preview=True, unet_name=DEFAULT_H3_MODEL,
                   upscale_enabled=False, upscale_scale=2.0, upscale_quality="Ultra",
                   upscale_restore_mode="Auto Scan (Clean/Chain90)", upscale_quality_target="110% Master",
                   upscale_color_treatment="Auto Natural", upscale_output_quality=95,
                   upscale_encode_preset="slow", upscale_temporal_mode="Auto Temporal",
                   upscale_subject_recovery="Auto", upscale_output_mode="SDR"):
        source_video = _camera_source_path(source_video)
        if not source_video or not os.path.isfile(source_video):
            raise ValueError("Upload a source video in H3 R2V Camera Timeline before generating.")
        # The timeline node is intentionally the single source of truth. It
        # loads the uploaded file internally so users never have to connect a
        # second video/image/audio source into this node.
        import nodes as comfy_nodes
        loader_class = comfy_nodes.NODE_CLASS_MAPPINGS.get("VHS_LoadVideoPath")
        if loader_class is None:
            raise RuntimeError("Video Helper Suite VHS_LoadVideoPath is required for the timeline source loader.")
        loaded = loader_class().load_video(
            video=source_video.strip().strip('"'), force_rate=24, custom_width=0,
            custom_height=0, frame_load_cap=0, skip_first_frames=0,
            select_every_nth=1, format="None",
        )
        images, _frame_count, audio, video_info = loaded
        if not torch.is_tensor(images) or images.ndim < 4:
            raise ValueError("The uploaded source video did not produce IMAGE frames.")
        audio = _normalize_audio(audio)
        segments = _plan_segments(camera_plan_json)
        if not segments:
            segments = _plan_segments(DEFAULT_PLAN)
        if expected_segments and len(segments) != expected_segments:
            raise ValueError(f"This workflow has {expected_segments} generation branches, but the timeline has {len(segments)} segments. Load the matching corrected workflow.")
        for index in range(len(segments)):
            start, end, _ = _frame_range(segments, index, 124, 24, len(images))
            if end-start > 360:
                raise ValueError(f"Segment {index+1} exceeds 15 seconds; split its range.")
        payload = json.dumps({"segments": segments}, ensure_ascii=False, indent=2)
        info = video_info if isinstance(video_info, dict) else {}
        actual_fps = float(info.get("loaded_fps") or info.get("source_fps") or source_fps or FPS_DEFAULT)
        h, w = images.shape[1:3]
        width, height = _camera_resolution(w, h, aspect_ratio, megapixels, custom_width, custom_height)
        LOG.info("Camera resolution: %s %.2f MP -> %dx%d (%.3f actual MP)", aspect_ratio, megapixels, width, height, width*height/1_000_000)
        settings = dict(unet_name=unet_name, lora_name=lora_name, lora_strength=float(lora_strength),
                        sage_enabled=bool(sage_enabled),
                        spectrum_enabled=bool(spectrum_enabled) and not bool(lip_sync_strict),
                        upscale_enabled=bool(upscale_enabled), upscale_scale=float(upscale_scale),
                        upscale_quality=upscale_quality, upscale_restore_mode=upscale_restore_mode,
                        upscale_quality_target=upscale_quality_target,
                        upscale_color_treatment=upscale_color_treatment,
                        upscale_output_quality=int(upscale_output_quality),
                        upscale_encode_preset=upscale_encode_preset,
                        upscale_temporal_mode=upscale_temporal_mode,
                        upscale_subject_recovery=upscale_subject_recovery,
                        upscale_output_mode=upscale_output_mode)
        return (images, audio, payload, info, actual_fps, float(edit_strength), width, height, settings, int(steps))


NODE_CLASS_MAPPINGS = {
    "H3R2VCameraTimeline": H3R2VCameraTimeline,
    "H3R2VCameraLipLock": H3R2VCameraLipLock,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3R2VCameraTimeline": "H3 R2V Camera Timeline (All-in-One UI)",
    "H3R2VCameraLipLock": "H3 R2V Camera + Lip Lock (internal)",
}
