"""Isolated upstream Motion Context 0.6.2 for the Endless v1.5 workflow.

Only registration names differ. Existing MiniMaxH3MotionContext nodes,
startup wrappers and their saved workflows are left untouched. No chain
routes or model/layout patches are registered by this compatibility pack.
"""
import importlib.util
from pathlib import Path
import sys
import types

# The implementation is installed separately from its attributed upstream.
# Load nodes/layout only, matching the original isolated adapter behavior.
_source = Path(__file__).resolve().parents[2] / 'flagship_dependencies/motion_context'
if not (_source / 'nodes.py').is_file():
    raise ImportError('Install the external Motion Context dependency with tools/install_external_nodes.py --features core. Its source is not bundled with Flagship.')
_package = '_flagship_external_motion_context'
if _package not in sys.modules:
    _module = types.ModuleType(_package)
    _module.__path__ = [str(_source)]
    _module.__package__ = _package
    sys.modules[_package] = _module
_name = _package + '.nodes'
if _name not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_name, _source / 'nodes.py')
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    try:
        _spec.loader.exec_module(_module)
    except Exception:
        sys.modules.pop(_name, None)
        raise
_classes = sys.modules[_name].NODE_CLASS_MAPPINGS
_names = sys.modules[_name].NODE_DISPLAY_NAME_MAPPINGS

_core = ("MiniMaxH3MotionContext", "MiniMaxH3MotionContextTrim",
         "MiniMaxH3MotionContextSaveLatent", "MiniMaxH3MotionContextLoadLatent")
NODE_CLASS_MAPPINGS = {"EndlessV15" + name: _classes[name] for name in _core}
NODE_DISPLAY_NAME_MAPPINGS = {"EndlessV15" + name: "Endless v1.5 · " + _names[name] for name in _core}
