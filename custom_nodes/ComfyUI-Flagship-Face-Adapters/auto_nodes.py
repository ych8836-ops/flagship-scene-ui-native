"""Automatic no-face guard for the H3 FaceRefine workflow branch."""

from __future__ import annotations

import sys


def _external_helper(name, *args):
    import nodes
    cls = nodes.NODE_CLASS_MAPPINGS.get('H3FaceTrackCrop')
    module = sys.modules.get(cls.__module__) if cls else None
    if module is None or not hasattr(module, name):
        raise RuntimeError('Install the separate ComfyUI-H3-FaceRefine dependency before using Flagship face adapters.')
    return getattr(module, name)(*args)


def _detector_list():
    try:
        return _external_helper('_detector_list')
    except RuntimeError:
        return ['face_yolov8m.pt']


def _load_detector(name):
    return _external_helper('_load_detector', name)


def _to_bgr_u8(frame):
    return _external_helper('_to_bgr_u8', frame)


class H3FacePresence:
    """Report whether the configured detector finds a face in any frame.

    Put this before a lazy switch. When false, ComfyUI can choose the original
    image branch without evaluating the expensive FaceRefine sampler branch.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "detector": (_detector_list(),),
                "confidence": (
                    "FLOAT",
                    {
                        "default": 0.35,
                        "min": 0.05,
                        "max": 0.95,
                        "step": 0.05,
                        "tooltip": "Must match H3FaceTrackCrop for deterministic auto bypass.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("BOOLEAN", "STRING")
    RETURN_NAMES = ("face_found", "report")
    FUNCTION = "detect"
    CATEGORY = "MiniMax H3/Face Refine"
    DESCRIPTION = (
        "Checks the current clip for at least one face. Use face_found with a lazy "
        "switch so no-face clips skip the complete FaceRefine sampling branch."
    )

    def detect(self, images, detector, confidence):
        import comfy.model_management as model_management

        model = _load_detector(detector)
        frame_count = int(images.shape[0])
        for index in range(frame_count):
            model_management.throw_exception_if_processing_interrupted()
            result = model.predict(
                _to_bgr_u8(images[index]), conf=confidence, verbose=False
            )[0]
            if len(result.boxes):
                return (
                    True,
                    f"Face found at frame {index + 1}/{frame_count}; FaceRefine enabled.",
                )
        return (
            False,
            f"No face found in {frame_count} frames; original clip passes through.",
        )


NODE_CLASS_MAPPINGS = {"H3FacePresence": H3FacePresence}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3FacePresence": "H3 Face Presence — Auto Bypass"
}
