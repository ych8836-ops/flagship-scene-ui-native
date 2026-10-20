"""Scene boundaries for the studio's optional sequence mode."""
import copy
import re

from .project_store import ProjectError


def expand_scene_clips(plan):
    if 'clips' in plan or not isinstance(plan.get('scenes'), list):
        return
    clips = []
    for index, scene in enumerate(plan['scenes'], 1):
        if not isinstance(scene, dict) or not isinstance(scene.get('clips'), list):
            raise ProjectError('씬마다 clips 목록을 넣어 주세요.')
        scene.setdefault('id', f'scene_{index}')
        for clip in scene.pop('clips'):
            if not isinstance(clip, dict):
                raise ProjectError('씬의 클립은 프롬프트가 있는 객체여야 합니다.')
            clip['scene_id'] = scene['id']
            clips.append(clip)
    plan['clips'] = clips
    plan.setdefault('sequence_mode', True)


def normalize_sequence(plan, clips, references):
    if not any(key in plan for key in ('sequence_mode', 'scenes')):
        return {}
    mode = plan.get('sequence_mode', False)
    if type(mode) is not bool:
        raise ProjectError('시퀀스 모드는 ON/OFF로 설정해 주세요.')
    scenes = copy.deepcopy(plan.get('scenes', [dict(id='scene_1', name='씬 1')]))
    if not isinstance(scenes, list) or not scenes or len(scenes) > 9999:
        raise ProjectError('씬은 1개 이상 등록해 주세요.')
    ids = []
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ProjectError('씬 설정이 올바르지 않습니다.')
        scene.setdefault('id', f'scene_{index}')
        scene.setdefault('name', f'씬 {index}')
        scene.setdefault('prompt', '')
        scene.setdefault('continue_previous', False)
        scene.setdefault('references', copy.deepcopy(references))
        if not isinstance(scene['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', scene['id']) or scene['id'] in ids:
            raise ProjectError('씬 ID는 중복되지 않는 영문·숫자·밑줄·하이픈이어야 합니다.')
        if not isinstance(scene['name'], str) or not isinstance(scene['prompt'], str) or type(scene['continue_previous']) is not bool:
            raise ProjectError('씬 이름·프롬프트·연결 옵션이 올바르지 않습니다.')
        refs = scene['references']
        if not isinstance(refs, dict):
            raise ProjectError('씬 참고 자료가 올바르지 않습니다.')
        for key, limit in [('images', 9), ('videos', 3), ('audios', 3)]:
            refs.setdefault(key, [])
            if not isinstance(refs[key], list) or len(refs[key]) > limit:
                raise ProjectError(f'씬 {index}: {key} 참고 자료 개수를 확인해 주세요.')
            for item in refs[key]:
                if key == 'videos':
                    if not isinstance(item, dict) or not isinstance(item.get('name'), str):
                        raise ProjectError('씬 참고 비디오 파일을 확인해 주세요.')
                    item.setdefault('use_audio', False)
                    if type(item['use_audio']) is not bool:
                        raise ProjectError('씬 참고 비디오 소리는 ON/OFF로 선택해 주세요.')
                elif not isinstance(item, str):
                    raise ProjectError('씬 참고 파일 이름이 올바르지 않습니다.')
        ids.append(scene['id'])
    position = 0
    for clip in clips:
        clip.setdefault('scene_id', ids[0])
        if clip['scene_id'] not in ids:
            raise ProjectError('클립에 등록되지 않은 씬 ID가 있습니다.')
        current = ids.index(clip['scene_id'])
        if current < position:
            raise ProjectError('같은 씬의 클립은 씬 순서대로 연속 배치해 주세요.')
        position = current
    return dict(sequence_mode=mode, scenes=scenes)


def scene_for_clip(plan, clip):
    if not plan.get('sequence_mode'):
        return None
    return next((scene for scene in plan.get('scenes', []) if scene['id'] == clip.get('scene_id')), None)


def scene_references(plan, clip):
    scene = scene_for_clip(plan, clip)
    return scene['references'] if scene else plan['references']


def shared_prompt(plan, clip):
    scene = scene_for_clip(plan, clip)
    return '\n\n'.join(text.strip() for text in (plan['settings']['shared_prompt'], scene['prompt'] if scene else '') if text.strip())


def continues_clip(plan, index):
    if index <= 1:
        return False
    if not plan.get('sequence_mode'):
        return True
    clip, previous = plan['clips'][index - 1], plan['clips'][index - 2]
    scene = scene_for_clip(plan, clip)
    return clip['scene_id'] == previous['scene_id'] or bool(scene and scene['continue_previous'])


def scene_start(plan, index):
    if not plan.get('sequence_mode'):
        return 1
    identity = plan['clips'][index - 1]['scene_id']
    while index > 1 and plan['clips'][index - 2]['scene_id'] == identity:
        index -= 1
    return index


def overlap_frames(plan, index):
    return int(plan['settings']['context_length']) if continues_clip(plan, index) else 0
