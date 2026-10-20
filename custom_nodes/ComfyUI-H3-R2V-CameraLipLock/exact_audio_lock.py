"""Exact target-audio conditioning for visible-mouth camera segments."""
import logging

import torch
import torch.nn.functional as F
import torchaudio
from comfy.nested_tensor import NestedTensor

from .clean_forward import attach_clean_forward


LOG = logging.getLogger("h3_camera_exact_audio_lock")


class H3CameraExactAudioLock:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "av_latent": ("LATENT",),
            "audio_vae": ("VAE",),
            "audio": ("AUDIO",),
        }}

    RETURN_TYPES = ("MODEL", "LATENT")
    RETURN_NAMES = ("model", "av_latent")
    FUNCTION = "lock_audio"
    CATEGORY = "MiniMax H3/R2V"
    DESCRIPTION = "Pins the exact segment audio into H3's target audio stream so visible mouth motion follows the source timing."

    def lock_audio(self, model, av_latent, audio_vae, audio):
        samples = av_latent.get("samples")
        if samples is None or not getattr(samples, "is_nested", False):
            raise ValueError("Strict Lip Sync requires a joint H3 video/audio latent.")
        streams = samples.unbind()
        if len(streams) != 2:
            raise ValueError("Strict Lip Sync expects exactly one video and one audio latent stream.")
        video, template = streams
        if video.shape[0] != 1 or template.ndim != 4 or tuple(template.shape[:3]) != (1, 32, 2):
            raise ValueError("Strict Lip Sync requires H3 stereo audio latent [1,32,2,T].")
        wave = audio["waveform"]
        sr = int(audio["sample_rate"])
        if (not torch.is_tensor(wave) or wave.ndim != 3 or wave.shape[0] != 1
                or wave.shape[1] not in (1, 2) or wave.shape[-1] == 0 or sr <= 0):
            raise ValueError("Strict Lip Sync requires nonempty mono/stereo segment audio.")
        if not torch.isfinite(wave).all():
            raise ValueError("Strict Lip Sync source audio contains NaN/Inf.")
        vae_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
        if vae_rate != 32000:
            raise ValueError("Strict Lip Sync requires the MiniMax H3 32 kHz audio VAE.")
        target_t = template.shape[-1]
        duration_delta = target_t / 40 - wave.shape[-1] / sr
        if not -0.051 <= duration_delta <= 0.76:
            raise ValueError(
                f"Strict Lip Sync segment timing mismatch ({duration_delta:+.3f}s). "
                "The matching segment audio must be connected."
            )
        wave = wave.detach().float()
        if sr != vae_rate:
            wave = torchaudio.functional.resample(wave, sr, vae_rate)
        if wave.shape[1] == 1:
            wave = wave.expand(-1, 2, -1)
        desired = target_t * 800
        wave = F.pad(wave[..., :desired], (0, max(0, desired - wave.shape[-1])))
        exact = audio_vae.encode(wave.movedim(1, -1))
        if tuple(exact.shape[:3]) != tuple(template.shape[:3]) or abs(exact.shape[-1] - target_t) > 2:
            raise ValueError("Strict Lip Sync audio VAE returned an incompatible latent shape.")
        exact = F.pad(exact[..., :target_t], (0, max(0, target_t - exact.shape[-1])))
        mask = av_latent.get("noise_mask")
        if mask is None:
            video_mask = torch.ones_like(video)
        elif getattr(mask, "is_nested", False) and len(mask.unbind()) == 2:
            video_mask = mask.unbind()[0]
        else:
            raise ValueError("Strict Lip Sync received an incompatible joint AV noise mask.")
        clean_network_audio = model.model.latent_format.process_in(exact)
        patched = attach_clean_forward(model, clean_network_audio)
        locked = dict(av_latent)
        locked["samples"] = NestedTensor((video, exact))
        locked["noise_mask"] = NestedTensor((video_mask, torch.zeros_like(exact)))
        LOG.info("Strict Lip Sync: exact source segment audio locked at %d H3 audio ticks", target_t)
        return patched, locked


NODE_CLASS_MAPPINGS = {"H3CameraExactAudioLock": H3CameraExactAudioLock}
NODE_DISPLAY_NAME_MAPPINGS = {"H3CameraExactAudioLock": "H3 Camera · Strict Lip Sync"}
