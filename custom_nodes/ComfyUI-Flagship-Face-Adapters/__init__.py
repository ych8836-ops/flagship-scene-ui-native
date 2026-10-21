"""Flagship additions over separately installed H3-FaceRefine; no upstream tracker bundled."""
from .auto_nodes import NODE_CLASS_MAPPINGS as _auto, NODE_DISPLAY_NAME_MAPPINGS as _auto_names
from .safe_color_nodes import NODE_CLASS_MAPPINGS as _color, NODE_DISPLAY_NAME_MAPPINGS as _color_names

NODE_CLASS_MAPPINGS = {**_auto, **_color}
NODE_DISPLAY_NAME_MAPPINGS = {**_auto_names, **_color_names}
