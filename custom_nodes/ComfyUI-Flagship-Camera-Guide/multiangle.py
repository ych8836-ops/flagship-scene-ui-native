"""Precise Easy MultiAngle-compatible paths; angles remain numeric throughout."""
import json
import math
import numpy as np

DEFAULT_PATH = {"version": 1, "enabled": True, "interpolation": "smooth", "rotation": "direct", "zoom_mode": "optical",
                "keyframes": [{"t": 0, "rotate": 0, "vertical": 0, "zoom": 5}]}


def number(value, name):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"MultiAngle {name} must be finite")
    return result


def parse_path(raw):
    data = json.loads(raw) if isinstance(raw, str) else raw
    # EASY_MULTI_ANGLE is a list of views with no time axis. Keep its order.
    if isinstance(data, list):
        data = {"keyframes": [{**p, "t": i / max(1, len(data)-1)} for i, p in enumerate(data)]}
    if not isinstance(data, dict):
        raise ValueError("MultiAngle needs a path object or Easy MultiAngle view list")
    frames = data.get("keyframes", [])
    if not isinstance(frames, list) or not frames:
        raise ValueError("MultiAngle needs at least one angle")
    points = []
    for frame in frames:
        p = {key: number(frame.get(key, default), key)
             for key, default in (("t", 0), ("rotate", 0), ("vertical", 0), ("zoom", 5))}
        if not 0 <= p["t"] <= 1:
            raise ValueError("MultiAngle time must be between 0 and 1")
        if not -90 <= p["vertical"] <= 90 or not 0 <= p["zoom"] <= 10:
            raise ValueError("MultiAngle elevation must be -90..90 and zoom 0..10")
        points.append(p)
    points.sort(key=lambda p: p["t"])
    if any(b["t"] <= a["t"] for a, b in zip(points, points[1:])):
        raise ValueError("MultiAngle keyframes must have distinct times")
    interpolation = data.get("interpolation", "smooth")
    rotation = data.get("rotation", "direct")
    if interpolation not in ("linear", "smooth") or rotation not in ("direct", "shortest"):
        raise ValueError("Unsupported MultiAngle interpolation or rotation")
    zoom_mode = data.get("zoom_mode", "optical")
    if zoom_mode not in ("dolly", "optical"):
        raise ValueError("Unsupported MultiAngle zoom mode")
    return {"version": 1, "enabled": data.get("enabled", True) is not False,
            "interpolation": interpolation, "rotation": rotation, "zoom_mode": zoom_mode, "keyframes": points}


def sample_path(path, fractions):
    path = parse_path(path)
    points = path["keyframes"]
    t = np.asarray([p["t"] for p in points])
    values = np.asarray([[p[k] for k in ("rotate", "vertical", "zoom")] for p in points])
    if path["rotation"] == "shortest":
        values[:, 0] = np.rad2deg(np.unwrap(np.deg2rad(values[:, 0])))
    fractions = np.asarray(fractions, dtype=np.float64)
    if len(points) == 1:
        return np.repeat(values, len(fractions), axis=0)
    index = np.clip(np.searchsorted(t, fractions, side="right")-1, 0, len(points)-2)
    f = np.clip((fractions-t[index])/(t[index+1]-t[index]), 0, 1)
    if path["interpolation"] == "smooth":
        f = f*f*(3-2*f)
    return values[index] + (values[index+1]-values[index])*f[:, None]


def radius_scale(zoom):
    # Explicit working-distance convention, not millimeters or optical focal length.
    return 2 ** ((5-number(zoom, "zoom"))/5)


class FlagshipMultiAngle:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"path_json": ("STRING", {"multiline": True, "default": json.dumps(DEFAULT_PATH)}),
                             "frames": ("INT", {"default": 124, "min": 1, "max": 100000}),
                             "fps": ("FLOAT", {"default": 24., "min": .01, "max": 240.})},
                "optional": {"multi_angle": ("EASY_MULTI_ANGLE",)}}
    RETURN_TYPES = ("STRING", "EASY_MULTI_ANGLE", "STRING")
    RETURN_NAMES = ("camera_path_json", "params", "angle_summary")
    FUNCTION = "build"
    CATEGORY = "Flagship/Camera"

    def build(self, path_json, frames=124, fps=24., multi_angle=None):
        path = parse_path(multi_angle if multi_angle is not None else path_json)
        values = sample_path(path, np.linspace(0, 1, frames))
        output = {**path, "frames": frames, "fps": fps,
                  "samples": [{"frame": i, "seconds": i/fps, "rotate": v[0], "vertical": v[1], "zoom": v[2]}
                              for i, v in enumerate(values)]}
        duration = (frames-1)/fps
        summary = "\n".join(f'{p["t"]*duration:.3f}s: azimuth {p["rotate"]:.3f}°, elevation {p["vertical"]:.3f}°, zoom {p["zoom"]:.3f}'
                            for p in path["keyframes"])
        return json.dumps(output, ensure_ascii=False), path["keyframes"], summary
