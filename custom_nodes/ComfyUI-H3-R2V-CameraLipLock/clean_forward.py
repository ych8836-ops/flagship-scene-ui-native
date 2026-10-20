"""Private, reversible H3 forward patch used by the camera lip lock.

The patch is attached to a cloned model only.  It never edits ComfyUI core or
the shared model object.
"""
import ast
import copy
import hashlib
import inspect
import textwrap
import types

import torch


PATCH_KEY = "diffusion_model._forward"
SUPPORTED_AST = {
    "7e6dc2c4faaf6317cfc20d846a251a82e068bcaa28b30e334ebd3e7808a909d3",
    # Reviewed core snapshot: per-row denoise masks, packed-buffer allocation,
    # and block prefetch. Target audio remains clean at t=1; reference audio
    # keeps its native timestep. Video and per-row masks are left intact.
    "574fa101e3c644ff192b7094aacc6cf1eb1e9850e9db14fe9dbd093d04f16bad",
}


def _locked_input(clean, incoming):
    if tuple(clean.shape) != tuple(incoming.shape):
        raise ValueError("Camera Lip Lock: target audio shape changed during sampling.")
    return clean.to(device=incoming.device, dtype=incoming.dtype)


def build_clean_forward(original, clean_audio):
    fn = getattr(original, "__func__", original)
    if getattr(fn, "_h3_camera_clean_audio_lock", False):
        fn = fn._h3_camera_original_forward
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    root = tree.body[0]
    digest = hashlib.sha256(ast.dump(root, include_attributes=False).encode()).hexdigest()
    if digest not in SUPPORTED_AST:
        raise RuntimeError(
            "Camera Lip Lock: the installed H3 forward implementation changed. "
            "Stopped safely; compatibility review is required."
        )
    clean = clean_audio.detach().to(device="cpu", dtype=torch.float32).clone()
    if not torch.isfinite(clean).all():
        raise ValueError("Camera Lip Lock: encoded source audio contains NaN/Inf.")
    count = {"audio": 0, "time": 0, "reference": 0}
    body = []
    for statement in root.body:
        body.append(statement)
        if not isinstance(statement, ast.Assign):
            continue
        target = ast.unparse(statement.targets[0])
        if target == "(video_x, audio_x)":
            body.extend(ast.parse("audio_x = _h3_locked_input(_h3_clean_audio, audio_x)").body)
            count["audio"] += 1
        elif target == "t_a":
            body.extend(ast.parse("_h3_reference_audio_time = t_a\nt_a = 1.0").body)
            count["time"] += 1
        elif target == "seg_t":
            for key, value in zip(statement.value.keys, statement.value.values):
                if isinstance(key, ast.Constant) and key.value == "ref_audio":
                    if ast.unparse(value) != "max(t_a, aud_aug)":
                        raise RuntimeError("Camera Lip Lock: unexpected reference-audio timestep expression.")
                    value.args[0] = ast.Name(id="_h3_reference_audio_time", ctx=ast.Load())
                    count["reference"] += 1
    if count != {"audio": 1, "time": 1, "reference": 1}:
        raise RuntimeError(f"Camera Lip Lock: incompatible H3 patch anchors: {count}")
    root.body = body
    ast.fix_missing_locations(tree)
    namespace = dict(fn.__globals__)
    namespace.update(_h3_clean_audio=clean, _h3_locked_input=_locked_input)
    exec(compile(tree, "<H3CameraExactAudioLock private forward>", "exec"), namespace)
    patched = namespace[root.name]
    patched._h3_camera_clean_audio_lock = True
    patched._h3_camera_original_forward = fn
    return types.MethodType(patched, original.__self__)


def attach_clean_forward(model, clean_audio):
    from comfy.patcher_extension import WrappersMP

    if model.get_wrappers(WrappersMP.DIFFUSION_MODEL, "spectrum_minimax_h3"):
        raise ValueError(
            "Strict Lip Sync requires Spectrum OFF because its forecast path bypasses "
            "the exact source-audio timestep. Sage may remain enabled."
        )
    diffusion = model.get_model_object("diffusion_model")
    if type(diffusion).__name__ != "MiniMaxH3Model":
        raise ValueError("Strict Lip Sync supports MiniMaxH3Model only.")
    original = model.get_model_object(PATCH_KEY)
    if getattr(original, "__self__", None) is not diffusion:
        raise RuntimeError("Camera Lip Lock: unexpected H3 forward owner; refusing a conflicting patch.")
    patched = model.clone()
    patched.add_object_patch(PATCH_KEY, build_clean_forward(original, clean_audio))
    patched.model_options = copy.copy(patched.model_options)
    options = dict(patched.model_options.get("transformer_options", {}))
    options.pop("minimax_h3_lock_audio_clean", None)
    patched.model_options["transformer_options"] = options
    return patched
