"""Read a local transcript for face conditioning; never replace the source audio."""
from pathlib import Path
from math import gcd

import numpy as np
from scipy.signal import resample_poly

try:
    import ctranslate2
    import tokenizers
    import whisper
except ImportError:
    ctranslate2 = tokenizers = whisper = None

import folder_paths


def local_asr_model():
    local = Path(folder_paths.models_dir)/'whisper/faster-whisper-small'
    if (local/'model.bin').is_file():
        return local
    cache = Path.home()/'.cache/huggingface/hub/models--Systran--faster-whisper-small'
    ref = cache/'refs/main'
    if ref.is_file():
        path = cache/'snapshots'/ref.read_text(encoding='utf-8').strip()
        if (path/'model.bin').is_file():
            return path
    return None


def source_speech(audio):
    path = local_asr_model()
    if path is None or ctranslate2 is None:
        return None, 'local Whisper-small model/backend unavailable; no download attempted'
    rate = int(audio['sample_rate'])
    waveform = audio['waveform'].detach().float().mean(dim=(0,1)).cpu().numpy()
    duration = len(waveform)/rate
    if not 1 <= duration <= 30:
        return None, 'source audio outside 1–30 second transcription window'
    divisor = gcd(rate, 16000)
    samples = resample_poly(waveform, 16000//divisor, rate//divisor).astype(np.float32)
    features = whisper.log_mel_spectrogram(whisper.pad_or_trim(samples)).numpy()[None]
    storage = ctranslate2.StorageView.from_array(features)
    model = ctranslate2.models.Whisper(str(path), device='cpu', compute_type='int8', intra_threads=4)
    language, probability = model.detect_language(storage)[0][0]
    tokenizer = tokenizers.Tokenizer.from_file(str(path/'tokenizer.json'))
    language_token = language if language.startswith('<|') else f'<|{language}|>'
    prefix = [tokenizer.token_to_id(t) for t in ('<|startoftranscript|>', language_token, '<|transcribe|>', '<|notimestamps|>')]
    result = model.generate(storage, [prefix], beam_size=5, return_no_speech_prob=True, return_scores=True)[0]
    text = tokenizer.decode(result.sequences_ids[0], skip_special_tokens=True).strip()
    if probability < .7 or result.no_speech_prob > .3 or result.scores[0] < -1 or len(text) < 2:
        return None, 'uncertain source transcript; face repair bypassed'
    language = language_token.removeprefix('<|').removesuffix('|>')
    return {'text': text, 'language': language, 'language_name': whisper.tokenizer.LANGUAGES.get(language, language).title(), 'language_probability': float(probability),
        'no_speech_probability': float(result.no_speech_prob), 'score': float(result.scores[0]), 'duration': duration}, None


def repair_prompt(speech):
    template = (Path(__file__).parent/'face_audio_prompt.txt').read_text(encoding='utf-8')
    text = speech['text'].replace('<', '').replace('>', '')
    return template.format(duration=f'{speech["duration"]:.3f}', language=speech['language_name'], dialogue=text)
