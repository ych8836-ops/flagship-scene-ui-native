"""Small, tensor-free project ledger. Successful outputs advance a chain."""
import copy
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path


class ProjectError(ValueError):
    pass


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class ProjectStore:
    def __init__(self, output_root):
        self.output = Path(output_root).resolve()
        self.root = self.output / 'EndlessH3AIO'
        self.lock = threading.RLock()

    def folder(self, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(r'[0-9a-f]{32}', project_id):
            raise ProjectError('프로젝트 식별자가 올바르지 않습니다.')
        path = (self.root / project_id).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ProjectError('프로젝트 경로가 올바르지 않습니다.')
        return path

    def output_file(self, name):
        path = (self.output / name).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ProjectError('저장 경로가 프로젝트 폴더를 벗어났습니다.')
        return path

    def load(self, project_id):
        with self.lock:
            file = self.folder(project_id) / 'project.json'
            if not file.is_file():
                raise ProjectError('저장된 프로젝트가 없습니다. 새 프로젝트를 만들어 주세요.')
            return json.loads(file.read_text('utf-8'))

    def write(self, project):
        project['updated'] = time.time()
        atomic_json(self.folder(project['id']) / 'project.json', project)

    def create(self, name, plan):
        with self.lock:
            if not str(name).strip():
                raise ProjectError('프로젝트 이름을 입력해 주세요.')
            project = dict(id=uuid.uuid4().hex, name=str(name).strip()[:160], created=time.time(),
                           plan=copy.deepcopy(plan), clips={}, jobs={}, active=None, exports=[])
            self.write(project)
            return project

    def list(self):
        result = []
        if not self.root.exists():
            return result
        with self.lock:
            for file in self.root.glob('*/project.json'):
                try:
                    p = self.load(file.parent.name)
                    result.append(dict(id=p['id'], name=p['name'], updated=p['updated'],
                                       completed=self.prefix(p), total=len(p['plan']['clips'])))
                except (OSError, ValueError, KeyError):
                    continue
        return sorted(result, key=lambda p: p['updated'], reverse=True)

    def prefix(self, project):
        i = 0
        while True:
            clip = project['clips'].get(str(i + 1))
            if not clip or clip.get('stale'):
                return i
            if not self.output_file(clip['latent']).is_file() or not self.output_file(clip['video']).is_file():
                return i
            i += 1

    @staticmethod
    def output_records(project):
        for clip in project['clips'].values():
            yield clip
            yield from clip.get('history', [])
        yield from project['exports']

    def manage_outputs(self, project_id, action, job_ids):
        """Recoverable media removal; retain native AV context and revision identities."""
        if action not in ('favorite', 'trash', 'restore'):
            raise ProjectError('알 수 없는 아웃풋 작업입니다.')
        if not isinstance(job_ids, list) or not job_ids or len(job_ids) > 1000 or any(
                not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{32}', key) for key in job_ids):
            raise ProjectError('작업할 아웃풋을 선택해 주세요.')
        with self.lock:
            p = self.load(project_id)
            if p['active'] or p.get('batch', {}).get('state') == 'running':
                raise ProjectError('현재 프로젝트 생성이 끝난 후 아웃풋을 정리해 주세요.')
            records = {item['job']: item for item in self.output_records(p)}
            selected = []
            for key in dict.fromkeys(job_ids):
                item = records.get(key)
                if not item or bool(item.get('gallery_deleted')) != (action == 'restore'):
                    raise ProjectError('선택한 아웃풋이 변경됐습니다. 새로고침 후 다시 선택해 주세요.')
                selected.append(item)
            if action == 'favorite':
                value = not all(item.get('favorite') for item in selected)
                for item in selected:
                    item['favorite'] = value
                self.write(p)
                return p
            folder = self.folder(project_id)
            operations = []
            for item in selected:
                job = item['job']
                source = self.output_file(item['video'])
                original = self.output_file(item.get('original_video', item['video']))
                # Only registered media belonging to this exact project's job may move.
                expected = folder / 'jobs' / job
                trash = (folder / 'trash' / job / original.name).resolve()
                if not original.is_relative_to(expected) or original.parent != expected or not trash.is_relative_to(folder):
                    raise ProjectError('아웃풋 저장 경로가 올바르지 않습니다.')
                if source != (trash if action == 'restore' else original):
                    raise ProjectError('아웃풋 저장 경로가 변경됐습니다.')
                destination = original if action == 'restore' else trash
                if not source.is_file() or destination.exists():
                    raise ProjectError('아웃풋 파일이 없거나 복원 위치에 파일이 이미 있습니다.')
                operations.append((source, destination, item))
            moved = []
            try:
                for source, destination, item in operations:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source.rename(destination)
                    moved.append((source, destination))
                    if action == 'trash':
                        item['original_video'] = item['video']
                        item['gallery_deleted'] = True
                    else:
                        item.pop('original_video', None)
                        item.pop('gallery_deleted', None)
                    item['video'] = destination.relative_to(self.output).as_posix()
                self.write(p)
            except Exception:
                for source, destination in reversed(moved):
                    destination.rename(source)
                raise
            return p

    def start_batch(self, project_id, plan, assemble, process_id, client_id, *, restart_clip=None):
        with self.lock:
            p = self.load(project_id)
            if p['active'] or p.get('batch', {}).get('state') == 'running':
                raise ProjectError('이 프로젝트는 이미 생성 중입니다.')
            prefix = self.prefix(p)
            if len(plan['clips']) < max((int(k) for k in p['clips']), default=0):
                raise ProjectError('이미 생성한 클립을 계획에서 삭제할 수 없습니다.')
            geometry = {k: plan['settings'][k] for k in ('width', 'height', 'context_length', 'audio_file')}
            if p.get('geometry') and geometry != p['geometry']:
                raise ProjectError('시작한 프로젝트의 해상도·연결 길이·립싱크 오디오 파일은 고정입니다.')
            if restart_clip is not None:
                if type(restart_clip) is not int or not 1 <= restart_clip <= min(prefix + 1, len(plan['clips'])):
                    raise ProjectError('재생성 시작 클립보다 앞선 클립을 먼저 완료해 주세요.')
                record = p['clips'].get(str(restart_clip), {})
                if not record.get('video') or not self.output_file(record['video']).is_file():
                    raise ProjectError('이미 생성한 클립에서만 재생성을 시작할 수 있습니다.')
            if restart_clip is None and prefix == len(plan['clips']) and not assemble:
                raise ProjectError('모든 클립이 이미 완료됐습니다. 전체 영상 합치기를 사용하세요.')
            for index in range(restart_clip - 1 if restart_clip else prefix, len(plan['clips'])):
                if not plan['clips'][index]['prompt'].strip():
                    raise ProjectError(f'클립 {index + 1}의 프롬프트가 비어 있습니다.')
            p['plan'] = copy.deepcopy(plan)
            p['batch'] = dict(id=uuid.uuid4().hex, state='running', assemble=assemble,
                              process_id=process_id, client_id=client_id, created=time.time(),
                              start_clip=restart_clip or prefix + 1, total=len(plan['clips']), error=None)
            if restart_clip:
                p['batch']['restart_clip'] = restart_clip
            self.write(p)
            return p

    def update_batch(self, project_id, batch_id, **fields):
        with self.lock:
            p = self.load(project_id)
            if p.get('batch', {}).get('id') != batch_id:
                raise ProjectError('전체 생성 작업 기록이 다릅니다.')
            p['batch'].update(fields)
            self.write(p)
            return p

    def schedule_next(self, project_id, plan, process_id, client_id):
        """Reserve one successor, anchored to the currently running clip's successful save."""
        with self.lock:
            p = self.load(project_id)
            if p.get('batch', {}).get('state') == 'running':
                raise ProjectError('이미 전체 생성 또는 다음 클립 예약이 진행 중입니다.')
            job = p['jobs'].get(p['active'])
            if not job or job['action'] == 'assemble':
                raise ProjectError('클립 생성 중에 다음 클립을 예약해 주세요.')
            index = job['index'] + 1
            if index > len(plan['clips']):
                raise ProjectError('다음 클립 계획이 없습니다. 생성 전에 클립을 추가해 주세요.')
            # Do not replace the active job's plan, even if another tab sends an edit.
            if plan != p['plan']:
                raise ProjectError('생성 중인 계획이 변경됐습니다. 현재 작업이 끝난 후 다시 시도해 주세요.')
            if not plan['clips'][index - 1]['prompt'].strip():
                raise ProjectError(f'클립 {index}의 프롬프트가 비어 있습니다.')
            p['batch'] = dict(id=uuid.uuid4().hex, kind='scheduled_clip', state='running',
                assemble=False, process_id=process_id, client_id=client_id, created=time.time(),
                wait_job=job['id'], target_clip=index, start_clip=index, total=index, error=None)
            self.write(p)
            return p

    def cancel_scheduled(self, project_id):
        """Cancel only the waiting successor; leave its predecessor untouched."""
        with self.lock:
            p = self.load(project_id)
            batch = p.get('batch', {})
            if batch.get('kind') != 'scheduled_clip' or batch.get('state') != 'running':
                raise ProjectError('대기 중인 다음 클립 예약이 없습니다.')
            active = p['jobs'].get(p['active'])
            if active and active.get('batch_id') == batch['id']:
                raise ProjectError('예약 클립이 이미 시작됐습니다. 중지 버튼을 사용해 주세요.')
            batch.update(state='cancelled', finished=time.time(), error='다음 클립 예약을 취소했습니다.')
            self.write(p)
            return p

    def reserve(self, project_id, plan, action, index=None, *, batch_id=None):
        with self.lock:
            p = self.load(project_id)
            batch = p.get('batch', {})
            if batch_id:
                if batch.get('id') != batch_id or batch.get('state') != 'running':
                    raise ProjectError('전체 생성이 중지됐습니다.')
            elif batch.get('state') == 'running':
                raise ProjectError('전체 생성 중에는 개별 작업을 실행할 수 없습니다.')
            if p['active']:
                raise ProjectError('이 프로젝트는 이미 생성 중입니다. 완료 후 다시 눌러 주세요.')
            prefix = self.prefix(p)
            if len(plan['clips']) < max((int(k) for k in p['clips']), default=0):
                raise ProjectError('이미 생성한 클립을 계획에서 삭제할 수 없습니다.')
            if action == 'next':
                index = prefix + 1
                if index > len(plan['clips']):
                    raise ProjectError('모든 클립이 완료됐습니다. + 클립 추가로 다음 프롬프트를 입력해 주세요.')
            elif action == 'retry':
                index = int(index or 0)
                if not (1 <= index <= len(plan['clips'])):
                    raise ProjectError('다시 생성할 클립을 선택해 주세요.')
                if index > prefix + 1:
                    raise ProjectError('선택한 클립보다 앞선 클립을 먼저 생성해 주세요.')
            elif action == 'assemble':
                if prefix < 1 or prefix != len(plan['clips']):
                    raise ProjectError('모든 클립을 생성한 후 합칠 수 있습니다. 누락 또는 재생성 필요 클립을 확인해 주세요.')
                index = prefix
            else:
                raise ProjectError('알 수 없는 작업입니다.')
            # Native latent context cannot change its spatial grid halfway through a run.
            geometry = {k: plan['settings'][k] for k in ('width', 'height', 'context_length', 'audio_file')}
            if p.get('geometry') and geometry != p['geometry']:
                raise ProjectError('시작한 프로젝트의 해상도·연결 길이·립싱크 오디오 파일은 고정입니다. 다른 설정은 새 프로젝트에서 사용해 주세요.')
            if action != 'assemble' and not plan['clips'][index - 1]['prompt'].strip():
                raise ProjectError(f'클립 {index}의 프롬프트가 비어 있습니다.')
            job_id = uuid.uuid4().hex
            job = dict(id=job_id, project_id=project_id, action=action, index=index,
                       state='preparing', created=time.time(), prompt_id=None, error=None,
                       plan=copy.deepcopy(plan), geometry=geometry)
            if batch_id:
                job['batch_id'] = batch_id
            p['plan'] = copy.deepcopy(plan)
            p['active'] = job_id
            p['jobs'][job_id] = job
            self.write(p)
            return p, copy.deepcopy(job)

    def reserve_output_upscale(self, project_id, source_job, settings):
        """Reserve a new export from stored media without editing the clip plan."""
        with self.lock:
            p = self.load(project_id)
            if p['active'] or p.get('batch', {}).get('state') == 'running':
                raise ProjectError('선택한 프로젝트 생성이 끝난 후 업스케일해 주세요.')
            source = next((item for item in p['exports'] if item['job'] == source_job), None)
            if not source or source.get('gallery_deleted'):
                raise ProjectError('아웃풋 갤러리에서 전체 합본 한 개를 선택해 주세요.')
            path = self.output_file(source['video'])
            if not path.is_relative_to(self.folder(project_id)) or not path.is_file() or not path.stat().st_size:
                raise ProjectError('선택한 전체 합본 파일을 찾을 수 없습니다.')
            job_id = uuid.uuid4().hex
            job = dict(id=job_id, project_id=project_id, action='upscale', index=0,
                       state='preparing', created=time.time(), prompt_id=None, error=None,
                       plan={'settings': copy.deepcopy(settings)},
                       source_video=source['video'], source_job=source_job,
                       source_revisions=copy.deepcopy(source['revisions']))
            p['active'] = job_id
            p['jobs'][job_id] = job
            self.write(p)
            return p, copy.deepcopy(job)

    def update_job(self, project_id, job_id, **fields):
        with self.lock:
            p = self.load(project_id)
            job = p['jobs'].get(job_id)
            if not job:
                raise ProjectError('작업 기록을 찾을 수 없습니다.')
            if job['state'] == 'completed':
                return p
            job.update(fields)
            if job['state'] in ('failed', 'cancelled') and p['active'] == job_id:
                p['active'] = None
            self.write(p)
            return p

    def commit(self, project_id, job_id, latent_path, video_path, frames):
        from .sequence_plan import continues_clip
        with self.lock:
            p = self.load(project_id)
            job = p['jobs'].get(job_id)
            if not job:
                raise ProjectError('작업 기록을 찾을 수 없습니다.')
            if job['state'] == 'completed':
                return p
            if p['active'] != job_id or job['state'] not in ('queued', 'running'):
                raise ProjectError('현재 진행 중인 작업과 저장 결과가 다릅니다.')
            expected_folder = self.folder(project_id) / 'jobs' / job_id
            video = self.output_file(video_path)
            if not video.is_relative_to(expected_folder) or not video.is_file() or not video.stat().st_size:
                raise ProjectError('영상 저장이 완료되지 않았습니다. 클립 번호는 유지됩니다.')
            if job['action'] == 'upscale':
                p['exports'].append(dict(video=video_path, job=job_id, created=time.time(), frames=frames,
                    revisions=copy.deepcopy(job['source_revisions']), upscaled=True,
                    scale=job['plan']['settings']['scale'], source_job=job['source_job'],
                    source_video=job['source_video']))
            elif job['action'] == 'assemble':
                p['exports'].append(dict(video=video_path, job=job_id, created=time.time(),
                                         frames=frames, revisions={k: v['job'] for k, v in p['clips'].items()}))
            else:
                latent = self.output_file(latent_path)
                if not latent.is_relative_to(expected_folder) or not latent.is_file() or not latent.stat().st_size:
                    raise ProjectError('다음 클립의 연결 데이터가 저장되지 않았습니다.')
                index = job['index']
                previous = p['clips'].get(str(index))
                history = list(previous.get('history', [])) if previous else []
                if previous:
                    history.append({k: v for k, v in previous.items() if k != 'history'})
                p['clips'][str(index)] = dict(index=index, job=job_id, latent=latent_path,
                    video=video_path, frames=frames, stale=False, history=history,
                    prompt=job['plan']['clips'][index - 1]['prompt'], created=time.time())
                for key in sorted(p['clips'], key=int):
                    if int(key) > index:
                        if not continues_clip(job['plan'], int(key)):
                            break
                        p['clips'][key]['stale'] = True
                p['geometry'] = job['geometry']
            job['state'] = 'completed'
            job['finished'] = time.time()
            p['active'] = None
            self.write(p)
            return p

    def assembly_folder(self, project, job):
        folder = self.folder(project['id']) / 'jobs' / job['id'] / 'assembly_latents'
        folder.mkdir(parents=True, exist_ok=False)
        # Links consume no second copy of the AV archive; source revisions remain intact.
        for index in range(1, job['index'] + 1):
            source = self.output_file(project['clips'][str(index)]['latent'])
            os.link(source, folder / f'clip_{index:05d}.safetensors')
        return folder
