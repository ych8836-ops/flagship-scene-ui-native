"""Temporary per-camera-segment video previews for the All-in-One timeline."""

from __future__ import annotations

import os

import folder_paths
from comfy_api.latest import Types


class H3CameraSegmentPreview:
    """Encode one completed camera segment to ComfyUI's temporary directory.

    The browser extension consumes the custom ``h3_camera_preview`` payload and
    places the clip in the matching timeline card.  Nothing is written to the
    normal output gallery, so segment previews do not mix with final renders.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
                "segment_index": ("INT", {"default": 0, "min": 0, "max": 63}),
                "shot": ("STRING", {"default": "camera shot"}),
                "start_seconds": ("FLOAT", {"default": 0.0, "min": 0.0}),
                "end_seconds": ("FLOAT", {"default": 1.0, "min": 0.0}),
            }
        }

    RETURN_TYPES = ()
    FUNCTION = "preview"
    CATEGORY = "MiniMax H3/R2V"
    OUTPUT_NODE = True
    DESCRIPTION = "Creates a temporary MP4 preview for one generated camera segment."

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        # A fresh URL and file are required for every queued render, even when
        # ComfyUI can reuse some upstream tensors from its cache.
        return float("nan")

    def preview(self, video, segment_index, shot, start_seconds, end_seconds):
        index = max(0, min(63, int(segment_index)))
        width, height = video.get_dimensions()
        prefix = f"h3_camera_segments/segment_{index + 1:02d}"
        full_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            prefix, folder_paths.get_temp_directory(), width, height
        )
        file = f"{filename}_{counter:05}_.mp4"
        video.save_to(
            os.path.join(full_folder, file),
            format=Types.VideoContainer("mp4"),
            codec="h264",
            crf=28.0,
        )
        item = {
            "filename": file,
            "subfolder": subfolder,
            "type": "temp",
            "segment_index": index,
            "shot": str(shot),
            "start_seconds": float(start_seconds),
            "end_seconds": float(end_seconds),
        }
        return {"ui": {"h3_camera_preview": [item]}}


NODE_CLASS_MAPPINGS = {"H3CameraSegmentPreview": H3CameraSegmentPreview}
NODE_DISPLAY_NAME_MAPPINGS = {"H3CameraSegmentPreview": "H3 Camera · Segment Preview (temporary)"}
