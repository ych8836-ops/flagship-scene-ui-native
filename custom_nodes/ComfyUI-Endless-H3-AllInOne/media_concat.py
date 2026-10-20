"""Join saved studio clips without loading latents or decoding video frames."""
from pathlib import Path
import subprocess

import av
import imageio_ffmpeg

from .project_store import ProjectError


def video_info(path):
    with av.open(str(path)) as container:
        if len(container.streams.video) != 1 or len(container.streams.audio) > 1:
            raise ProjectError('합치기에는 영상 1개와 오디오 최대 1개의 스트림을 가진 클립이 필요합니다.')
        video = container.streams.video[0]
        frames = video.frames or sum(packet.size > 0 for packet in container.demux(video))
        if not frames or not video.average_rate:
            raise ProjectError(f'클립의 프레임 수와 FPS를 읽지 못했습니다: {path.name}')
        audio = container.streams.audio[0] if container.streams.audio else None
        return dict(frames=frames, fps=video.average_rate, codec=video.codec_context.name,
                    width=video.width, height=video.height, format=video.codec_context.format.name,
                    time_base=video.time_base, sample_rate=audio.codec_context.sample_rate if audio else 0,
                    layout=audio.codec_context.layout.name if audio else '')


def concat_clips(project, job, store):
    if job['action'] != 'assemble' or not 1 <= job['index'] <= len(job['plan']['clips']):
        raise ProjectError('전체 합치기 작업을 확인할 수 없습니다.')
    directory = store.folder(project['id']) / 'jobs' / job['id']
    # Project and job IDs originate in the ledger; still enforce the save boundary.
    directory = directory.resolve()
    if not directory.is_relative_to(store.folder(project['id'])) or directory.parent.name != 'jobs':
        raise ProjectError('합치기 저장 경로가 올바르지 않습니다.')
    paths, counts = [], []
    for index in range(1, job['index'] + 1):
        clip = project['clips'][str(index)]
        path = store.output_file(clip['video'])
        if not path.is_relative_to(store.folder(project['id'])) or not path.is_file():
            raise ProjectError(f'클립 {index}의 저장 영상을 찾을 수 없습니다.')
        paths.append(path)
        counts.append(clip['frames'])
    return concat_files(paths, counts, directory)


def concat_files(paths, frame_counts, directory, *, label='클립'):
    if not paths:
        raise ProjectError('합칠 영상이 없습니다.')
    infos = []
    for index, (path, frames) in enumerate(zip(paths, frame_counts, strict=True), 1):
        info = video_info(path)
        if info['frames'] != frames:
            raise ProjectError(f'{label} {index}의 저장 프레임 수가 기록과 다릅니다.')
        if infos and any(info[key] != infos[0][key] for key in ('fps','codec','width','height','format','time_base','sample_rate','layout')):
            raise ProjectError(f'{label} {index}의 해상도·코덱·FPS·오디오 형식이 달라 재인코딩 없이 합칠 수 없습니다.')
        infos.append(info)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / 'concat.ffconcat'
    # Durations use the already-trimmed MP4 frames, never the latent/context overlap.
    lines = ['ffconcat version 1.0']
    for path, info in zip(paths, infos):
        if '\n' in str(path) or '\r' in str(path):
            raise ProjectError('합치기 파일 경로에는 줄바꿈을 사용할 수 없습니다.')
        lines.extend(["file '" + path.as_posix().replace("'", "'\\''") + "'",
                      f"duration {float(info['frames'] / info['fps']):.12f}"])
    manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    temporary = directory / 'concat.partial.mp4'
    output = directory / 'concat.mp4'
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-copyts',
               '-f', 'concat', '-safe', '0', '-i', str(manifest)]
    first = infos[0]
    if first['sample_rate']:
        filters, labels = [], []
        for index, (path, info) in enumerate(zip(paths, infos), 1):
            command.extend(['-i', str(path)])
            samples = round(info['frames'] / info['fps'] * info['sample_rate'])
            filters.append(f'[{index}:a:0]apad=whole_len={samples},atrim=end_sample={samples},asetpts=N/SR/TB[a{index}]')
            labels.append(f'[a{index}]')
        filters.append(''.join(labels) + f'concat=n={len(paths)}:v=0:a=1[audio]')
        command.extend(['-filter_complex_threads', '2', '-filter_complex', ';'.join(filters),
                        '-map', '0:v:0', '-map', '[audio]', '-c:v', 'copy',
                        '-c:a', 'aac', '-b:a', '256k', '-ar', str(first['sample_rate'])])
    else:
        command.extend(['-map', '0:v:0', '-c:v', 'copy', '-an'])
    command.extend(['-threads', '2', '-avoid_negative_ts', 'disabled', '-map_metadata', '-1', '-movflags', '+faststart', str(temporary)])
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise ProjectError('FFmpeg 합치기에 실패했습니다: ' + result.stderr[-1600:])
        frames = sum(info['frames'] for info in infos)
        merged = video_info(temporary)
        if merged['frames'] != frames or merged['fps'] != first['fps']:
            raise ProjectError('합본의 프레임 수 또는 FPS가 원본 클립과 다릅니다.')
        with av.open(str(temporary)) as container:
            if first['sample_rate']:
                video, audio = container.streams.video[0], container.streams.audio[0]
                if video.duration is None or audio.duration is None:
                    raise ProjectError('합본의 영상·오디오 길이를 확인할 수 없습니다.')
                difference = abs(video.duration * video.time_base - audio.duration * audio.time_base)
                offset = abs((video.start_time or 0) * video.time_base - (audio.start_time or 0) * audio.time_base)
                if difference > 1 / first['fps'] or offset > 1 / first['fps']:
                    raise ProjectError('합본 영상·오디오 길이 차이가 한 프레임보다 큽니다.')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
    print(f'Endless H3 FFmpeg merge: {len(paths)} {label}, {frames} frames; video stream copy; no VAE')
    return output, frames
