"""Construct ordinary native Comfy graphs, without a private sampler or model patch."""
import copy
import math
import re
import secrets
from pathlib import Path

from .project_store import ProjectError
from .scene_assembly import scene_ranges
from .sequence_plan import expand_scene_clips, normalize_sequence, scene_references, shared_prompt, continues_clip, scene_start, overlap_frames


DEFAULTS = dict(
    model='minimax_h3_fl2va_pruned_int8_convrot.safetensors',
    clip='qwen3vl_32b_minimax_h3_int8_convrot.safetensors',
    video_vae='minimax_h3_video_vae_fp16.safetensors',
    audio_vae='minimax_h3_audio_vae_fp32.safetensors',
    turbo_lora='minimax\\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_resized_avg_rank_21_bf16.safetensors',
    turbo_strength=0.9,
    reference_lora='minimax\\minimax_h3_ref_lora_layer20-49adaln_proj_rank_256_bf16.safetensors',
    reference_strength=1.0, width=576, height=768, steps=8, sampler='res_multistep',
    scheduler='sgm_uniform', shift_video=12.0, shift_audio=3.0,
    context_length='22', sage=True, chunks=2, attention_mode=None, fp16_accumulation=False,
    cache_mode='off', easycache_threshold=0.12, spectrum_blend=0.5,
    refiner=False, refiner_strength=0.1,
    ref_image_size='max', shared_prompt='', loras=[], audio_file='',
    upscale=False, scale=2.0, memory_profile='Auto', motion_repair='Auto',
    motion_repair_strength=30, color_treatment='Auto Natural', output_quality=95,
)


def default_plan():
    return dict(settings=copy.deepcopy(DEFAULTS), references=dict(images=[], videos=[], audios=[]), clips=[dict(prompt='', seconds=5.0,
                mode='I2V', first_image='', last_image='', images=[], videos=[], audios=[], seed=-1)])


PICTURE_TOKEN = re.compile(r'<Picture\s+(\d+)>|@picture_(\d+)(?![\w-])', re.IGNORECASE)


def common_picture_indices(plan, clip):
    text = shared_prompt(plan, clip) + '\n' + clip['prompt']
    indices = sorted({int(m[1] or m[2]) for m in PICTURE_TOKEN.finditer(text)})
    if any(i < 1 or i > len(scene_references(plan, clip)['images']) for i in indices):
        raise ProjectError('프롬프트의 Picture 번호에 해당하는 공통 이미지를 등록해 주세요.')
    return indices


def normalize_clip_refiner(value, index):
    """Prompt-author metadata, never injected into the H3 generation text."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ProjectError(f'클립 {index}: 리파이너 설정은 객체로 입력해 주세요.')
    value = copy.deepcopy(value)
    if set(value) - {'mode', 'enabled', 'strength', 'reference_clip', 'reason'}:
        raise ProjectError(f'클립 {index}: 지원하지 않는 리파이너 항목이 있습니다.')
    if 'enabled' in value:
        if type(value['enabled']) is not bool:
            raise ProjectError(f'클립 {index}: refiner.enabled는 true/false입니다.')
        mode = 'on' if value.pop('enabled') else 'off'
        if 'mode' in value and value['mode'] != mode:
            raise ProjectError(f'클립 {index}: 리파이너 mode와 enabled가 충돌합니다.')
        value['mode'] = mode
    out = dict(mode='off', strength=0.1, reference_clip=1, reason='')
    out.update(value)
    if out['mode'] not in ('inherit', 'off', 'on'):
        raise ProjectError(f'클립 {index}: 리파이너 mode는 off/on입니다.')
    # Legacy inheritance is accepted only to migrate to safe opt-in OFF.
    if out['mode'] == 'inherit':
        out['mode'] = 'off'
    v = out['strength']
    if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 3:
        raise ProjectError(f'클립 {index}: 리파이너 강도는 0~3 범위입니다.')
    if type(out['reference_clip']) is not int or not 1 <= out['reference_clip'] <= 9999:
        raise ProjectError(f'클립 {index}: 기준 클립 번호는 1 이상의 정수입니다.')
    if out['mode'] == 'on' and out['reference_clip'] >= index and not (index == 1 and out['reference_clip'] == 1):
        raise ProjectError(f'클립 {index}: 리파이너 기준은 현재 클립보다 앞선 클립이어야 합니다.')
    if not isinstance(out['reason'], str) or len(out['reason']) > 2000:
        raise ProjectError(f'클립 {index}: 리파이너 판단 근거는 2000자 이내 문자열입니다.')
    return out


def resolve_clip_refiner(settings, clip, index):
    r = normalize_clip_refiner(clip.get('refiner'), index)
    # Legacy common settings remain loadable but never enable a clip.
    return dict(enabled=r['mode'] == 'on', strength=r['strength'], reference_clip=r['reference_clip'])


def normalize_plan(value):
    if not isinstance(value, dict):
        raise ProjectError('프로젝트 설정이 올바르지 않습니다.')
    plan = copy.deepcopy(value)
    expand_scene_clips(plan)
    settings = {**DEFAULTS, **plan.get('settings', {})}
    if settings['attention_mode'] is None:
        settings['attention_mode'] = 'h3_sage' if settings['sage'] else 'off'
    if settings['attention_mode'] not in ('off', 'h3_sage', 'kj_sage', 'pytorch', 'kitchen'):
        raise ProjectError('Attention 옵션이 올바르지 않습니다.')
    settings['sage'] = settings['attention_mode'] == 'h3_sage'
    if settings['cache_mode'] not in ('off', 'easycache', 'spectrum'):
        raise ProjectError('캐시 옵션이 올바르지 않습니다.')
    clips = plan.get('clips')
    if not isinstance(clips, list) or not 1 <= len(clips) <= 9999:
        raise ProjectError('클립은 1개 이상, 9999개 이하로 설정해 주세요.')
    for key in ('width', 'height'):
        v = settings[key]
        if type(v) is not int or not 256 <= v <= 8192 or v % 32:
            raise ProjectError('가로·세로 해상도는 256 이상인 32의 배수로 입력해 주세요.')
    if type(settings['steps']) is not int or not 1 <= settings['steps'] <= 200:
        raise ProjectError('스텝은 1~200 사이로 설정해 주세요.')
    if settings['context_length'] not in ('5', '22', '39', '56'):
        raise ProjectError('지원하는 연결 길이는 5, 22, 39, 56프레임입니다.')
    if type(settings['chunks']) is not int or not 1 <= settings['chunks'] <= 64:
        raise ProjectError('메모리 분할은 1~64 사이로 설정해 주세요.')
    if not isinstance(settings['shared_prompt'], str):
        raise ProjectError('공통 프롬프트가 올바르지 않습니다.')
    for key in ('sage', 'refiner', 'upscale', 'fp16_accumulation'):
        if type(settings[key]) is not bool:
            raise ProjectError(f'{key} 항목은 ON/OFF로 설정해 주세요.')
    for key in ('model', 'clip', 'video_vae', 'audio_vae', 'turbo_lora', 'reference_lora',
                'sampler', 'scheduler', 'audio_file'):
        if not isinstance(settings[key], str):
            raise ProjectError(f'{key} 파일 또는 설정 이름이 올바르지 않습니다.')
    for key, minimum, maximum in [('turbo_strength', -10, 10), ('reference_strength', -10, 10),
                                  ('refiner_strength', 0, 3), ('scale', 1, 4),
                                  ('shift_video', .01, 100), ('shift_audio', .01, 100),
                                  ('easycache_threshold', 0, 3), ('spectrum_blend', 0, 1)]:
        v = settings[key]
        if type(v) not in (int, float) or not math.isfinite(v) or not minimum <= v <= maximum:
            raise ProjectError(f'{key} 설정 범위가 올바르지 않습니다.')
    if settings['memory_profile'] not in ('Auto', 'Quality', 'Low VRAM'):
        raise ProjectError('업스케일 메모리 프리셋이 올바르지 않습니다.')
    if settings['color_treatment'] not in ('Off', 'Auto Natural', 'Auto Bright'):
        raise ProjectError('업스케일 색상 보정 설정이 올바르지 않습니다.')
    if type(settings['output_quality']) is not int or not 80 <= settings['output_quality'] <= 99:
        raise ProjectError('업스케일 출력 품질은 80~99 사이 정수로 설정해 주세요.')
    if settings['motion_repair'] not in ('Auto', 'Action Strong', 'NVIDIA 가변 프레임 보간', 'Off'):
        raise ProjectError('모션 리페어 설정이 올바르지 않습니다.')
    if settings['motion_repair_strength'] not in range(10, 51, 5):
        raise ProjectError('모션 리페어 강도는 10~50 사이 5 단위로 설정해 주세요.')
    if settings['ref_image_size'] not in ('match', 'max'):
        raise ProjectError('참고 이미지 크기 설정이 올바르지 않습니다.')
    if not isinstance(settings['loras'], list) or len(settings['loras']) > 20:
        raise ProjectError('추가 LoRA 설정이 올바르지 않습니다.')
    for lora in settings['loras']:
        if not isinstance(lora, dict) or not isinstance(lora.get('name'), str):
            raise ProjectError('추가 LoRA 이름을 선택해 주세요.')
        strength = lora.get('strength', 1.0)
        if type(strength) not in (int, float) or not math.isfinite(strength) or not -10 <= strength <= 10:
            raise ProjectError('추가 LoRA 강도는 -10~10 범위로 설정해 주세요.')
        lora['strength'] = strength
    for index, c in enumerate(clips, 1):
        if not isinstance(c, dict) or not isinstance(c.get('prompt'), str):
            raise ProjectError('클립 프롬프트가 올바르지 않습니다.')
        c['refiner'] = normalize_clip_refiner(c.get('refiner'), index)
        c.setdefault('seconds', 5.0)
        c.setdefault('mode', 'I2V')
        c.setdefault('first_image', '')
        c.setdefault('last_image', '')
        c.setdefault('images', [])
        c.setdefault('videos', [])
        c.setdefault('audios', [])
        c.setdefault('seed', -1)
        c.setdefault('background_refresh', False)
        c.setdefault('background_source', 'image')
        c.setdefault('background_image', '')
        c.setdefault('background_time', 0.0)
        if type(c['background_refresh']) is not bool or c['background_source'] not in ('image', 'clip1'):
            raise ProjectError('배경 참고 재생성 옵션이 올바르지 않습니다.')
        if not isinstance(c['background_image'], str):
            raise ProjectError('배경 참고 이미지 이름이 올바르지 않습니다.')
        if type(c['background_time']) not in (int, float) or not math.isfinite(c['background_time']) or not 0 <= c['background_time'] <= 15:
            raise ProjectError('첫 클립의 참고 시점은 0~15초 사이로 설정해 주세요.')
        if type(c['seconds']) not in (int, float) or not math.isfinite(c['seconds']) or not 3 <= c['seconds'] <= 15:
            raise ProjectError('한 클립 길이는 3~15초 사이로 설정해 주세요.')
        if c['mode'] not in ('I2V', 'R2V', 'T2V'):
            raise ProjectError('생성 방식이 올바르지 않습니다.')
        if not isinstance(c['images'], list) or len(c['images']) > 9 or not all(isinstance(i, str) for i in c['images']):
            raise ProjectError('클립별 참고 이미지는 최대 9개입니다.')
        if not isinstance(c['videos'], list) or len(c['videos']) > 3:
            raise ProjectError('클립별 참고 비디오는 최대 3개입니다.')
        if not isinstance(c['audios'], list) or len(c['audios']) > 3 or not all(isinstance(a, str) for a in c['audios']):
            raise ProjectError('클립별 참고 오디오는 최대 3개입니다.')
        for video in c['videos']:
            if not isinstance(video, dict) or not isinstance(video.get('name'), str):
                raise ProjectError('참고 비디오 파일 이름이 올바르지 않습니다.')
            video.setdefault('use_audio', False)
            if type(video['use_audio']) is not bool:
                raise ProjectError('참고 비디오 소리는 ON/OFF로 선택해 주세요.')
        if any(not isinstance(c[k], str) for k in ('first_image', 'last_image')):
            raise ProjectError('이미지 파일 이름이 올바르지 않습니다.')
        if type(c['seed']) is not int or not -1 <= c['seed'] <= 18446744073709551615:
            raise ProjectError('시드는 -1(랜덤) 또는 0 이상의 정수로 설정해 주세요.')
    # Old plans retain clip-specific lists; an empty clip inherits the first R2V list.
    references = plan.get('references')
    if references is None:
        source = next((c for c in clips if c['mode'] == 'R2V' and any(c[k] for k in ('images', 'videos', 'audios'))), {})
        references = {k: copy.deepcopy(source.get(k, [])) for k in ('images', 'videos', 'audios')}
    if not isinstance(references, dict):
        raise ProjectError('공통 참고 자료가 올바르지 않습니다.')
    references = {k: copy.deepcopy(references.get(k, [])) for k in ('images', 'videos', 'audios')}
    if not isinstance(references['images'], list) or len(references['images']) > 9 or not all(isinstance(i, str) for i in references['images']):
        raise ProjectError('공통 참고 이미지는 최대 9개입니다.')
    if not isinstance(references['audios'], list) or len(references['audios']) > 3 or not all(isinstance(a, str) for a in references['audios']):
        raise ProjectError('공통 참고 오디오는 최대 3개입니다.')
    if not isinstance(references['videos'], list) or len(references['videos']) > 3:
        raise ProjectError('공통 참고 비디오는 최대 3개입니다.')
    for video in references['videos']:
        if not isinstance(video, dict) or not isinstance(video.get('name'), str):
            raise ProjectError('공통 참고 비디오 파일 이름이 올바르지 않습니다.')
        video.setdefault('use_audio', False)
        if type(video['use_audio']) is not bool:
            raise ProjectError('공통 참고 비디오 소리는 ON/OFF로 선택해 주세요.')
    sequence = normalize_sequence(plan, clips, references)
    scope_plan = dict(settings=settings, references=references, clips=clips, **sequence)
    for c in clips:
        scoped = scene_references(scope_plan, c)
        c.setdefault('use_common_references', not any(c[k] for k in references) or all(c[k] == scoped[k] for k in references))
        if type(c['use_common_references']) is not bool:
            raise ProjectError('공통 참고 사용은 ON/OFF로 선택해 주세요.')
        if c['mode'] == 'R2V' and c['use_common_references']:
            c.update(copy.deepcopy(scoped))
            indices = common_picture_indices(scope_plan, c)
            c['images'] = [scoped['images'][i - 1] for i in indices]
        if c['background_refresh'] and c['background_source'] == 'image' and not c['background_image']:
            raise ProjectError('배경 참고 이미지를 선택하거나 첫 클립 참고로 바꿔 주세요.')
        if c['background_refresh'] and c['mode'] == 'R2V' and len([i for i in c['images'] if i]) >= 9:
            raise ProjectError('배경 참고를 추가하려면 이 클립의 일반 참고 이미지를 8개 이하로 줄여 주세요.')
    return dict(settings=settings, references=references, clips=clips, **sequence)


def background_directive(prompt, number):
    """Add a local role only; never duplicate dialogue or edit the saved prompt."""
    label = f'<Picture {number}>'
    definition = (f'{label} is an environment composition reference for this clip. '
                  'Use its visible background layout, surfaces and environmental detail; '
                  'do not transfer its people, clothing, poses, text or overlays.')
    retention = f'{label} (environment composition): weak_reference - background layout and detail only.'
    instruction = (f'Refresh the background using {label} instead of reproducing degraded background detail from the incoming clip. '
                   'Preserve the same people from their existing identity references and incoming frame, '
                   'and retain the requested actions, camera motion, shot timing, dialogue and sound. '
                   'Adapt the background to the requested viewpoint rather than copying the reference as a full frame.')
    additions = {'subject_definitions': definition, 'retention_analysis': retention,
                 'detailed_description': instruction}
    headings = list(re.finditer(r'(?m)^(subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music):[ \t]*$', prompt))
    if all(any(m[1] == name for m in headings) for name in additions):
        for match in reversed(headings):
            if match[1] in additions:
                prompt = prompt[:match.end()] + '\n' + additions[match[1]] + prompt[match.end():]
        return prompt
    return prompt + '\n\n' + definition + '\n' + instruction


def frame_count(seconds, index, context):
    # Clip duration is delivered duration: subsequent clips add their discarded overlap.
    requested = round(seconds * 24) + (int(context) if index > 1 else 0)
    return max(5, 5 + round((requested - 5) / 17) * 17)


def clip_frame_count(plan, index):
    return frame_count(plan['clips'][index - 1]['seconds'], 2 if continues_clip(plan, index) else 1, plan['settings']['context_length'])


class Graph:
    def __init__(self):
        self.prompt = {}

    def add(self, class_type, **inputs):
        key = str(len(self.prompt) + 1)
        self.prompt[key] = dict(class_type=class_type, inputs=inputs)
        return [key, 0]

    @staticmethod
    def slot(ref, index):
        return [ref[0], index]


UPSCALE_SETTING_KEYS = ('scale', 'memory_profile', 'motion_repair', 'motion_repair_strength',
                        'color_treatment', 'output_quality')


def normalize_upscale_settings(value):
    if not isinstance(value, dict):
        raise ProjectError('업스케일 설정이 올바르지 않습니다.')
    probe = default_plan()
    probe['settings'].update({key: value[key] for key in UPSCALE_SETTING_KEYS if key in value})
    settings = normalize_plan(probe)['settings']
    return {key: settings[key] for key in UPSCALE_SETTING_KEYS}


def add_upscale(g, video, s):
    return g.add('RTXVideoVSRRestore', video=video, scale=s['scale'], upscale_quality='Ultra',
                 restore_mode='Auto Scan (Clean/Chain90)', quality_target='110% Master',
                 color_treatment=s.get('color_treatment', DEFAULTS['color_treatment']),
                 output_quality=s.get('output_quality', DEFAULTS['output_quality']), encode_preset='slow',
                 temporal_mode='Auto Temporal', subject_recovery='Auto', enabled=True,
                 hdr_enabled=False, output_mode='SDR', motion_repair=s['motion_repair'],
                 motion_repair_strength=s['motion_repair_strength'], memory_profile=s['memory_profile'])


def build_output_upscale_prompt(project, job, store):
    directory = store.folder(project['id']) / 'jobs' / job['id']
    directory.mkdir(parents=True, exist_ok=True)
    prefix = directory.relative_to(store.output).as_posix()
    g = Graph()
    source = g.add('EndlessH3OutputVideo', video_path=job['source_video'])
    video = add_upscale(g, source, job['plan']['settings'])
    saved = g.add('SaveVideo', video=video, filename_prefix=prefix + '/video',
                  format='auto', **{'format.codec': 'auto'})
    g.add('EndlessH3ProjectCommit', video=saved, project_id=project['id'], job_id=job['id'],
          frames=g.slot(source, 1))
    return g.prompt


def build_scene_assembly_prompt(project, job, store, *, preview=False):
    s = job['plan']['settings']
    ranges = scene_ranges(job['plan'], job['index'])
    overlap = int(s['context_length'])
    for first, last in ranges:
        if first < last and any(project['clips'][str(i)]['frames'] + overlap_frames(job['plan'], i) < 2 * overlap
                                for i in range(first, last + 1)):
            raise ProjectError('Endless 씬 합치기는 연결된 클립마다 연결 길이의 2배 이상 프레임이 필요합니다.')
    directory = store.folder(project['id']) / 'jobs' / job['id']
    g = Graph()
    vvae = g.add('VAELoader', vae_name=s['video_vae'])
    avae = g.add('VAELoader', vae_name=s['audio_vae']) if not s['audio_file'] else None
    master = g.add('LoadAudio', audio=s['audio_file']) if s['audio_file'] else None
    previous = None
    for number, (first, last) in enumerate(ranges, 1):
        inputs = dict(project_id=project['id'], job_id=job['id'], scene_index=number, video_vae=vvae)
        if avae:
            inputs['audio_vae'] = avae
        if previous:
            inputs['previous_scenes'] = previous
        if master:
            offset = sum(project['clips'][str(i)]['frames'] for i in range(1, first)) / 24.0
            seconds = sum(project['clips'][str(i)]['frames'] for i in range(first, last + 1)) / 24.0
            inputs['master_audio'] = g.add('TrimAudioDuration', audio=master, start_index=offset, duration=seconds)
        previous = g.add('EndlessH3StitchScene', **inputs)
    source = g.add('EndlessH3ConcatScenes', project_id=project['id'], job_id=job['id'], scene_manifest=previous)
    video = add_upscale(g, source, s) if s['upscale'] else source
    saved = g.add('SaveVideo', video=video, filename_prefix=directory.relative_to(store.output).as_posix() + '/video',
                  format='auto', **{'format.codec': 'auto'})
    if not preview:
        g.add('EndlessH3ProjectCommit', video=saved, project_id=project['id'], job_id=job['id'], frames=g.slot(source, 1))
    return g.prompt


def build_assembly_prompt(project, job, store, *, preview=False):
    if job['plan'].get('sequence_mode'):
        return build_scene_assembly_prompt(project, job, store, preview=preview)
    directory = store.folder(project['id']) / 'jobs' / job['id']
    if not preview:
        directory.mkdir(parents=True, exist_ok=True)
    prefix = directory.relative_to(store.output).as_posix()
    g = Graph()
    source = g.add('EndlessH3ConcatClips', project_id=project['id'], job_id=job['id'])
    video = add_upscale(g, source, job['plan']['settings']) if job['plan']['settings']['upscale'] else source
    saved = g.add('SaveVideo', video=video, filename_prefix=prefix + '/video',
                  format='auto', **{'format.codec': 'auto'})
    if not preview:
        g.add('EndlessH3ProjectCommit', video=saved, project_id=project['id'], job_id=job['id'],
              frames=g.slot(source, 1))
    return g.prompt


def build_prompt(project, job, store, *, preview=False):
    if job['action'] == 'assemble':
        return build_assembly_prompt(project, job, store, preview=preview)
    s = job['plan']['settings']
    g = Graph()
    directory = store.folder(project['id']) / 'jobs' / job['id']
    if not preview:
        directory.mkdir(parents=True, exist_ok=True)
    prefix = directory.relative_to(store.output).as_posix()
    vvae = g.add('VAELoader', vae_name=s['video_vae'])
    avae = g.add('VAELoader', vae_name=s['audio_vae'])
    latent_save = None
    index = job['index']
    c = job['plan']['clips'][index - 1]
    refresh = c.get('background_refresh', False)
    if refresh and not project['clips'].get(str(index), {}).get('video'):
        raise ProjectError('배경 참고 옵션은 이미 생성한 클립의 재생성에만 사용할 수 있습니다.')
    continuation = continues_clip(job['plan'], index)
    length = clip_frame_count(job['plan'], index)
    frames = length - overlap_frames(job['plan'], index)
    model = g.add('UNETLoader', unet_name=s['model'], weight_dtype='default')
    # The original author's FL2VA-to-reference conversion LoRA is task-specific.
    if (c['mode'] == 'R2V' or refresh) and s['reference_lora']:
        model = g.add('LoraLoaderModelOnly', model=model, lora_name=s['reference_lora'],
                      strength_model=s['reference_strength'])
    if s['turbo_lora']:
        model = g.add('LoraLoaderModelOnly', model=model, lora_name=s['turbo_lora'], strength_model=s['turbo_strength'])
    for lora in s['loras']:
        if lora.get('enabled', True) and lora['name']:
            model = g.add('LoraLoaderModelOnly', model=model, lora_name=lora['name'], strength_model=lora['strength'])
    attention = s.get('attention_mode') or ('h3_sage' if s['sage'] else 'off')
    if attention == 'h3_sage':
        model = g.add('MiniMaxH3MemoryEfficientSageAttentionPatch', model=model)
    elif attention == 'kj_sage':
        model = g.add('PathchSageAttentionKJ', model=model, sage_attention='auto', allow_compile=False)
    elif attention in ('pytorch', 'kitchen'):
        model = g.add('ModelAttentionBackend', model=model,
                      attention='pytorch attention' if attention == 'pytorch' else 'comfy kitchen attention')
    if s['chunks'] > 1:
        model = g.add('MiniMaxChunkFeedForward', model=model, chunks=s['chunks'], seq_threshold=4096)
    if s.get('fp16_accumulation', False):
        model = g.add('ModelPatchTorchSettings', model=model, enable_fp16_accumulation=True)
    if s.get('cache_mode') == 'easycache':
        model = g.add('EasyCache', model=model, reuse_threshold=s['easycache_threshold'],
                      start_percent=0.2, end_percent=0.9, verbose=False)
    elif s.get('cache_mode') == 'spectrum':
        model = g.add('SpectrumApplyMiniMaxH3', model=model, enabled=True,
                      blend_weight=s['spectrum_blend'], degree=1, ridge_lambda=0.1,
                      window_size=2.0, flex_window=0.75, warmup_steps=1,
                      tail_actual_steps=2, max_history=8, debug=False, history_storage='system_ram',
                      offline_archive_storage='system_ram', audio_blend_weight=0.0)
    model = g.add('MiniMaxH3SigmaShift', model=model, shift_video=s['shift_video'], shift_audio=s['shift_audio'])
    clip = g.add('CLIPLoader', clip_name=s['clip'], type='minimax', device='default')
    prompt = '\n\n'.join(t for t in (shared_prompt(job['plan'], c), c['prompt'].strip()) if t)
    if c['mode'] == 'R2V' and c.get('use_common_references'):
        indices = common_picture_indices(job['plan'], c)
        local = {number: n for n, number in enumerate(indices, 1)}
        prompt = PICTURE_TOKEN.sub(lambda m: f'<Picture {local[int(m[1] or m[2])]}>', prompt)
    reference_images = [i for i in c['images'] if i] if c['mode'] == 'R2V' else []
    if refresh and c['mode'] != 'R2V':
        # Retain the opening/final image labels when enabling reference conditioning.
        reference_images = [c[k] for k in ('first_image', 'last_image') if c[k]]
    if refresh:
        prompt = background_directive(prompt, len(reference_images) + 1)
    kwargs = dict(clip=clip, vae=vvae, prompt=prompt, width=s['width'], height=s['height'], length=length)
    if c['mode'] == 'R2V' or refresh:
        kwargs.update(audio_vae=avae, ref_image_size=s['ref_image_size'])
        for n, image in enumerate(reference_images):
            kwargs[f'ref_images.ref_image_{n}'] = g.add('LoadImage', image=image)
        if refresh:
            if c['background_source'] == 'clip1':
                first = project['clips'].get('1', {})
                if not first.get('video'):
                    raise ProjectError('첫 클립의 생성 영상을 찾을 수 없습니다.')
                store.output_file(first['video'])  # Enforce the same project-output containment.
                background = g.add('EndlessH3BackgroundFrame', video_path=first['video'], seconds=c['background_time'])
            else:
                background = g.add('LoadImage', image=c['background_image'])
            kwargs[f'ref_images.ref_image_{len(reference_images)}'] = background
        for n, reference in enumerate(v for v in (c.get('videos', []) if c['mode'] == 'R2V' else []) if v['name']):
            frames_ref = g.add('VHS_LoadVideoFFmpeg', video=reference['name'], force_rate=24,
                               custom_width=0, custom_height=0, frame_load_cap=min(length, 360), start_time=0.0)
            kwargs[f'ref_videos.ref_video_{n}'] = frames_ref
            if reference['use_audio']:
                kwargs[f'ref_video_audios.ref_video_audio_{n}'] = g.slot(frames_ref, 2)
        for n, name in enumerate(a for a in (c.get('audios', []) if c['mode'] == 'R2V' else []) if a):
            loaded_audio = g.add('LoadAudio', audio=name)
            kwargs[f'ref_audios.ref_audio_{n}'] = g.add('TrimAudioDuration', audio=loaded_audio,
                start_index=0.0, duration=min(length / 24, 15.0))
        cond = g.add('MiniMaxH3ReferenceToVideo', **kwargs)
    else:
        # A continued clip is anchored by the previous latent, not a repeated opening image.
        if c['mode'] == 'I2V' and not continuation:
            if not c['first_image'] and not preview:
                raise ProjectError('첫 I2V 클립의 시작 이미지를 선택해 주세요.')
            kwargs['first_frame'] = g.add('LoadImage', image=c['first_image'])
        if c['last_image']:
            kwargs['last_frame'] = g.add('LoadImage', image=c['last_image'])
        cond = g.add('MiniMaxH3ImageToVideo', **kwargs)
    latent = g.slot(cond, 1)
    if refresh and c['mode'] != 'R2V':
        if c['mode'] == 'I2V' and not continuation:
            first = g.add('LoadImage', image=c['first_image'])
            first = g.add('ImageScale', image=first, upscale_method='lanczos', width=s['width'], height=s['height'], crop='disabled')
            cond = g.add('MiniMaxH3AddGuide', positive=cond, vae=vvae, latent=latent, image=first, frame_idx=0)
        if c['last_image']:
            last = g.add('LoadImage', image=c['last_image'])
            cond = g.add('MiniMaxH3AddGuide', positive=cond, vae=vvae, latent=latent, image=last, frame_idx=-1)
    if s['audio_file']:
        offset = max(0, sum(project['clips'][str(i)]['frames'] for i in range(1, index))
                     - overlap_frames(job['plan'], index)) / 24.0
        audio_file = g.add('LoadAudio', audio=s['audio_file'])
        cut = g.add('TrimAudioDuration', audio=audio_file, start_index=offset, duration=length / 24.0)
        encoded = g.add('VAEEncodeAudio', audio=cut, vae=avae)
        mask = g.add('SolidMask', value=0.0, width=1, height=1)
        locked = g.add('SetLatentNoiseMask', samples=encoded, mask=mask)
        # Keep the empty AV canvas here so native Concat fits audio to its exact grid.
        latent = g.add('LTXVConcatAVLatent', video_latent=latent, audio_latent=locked)
    context_inputs = dict(conditioning=cond, vae=vvae, latent=latent,
                          context_length=s['context_length'], audio_context_length=24)
    if continuation:
        previous = store.output_file(project['clips'][str(index - 1)]['latent'])
        context_inputs['context_latent'] = g.add('EndlessV15MiniMaxH3MotionContextLoadLatent',
                                               latent_path=str(previous), clip_index=index - 1)
    context = g.add('EndlessV15MiniMaxH3MotionContext', **context_inputs)
    noise = g.add('RandomNoise', noise_seed=secrets.randbits(64) if c['seed'] == -1 else c['seed'])
    guider = g.add('BasicGuider', model=model, conditioning=context)
    sampler = g.add('KSamplerSelect', sampler_name=s['sampler'])
    sigmas = g.add('BasicScheduler', model=model, scheduler=s['scheduler'], steps=s['steps'], denoise=1.0)
    sampled = g.add('SamplerCustomAdvanced', noise=noise, guider=guider, sampler=sampler, sigmas=sigmas, latent_image=latent)
    refined = sampled
    refiner = resolve_clip_refiner(s, c, index)
    if refiner['enabled'] and refiner['strength'] > 0:
        kwargs = dict(latent=sampled, target_ratio=0.0, strength=refiner['strength'])
        if continuation:
            reference_index = max(refiner['reference_clip'], scene_start(job['plan'], index))
            reference = project['clips'].get(str(reference_index), {})
            if not reference.get('latent'):
                raise ProjectError(f'클립 {index}: 리파이너 기준 클립 {reference_index}을 먼저 생성해 주세요.')
            kwargs['reference_latent'] = g.add('EndlessV15MiniMaxH3MotionContextLoadLatent',
                latent_path=str(store.output_file(reference['latent'])), clip_index=reference_index)
        refined = g.add('H3ClipRefiner -noEmbryo', **kwargs)
    latent_save = g.add('EndlessV15MiniMaxH3MotionContextSaveLatent', latent=refined,
                        filename_prefix=prefix + '/clip', clip_index=index)
    streams = g.add('LTXVSeparateAVLatent', av_latent=refined)
    decoded = g.add('VAEDecode', samples=streams, vae=vvae)
    decoded_audio = cut if s['audio_file'] else g.add('VAEDecodeAudio', samples=g.slot(streams, 1), vae=avae)
    trim = g.add('EndlessV15MiniMaxH3MotionContextTrim', images=decoded, audio=decoded_audio,
                 trim_frames=g.slot(context, 1), fps=24.0, match_tail=True)
    images, audio = trim, g.slot(trim, 1)
    video = g.add('CreateVideo', images=images, audio=audio, fps=24.0,
                  bit_depth='auto', color_space='sRGB', codec='none')
    saved = g.add('SaveVideo', video=video, filename_prefix=prefix + '/video', format='auto', **{'format.codec': 'auto'})
    terminal = dict(video=saved, project_id=project['id'], job_id=job['id'], frames=frames)
    if latent_save:
        terminal['latent_path'] = latent_save
    if not preview:
        g.add('EndlessH3ProjectCommit', **terminal)
    return g.prompt
