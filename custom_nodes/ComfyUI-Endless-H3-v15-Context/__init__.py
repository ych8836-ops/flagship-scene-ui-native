"""Isolated upstream Motion Context 0.6.2 for the Endless v1.5 workflow.

Only registration names differ. Existing MiniMaxH3MotionContext nodes,
startup wrappers and their saved workflows are left untouched. No chain
routes or model/layout patches are registered by this compatibility pack.
"""
from .nodes import NODE_CLASS_MAPPINGS as _classes, NODE_DISPLAY_NAME_MAPPINGS as _names

_core = ("MiniMaxH3MotionContext", "MiniMaxH3MotionContextTrim",
         "MiniMaxH3MotionContextSaveLatent", "MiniMaxH3MotionContextLoadLatent")
NODE_CLASS_MAPPINGS = {"EndlessV15" + name: _classes[name] for name in _core}
NODE_DISPLAY_NAME_MAPPINGS = {"EndlessV15" + name: "Endless v1.5 · " + _names[name] for name in _core}
