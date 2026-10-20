"""Source-initialized H3 video edit conditioning. No new models/dependencies."""
import logging
import torch

LOG = logging.getLogger("h3_camera_source_edit")


def _check_lora_set_shapes(model, name):
    patches = getattr(model, "patches", {})
    if not patches:
        return
    state = model.model_state_dict()
    for key, entries in patches.items():
        weight = state.get(key)
        if weight is None:
            continue
        for entry in entries:
            patch = entry[1]
            if entry[3] is not None or not isinstance(patch, tuple) or len(patch) != 2 or patch[0] != "set":
                continue
            replacement = patch[1][0]
            if tuple(weight.shape) != tuple(replacement.shape):
                raise ValueError(f"LoRA incompatible with this base model: {name}; {key}: model {tuple(weight.shape)}, "
                                 f"LoRA {tuple(replacement.shape)}. Select a compatible LoRA/base model pair. "
                                 "Changing resolution, steps or Sage will not repair this weight shape mismatch.")


class H3CameraReferenceEdit:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip": ("CLIP",), "vae": ("VAE",), "audio_vae": ("VAE",),
            "images": ("IMAGE",), "audio": ("AUDIO",),
            "prompt": ("STRING", {"forceInput": True}),
            "width": ("INT", {"default": 960, "min": 32, "max": 4096, "step": 32}),
            "height": ("INT", {"default": 544, "min": 32, "max": 4096, "step": 32}),
        }}

    RETURN_TYPES = ("CONDITIONING", "LATENT")
    RETURN_NAMES = ("source_reference_conditioning", "source_av_latent")
    FUNCTION = "encode"
    CATEGORY = "MiniMax H3/R2V"

    def encode(self, clip, vae, audio_vae, images, audio, prompt, width, height):
        from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo, align_frame_count, _resize
        from comfy.nested_tensor import NestedTensor
        from .nodes import _normalize_audio

        audio = _normalize_audio(audio)
        if not torch.is_tensor(images) or images.ndim != 4 or len(images) < 5:
            raise ValueError("Camera edit needs at least 5 source frames.")
        if width % 32 or height % 32:
            raise ValueError("Camera edit width and height must be multiples of 32.")
        count = len(images)
        padded_count = align_frame_count(count)
        if padded_count > 362:
            raise ValueError("Split camera segments into at most 15 seconds (360 frames at 24 fps).")
        # Preserve proportions rather than stretching people to the old 960x544
        # canvas. The paired workflow provides source-aspect dimensions.
        # A deliberate aspect-ratio change crops centrally instead of stretching faces.
        frames = _resize(images, width, height, "center")
        if padded_count > count:
            frames = torch.cat((frames, frames[-1:].expand(padded_count-count, -1, -1, -1)), dim=0)
        sr = int(audio["sample_rate"])
        needed = round(padded_count / 24 * sr)
        wave = audio["waveform"]
        if wave.shape[-1] < needed:
            wave = torch.nn.functional.pad(wave, (0, needed-wave.shape[-1]))
        else:
            wave = wave[..., :needed]
        reference_audio = {"waveform": wave, "sample_rate": sr}

        # Typed call avoids silent loss of legacy flat ref_video_0 input names.
        encoded = MiniMaxH3ReferenceToVideo.execute(
            clip=clip, vae=vae, audio_vae=audio_vae, prompt=prompt,
            width=width, height=height, length=padded_count, ref_image_size="match",
            ref_videos={"ref_video_0": frames},
            ref_video_audios={"ref_video_audio_0": reference_audio},
        )
        conditioning, empty = encoded[0], encoded[1]
        blocks = next((meta.get("minimax_refs") for _, meta in conditioning if meta.get("minimax_refs")), [])
        block = next((b for b in blocks if b.get("kind") == "video_audio"), None)
        if block is None or block.get("audio_latent") is None:
            raise RuntimeError("Source video/audio conditioning was NOT attached; generation stopped to prevent an unrelated video.")
        expected_video, expected_audio = empty["samples"].unbind()
        video_z, audio_z = block["latent"], block["audio_latent"]
        if video_z.shape != expected_video.shape:
            # Native reference encoding caps reference canvas area (~1 MP).
            # Larger requested output needs its own source initialization encode;
            # keep the capped reference for conditioning without changing core code.
            video_z = vae.encode(frames)
            if video_z.shape != expected_video.shape:
                raise ValueError(f"Source video latent shape {tuple(video_z.shape)} does not match {tuple(expected_video.shape)}.")
        if audio_z.shape[:-1] != expected_audio.shape[:-1]:
            raise ValueError("Source audio VAE is incompatible with the H3 audio latent.")
        # Audio VAE frame rounding may differ by one or two latent ticks.
        delta = expected_audio.shape[-1] - audio_z.shape[-1]
        if abs(delta) > 2:
            raise ValueError(f"Source audio timing mismatch ({delta} latent ticks); refusing unsynchronized sampling.")
        if delta > 0:
            audio_z = torch.nn.functional.pad(audio_z, (0, delta))
        elif delta < 0:
            audio_z = audio_z[..., :expected_audio.shape[-1]]
        source = {"samples": NestedTensor((video_z, audio_z))}
        # Initialize from the encoded source, not the zeros returned by R2V.
        # The original waveform is muxed later; no generated audio is used.
        LOG.info("Camera edit: verified video+audio reference, SOURCE latent %s, %d -> %d padded frames", tuple(video_z.shape), count, padded_count)
        return conditioning, source


class H3CameraTrimClip:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "source_frames": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "trim"
    CATEGORY = "MiniMax H3/R2V"

    def trim(self, images, source_frames):
        generated_count = len(images)
        target_count = len(source_frames)
        if generated_count >= target_count:
            return (images[:target_count],)
        deficit = target_count - generated_count
        # H3's AV latent alignment can decode up to four frames short even when
        # the requested source/audio duration is valid.  For this small codec
        # rounding gap, distribute the missing time across the clip instead of
        # freezing the last frame or shortening the unchanged source audio.
        if generated_count < 2 or deficit > 4 or deficit / target_count > 0.10:
            raise ValueError(
                f"Generated camera clip is too short ({generated_count}/{target_count} frames); "
                "the difference is too large for safe lip-sync retiming."
            )
        positions = torch.linspace(0, generated_count - 1, target_count, device=images.device)
        lower = positions.floor().long()
        upper = positions.ceil().long().clamp_max(generated_count - 1)
        weight = (positions - lower).reshape((target_count,) + (1,) * (images.ndim - 1))
        retimed = torch.lerp(images.index_select(0, lower), images.index_select(0, upper), weight)
        LOG.warning(
            "Camera clip AV alignment: retimed %d decoded frames to %d source frames (small H3 rounding gap).",
            generated_count, target_count,
        )
        return (retimed,)


class H3CameraAudioJoin:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio1": ("AUDIO",), "audio2": ("AUDIO",)}}
    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "join"
    CATEGORY = "MiniMax H3/R2V"

    def join(self, audio1, audio2):
        from .nodes import _normalize_audio
        a, b = _normalize_audio(audio1), _normalize_audio(audio2)
        if a["sample_rate"] != b["sample_rate"] or a["waveform"].shape[:-1] != b["waveform"].shape[:-1]:
            raise ValueError("Camera segment audio sample rate/channel layout differs.")
        return ({"waveform": torch.cat((a["waveform"], b["waveform"]), dim=-1), "sample_rate": a["sample_rate"]},)


class H3CameraModelOptions:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "settings": ("H3_CAMERA_SETTINGS",)}}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "MiniMax H3/R2V"

    def apply(self, model, settings):
        import nodes as comfy_nodes
        import folder_paths
        name = settings.get("lora_name", "None")
        if name != "None" and settings.get("lora_strength", 1.0) != 0:
            if name not in folder_paths.get_filename_list("loras"):
                raise ValueError(f"Selected camera LoRA is not installed: {name}")
            model = comfy_nodes.LoraLoaderModelOnly().load_lora_model_only(
                model, name, float(settings.get("lora_strength", 1.0)))[0]
            _check_lora_set_shapes(model, name)
        if settings.get("spectrum_enabled", False):
            cls = comfy_nodes.NODE_CLASS_MAPPINGS.get("SpectrumApplyMiniMaxH3")
            if cls is None:
                raise RuntimeError("Spectrum is enabled but SpectrumApplyMiniMaxH3 is not installed/loaded.")
            kwargs = {"model": model}
            for key, spec in cls.INPUT_TYPES()["required"].items():
                if key == "model":
                    continue
                if len(spec) > 1 and "default" in spec[1]:
                    kwargs[key] = spec[1]["default"]
                elif isinstance(spec[0], list) and spec[0]:
                    kwargs[key] = spec[0][0]
                else:
                    raise RuntimeError(f"Spectrum input {key} requires explicit configuration.")
            kwargs.update(enabled=True, blend_weight=0.35)
            model = getattr(cls(), cls.FUNCTION)(**kwargs)[0]
        if settings.get("sage_enabled", True):
            cls = comfy_nodes.NODE_CLASS_MAPPINGS.get("MiniMaxH3MemoryEfficientSageAttentionPatch")
            if cls is None:
                raise RuntimeError("Sage is enabled but the KJNodes H3 memory-efficient Sage patch is not loaded.")
            model = cls.execute(model=model)[0]
        LOG.info("Camera model options: LoRA=%s strength=%s Sage=%s Spectrum=%s", name,
                 settings.get("lora_strength", 1.0), settings.get("sage_enabled", True), settings.get("spectrum_enabled", False))
        return (model,)


class H3CameraReferenceBalance:
    """Keep semantic video tokens and dense audio, but release the source camera.

    MiniMaxH3ReferenceToVideo has already encoded the 2 fps source frames into
    the Qwen context before this node runs.  The separate dense video latent is
    what most strongly copies the source viewpoint.  Converting a paired
    video+audio latent block to an audio-only block preserves the source audio
    inside the DiT while leaving the target video latent empty and free to
    follow a new camera instruction.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"conditioning": ("CONDITIONING",)}}

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("balanced_conditioning",)
    FUNCTION = "balance"
    CATEGORY = "MiniMax H3/R2V"

    def balance(self, conditioning):
        balanced = []
        paired_audio = 0
        removed_video = 0
        for tensor, values in conditioning:
            copied = values.copy()
            refs = copied.get("minimax_refs")
            if refs is not None:
                out_refs = []
                for block in refs:
                    kind = block.get("kind")
                    if kind == "video_audio" and block.get("audio_latent") is not None:
                        out_refs.append({
                            "kind": "audio",
                            "ref_audio_t": block.get("ref_audio_t", block["audio_latent"].shape[-1]),
                            "audio_latent": block["audio_latent"],
                        })
                        paired_audio += 1
                        removed_video += 1
                    elif kind == "video":
                        # Qwen video tokens remain in the already-encoded text
                        # context; only the dense latent camera copy is removed.
                        removed_video += 1
                    else:
                        out_refs.append(block.copy())
                copied["minimax_refs"] = out_refs
                copied["minimax_audio_cond_noise_aug"] = 1.0
            balanced.append([tensor, copied])
        if removed_video == 0:
            raise ValueError("Reference Balance needs at least one MiniMax H3 reference video block.")
        if paired_audio == 0:
            raise ValueError("Reference Balance needs a soundtrack paired with the reference video.")
        LOG.info("Reference Balance: semantic video tokens kept, %d dense video block(s) released, "
                 "%d dense audio guide(s) retained", removed_video, paired_audio)
        return (balanced,)


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (
    H3CameraReferenceEdit,
    H3CameraTrimClip,
    H3CameraAudioJoin,
    H3CameraModelOptions,
    H3CameraReferenceBalance,
)}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3CameraReferenceEdit": "H3 Camera · Source Video Edit",
    "H3CameraTrimClip": "H3 Camera · Keep Exact Duration",
    "H3CameraAudioJoin": "H3 Camera · Join Original Audio",
    "H3CameraModelOptions": "H3 Camera · LoRA / Sage / Spectrum",
    "H3CameraReferenceBalance": "H3 Camera · Semantic Video + Dense Audio",
}
