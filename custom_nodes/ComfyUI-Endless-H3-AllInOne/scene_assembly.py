"""Write one Endless scene at a time, then join its encoded files with FFmpeg."""
from fractions import Fraction
import json
import os

import nodes
from comfy_api.latest import InputImpl, Types

from .media_concat import concat_files, video_info
from .project_store import ProjectError
from .sequence_plan import overlap_frames


def scene_ranges(plan, last):
    ranges = []
    first = 1
    for index in range(2, last + 1):
        if plan['clips'][index - 1]['scene_id'] != plan['clips'][index - 2]['scene_id']:
            ranges.append((first, index - 1))
            first = index
    return ranges + [(first, last)]


def assembly_job(store, project_id, job_id):
    project = store.load(project_id)
    job = project['jobs'].get(job_id)
    if not job or job['action'] != 'assemble' or not job['plan'].get('sequence_mode'):
        raise ProjectError('시퀀스 합치기 작업을 찾을 수 없습니다.')
    if not 1 <= job['index'] <= len(job['plan']['clips']):
        raise ProjectError('씬 합치기 클립 범위가 올바르지 않습니다.')
    directory = (store.folder(project_id) / 'jobs' / job_id).resolve()
    if not directory.is_relative_to(store.folder(project_id)) or directory.parent.name != 'jobs':
        raise ProjectError('씬 합치기 저장 경로가 올바르지 않습니다.')
    return project, job, directory


def approved_scenes(store, directory, manifest, count):
    entries = json.loads(manifest)
    if not isinstance(entries, list) or len(entries) != count:
        raise ProjectError('앞 씬의 합치기 결과가 누락됐습니다.')
    for index, entry in enumerate(entries, 1):
        expected = directory / 'scenes' / f'scene_{index:05d}.mp4'
        if not isinstance(entry, dict) or type(entry.get('frames')) is not int or entry['frames'] <= 0:
            raise ProjectError('씬 합치기 결과 기록이 올바르지 않습니다.')
        if store.output_file(entry.get('video', '')) != expected or not expected.is_file():
            raise ProjectError('현재 작업의 씬 영상 파일을 찾을 수 없습니다.')
    return entries


def stitch_scene(store, project_id, job_id, scene_index, video_vae, audio_vae=None, previous_scenes='[]', master_audio=None):
    if audio_vae is None and master_audio is None:
        raise ProjectError('음성 VAE 또는 립싱크 원본 오디오를 연결해 주세요.')
    project, job, directory = assembly_job(store, project_id, job_id)
    ranges = scene_ranges(job['plan'], job['index'])
    if not 1 <= scene_index <= len(ranges):
        raise ProjectError('합칠 씬 번호가 올바르지 않습니다.')
    entries = approved_scenes(store, directory, previous_scenes, scene_index - 1)
    first, last = ranges[scene_index - 1]
    folder = directory / 'scenes' / f'latents_{scene_index:05d}'
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(first, last + 1):
        source = store.output_file(project['clips'][str(index)]['latent'])
        if not source.is_relative_to(store.folder(project_id)) or not source.is_file():
            raise ProjectError(f'클립 {index}의 승인된 AV 연결 데이터를 찾을 수 없습니다.')
        target = folder / f'clip_{index:05d}.safetensors'
        if target.exists():
            if not os.path.samefile(source, target):
                raise ProjectError('씬 합치기 연결 데이터가 기존 작업과 다릅니다.')
        else:
            os.link(source, target)
    stitcher = nodes.NODE_CLASS_MAPPINGS['H3MotionContextClipStitcher -noEmbryo']
    images, audio, _, _ = stitcher.stitch(str(folder), 'clip_*.safetensors', first, last,
        job['plan']['settings']['context_length'], 24.0, video_vae,
        audio_vae if master_audio is None else None)
    trim_type = nodes.NODE_CLASS_MAPPINGS['EndlessV15MiniMaxH3MotionContextTrim']
    trim = getattr(trim_type(), trim_type.FUNCTION)
    images, audio = trim(images=images, audio=audio, trim_frames=overlap_frames(job['plan'], first), fps=24.0, match_tail=True)
    if master_audio is not None:
        images, audio = trim(images=images, audio=master_audio, trim_frames=0, fps=24.0, match_tail=True)
    frames = len(images)
    expected_frames = sum(project['clips'][str(i)]['frames'] for i in range(first, last + 1))
    if frames != expected_frames:
        raise ProjectError(f'씬 {scene_index}의 AV 디코딩 프레임 수가 클립 저장 기록과 다릅니다.')
    output = directory / 'scenes' / f'scene_{scene_index:05d}.mp4'
    temporary = output.with_name(output.stem + '.partial.mp4')
    try:
        video = InputImpl.VideoFromComponents(Types.VideoComponents(images=images, audio=audio, frame_rate=Fraction(24)),
                                             bit_depth=8, color_space='sRGB')
        video.save_to(str(temporary), format=Types.VideoContainer.MP4, codec=Types.VideoCodec.AUTO)
        info = video_info(temporary)
        if info['frames'] != frames or info['fps'] != 24:
            raise ProjectError('씬 영상 저장 후 프레임 수 또는 FPS가 달라졌습니다.')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    entries.append({'video':output.relative_to(store.output).as_posix(),'frames':frames})
    print(f'Endless scene {scene_index}/{len(ranges)} saved: clips {first}-{last}, {frames} frames')
    return json.dumps(entries)


def concat_scenes(store, project_id, job_id, scene_manifest):
    project, job, directory = assembly_job(store, project_id, job_id)
    ranges = scene_ranges(job['plan'], job['index'])
    entries = approved_scenes(store, directory, scene_manifest, len(ranges))
    for entry, (first, last) in zip(entries, ranges):
        expected = sum(project['clips'][str(i)]['frames'] for i in range(first, last + 1))
        if entry['frames'] != expected:
            raise ProjectError('씬 합본의 프레임 수가 현재 클립 기록과 다릅니다.')
    return concat_files([store.output_file(x['video']) for x in entries], [x['frames'] for x in entries], directory, label='씬')
