"""Endless H3 project UI, using native Comfy execution and existing v1.5 nodes."""
import asyncio
import copy
import json
import os
import time
import uuid
from pathlib import Path

from aiohttp import web
import execution
import folder_paths
import nodes
from server import PromptServer

from .project_store import ProjectStore, ProjectError
from .media_concat import concat_clips
from .scene_assembly import stitch_scene, concat_scenes
from .prompt_builder import DEFAULTS, default_plan, normalize_plan, build_prompt, frame_count
from .prompt_builder import normalize_upscale_settings, build_output_upscale_prompt, clip_frame_count
from .sequence_plan import continues_clip, overlap_frames

STORE = ProjectStore(folder_paths.get_output_directory())
ROUTES = PromptServer.instance.routes
PROCESS_ID = uuid.uuid4().hex
BATCH_TASKS = set()


def public_project(p):
    result = copy.deepcopy(p)
    result['next_clip'] = STORE.prefix(p) + 1
    # Old job plans can be large; the UI needs only lightweight job status.
    result['jobs'] = {key: {k: v for k, v in job.items() if k not in ('plan', 'geometry')}
                      for key, job in p['jobs'].items()}
    for clip in result['clips'].values():
        clip['missing'] = not (STORE.output_file(clip['latent']).is_file() and STORE.output_file(clip['video']).is_file())
    for export in result['exports']:
        export['outdated'] = (len(export['revisions']) != len(p['plan']['clips']) or
            any(p['clips'].get(key, {}).get('job') != revision for key, revision in export['revisions'].items()))
    return result


def reconcile(project_id):
    p = STORE.load(project_id)
    batch = p.get('batch', {})
    if batch.get('state') == 'running' and batch.get('process_id') != PROCESS_ID:
        p = STORE.update_batch(project_id, batch['id'], state='cancelled', finished=time.time(),
                               error='서버가 재시작되어 전체 생성이 중지됐습니다. 버튼을 다시 누르면 남은 클립부터 시작합니다.')
    if not p['active']:
        return p
    job = p['jobs'][p['active']]
    pid = job.get('prompt_id')
    server = PromptServer.instance
    running, pending = server.prompt_queue.get_current_queue()
    if pid and any(q[1] == pid for q in running + pending):
        state = 'running' if any(q[1] == pid for q in running) else 'queued'
        if job['state'] != state:
            return STORE.update_job(project_id, job['id'], state=state)
        return p
    history = server.prompt_queue.get_history(prompt_id=pid) if pid else {}
    if pid in history:
        entry = history[pid]
        status = entry.get('status') or {}
        messages = status.get('messages', [])
        errors = [m[1].get('exception_message', m[1].get('exception_type', '생성이 중단됐습니다.'))
                  for m in messages if m[0] in ('execution_error', 'execution_interrupted')]
        error = errors[-1] if errors else '저장 완료 확인이 없어 클립 번호를 유지했습니다.'
        return STORE.update_job(project_id, job['id'], state='failed', error=error, finished=time.time())
    # Validation may yield while a second browser polls; do not release its live reservation.
    if job['state'] == 'preparing' and job.get('process_id') == PROCESS_ID and time.time() - job['created'] < 180:
        return p
    return STORE.update_job(project_id, job['id'], state='cancelled',
                            error='이전 대기 작업이 취소됐거나 서버가 재시작됐습니다. 같은 클립을 다시 생성해 주세요.')


def check_assets(plan, index, action):
    if action == 'assemble' and not plan.get('sequence_mode'):
        return
    s = plan['settings']
    types = [('vae', s['video_vae'])]
    if action != 'assemble' or not s['audio_file']:
        types.append(('vae', s['audio_vae']))
    if action != 'assemble':
        types[:0] = [('diffusion_models', s['model']), ('text_encoders', s['clip'])]
    if action != 'assemble':
        if s['turbo_lora']:
            types.append(('loras', s['turbo_lora']))
        if (plan['clips'][index - 1]['mode'] == 'R2V' or plan['clips'][index - 1].get('background_refresh')) and s['reference_lora']:
            types.append(('loras', s['reference_lora']))
        types.extend(('loras', l['name']) for l in s['loras'] if l.get('enabled', True) and l['name'])
    for kind, name in types:
        allowed = folder_paths.get_filename_list(kind)
        if not isinstance(name, str) or name not in allowed or not folder_paths.get_full_path(kind, name):
            raise ProjectError(f'설치된 {kind} 파일을 선택해 주세요: {name}')
    import comfy.samplers
    if action != 'assemble' and (s['sampler'] not in comfy.samplers.KSampler.SAMPLERS or s['scheduler'] not in comfy.samplers.KSampler.SCHEDULERS):
        raise ProjectError('설치된 샘플러와 스케줄러를 선택해 주세요.')
    files = []
    if action != 'assemble':
        c = plan['clips'][index - 1]
        if c['mode'] == 'I2V' and not continues_clip(plan, index):
            files.append(c['first_image'])
        if c['last_image']:
            files.append(c['last_image'])
        if c.get('background_refresh'):
            if c['background_source'] == 'image':
                files.append(c['background_image'])
            if c['mode'] != 'R2V' and c['first_image']:
                files.append(c['first_image'])
        if c['mode'] == 'R2V':
            videos = [v for v in c.get('videos', []) if v['name']]
            if not c.get('background_refresh') and not c.get('use_common_references') and not any(c['images']) and not videos and not any(c.get('audios', [])):
                raise ProjectError('R2V 참고 이미지·비디오·오디오 중 하나 이상 선택해 주세요.')
            files.extend(i for i in c['images'] if i)
            files.extend(v['name'] for v in videos)
            files.extend(a for a in c.get('audios', []) if a)
            if videos and 'VHS_LoadVideoFFmpeg' not in nodes.NODE_CLASS_MAPPINGS:
                raise ProjectError('비디오 참고에는 설치된 VideoHelperSuite의 Load Video FFmpeg 노드가 필요합니다.')
    if s['audio_file']:
        files.append(s['audio_file'])
    root = Path(folder_paths.get_input_directory()).resolve()
    for name in files:
        path = (root / name).resolve()
        if not name or not path.is_relative_to(root) or not path.is_file():
            raise ProjectError(f'ComfyUI 입력 폴더의 파일을 선택하거나 업로드해 주세요: {name}')
    if action != 'assemble' and c['mode'] == 'R2V':
        import av
        for reference in c.get('videos', []):
            if not reference['name']:
                continue
            with av.open(str(root / reference['name'])) as container:
                if not container.streams.video:
                    raise ProjectError(f'참고 파일에 비디오가 없습니다: {reference["name"]}')
                if reference['use_audio'] and not container.streams.audio:
                    raise ProjectError(f'이 비디오는 소리가 없습니다. 소리 참고를 OFF로 바꿔 주세요: {reference["name"]}')


def check_audio_duration(project, job):
    if job['action'] == 'assemble' and not job['plan'].get('sequence_mode'):
        return
    s = job['plan']['settings']
    if not s['audio_file']:
        return
    import av
    index = job['index']
    if job['action'] == 'assemble':
        frames = sum(project['clips'][str(i)]['frames'] for i in range(1, index + 1))
        offset_frames = 0
    else:
        frames = clip_frame_count(job['plan'], index)
        offset_frames = max(0, sum(project['clips'][str(i)]['frames'] for i in range(1, index))
                            - overlap_frames(job['plan'], index))
    file = Path(folder_paths.get_input_directory()) / s['audio_file']
    with av.open(str(file)) as container:
        stream = next(iter(container.streams.audio), None)
        if stream is None:
            raise ProjectError('선택한 파일에 오디오가 없습니다.')
        duration = float(stream.duration * stream.time_base) if stream.duration is not None else (
            container.duration / av.time_base if container.duration is not None else None)
    if duration is None:
        raise ProjectError('오디오 길이를 읽을 수 없습니다. WAV 또는 MP3 파일로 다시 업로드해 주세요.')
    if duration + .05 < (offset_frames + frames) / 24:
        raise ProjectError(f'클립 {index}까지 연결하려면 오디오가 {(offset_frames + frames) / 24:.2f}초 이상 필요합니다. 현재 {duration:.2f}초입니다.')


def error_response(error, status=400):
    return web.json_response({'error': str(error)}, status=status)


@ROUTES.get('/endless_h3_aio/config')
async def config_route(request):
    input_files = [p.relative_to(folder_paths.get_input_directory()).as_posix()
                   for p in Path(folder_paths.get_input_directory()).rglob('*') if p.is_file()]
    return web.json_response(dict(sequence_mode_supported=True, clip_refiner_per_clip_only=True, clip_refiner_supported=True, background_refresh_supported=True, output_upscale_supported=True, output_tools_supported=True, asset_refresh_supported=True, scheduled_clip_supported=True, default_plan=default_plan(), projects=STORE.list(), models={
        key: folder_paths.get_filename_list(kind) for key, kind in (
            ('model', 'diffusion_models'), ('clip', 'text_encoders'), ('vae', 'vae'), ('loras', 'loras'))},
        images=folder_paths.filter_files_content_types(input_files, ['image']),
        videos=folder_paths.filter_files_content_types(input_files, ['video']),
        audio_files=folder_paths.filter_files_content_types(input_files, ['audio']),
        samplers=list(__import__('comfy.samplers', fromlist=['KSampler']).KSampler.SAMPLERS),
        schedulers=list(__import__('comfy.samplers', fromlist=['KSampler']).KSampler.SCHEDULERS),
        dependencies={name: name in nodes.NODE_CLASS_MAPPINGS for name in (
            'EndlessV15MiniMaxH3MotionContext', 'H3ClipRefiner -noEmbryo',
            'H3MotionContextClipStitcher -noEmbryo', 'MiniMaxH3MemoryEfficientSageAttentionPatch',
            'MiniMaxChunkFeedForward', 'RTXVideoVSRRestore', 'PathchSageAttentionKJ',
            'ModelAttentionBackend', 'ModelPatchTorchSettings', 'EasyCache', 'SpectrumApplyMiniMaxH3')}))


@ROUTES.get('/endless_h3_aio/projects')
async def projects_route(request):
    return web.json_response({'projects': STORE.list()})


@ROUTES.post('/endless_h3_aio/assets_refresh')
async def assets_refresh_route(request):
    try:
        data = await request.json()
        scope = data.get('scope')
        if scope not in ('models', 'loras'):
            raise ProjectError('모델 또는 LoRA 새로고침을 선택해 주세요.')
        kinds = [('model', 'diffusion_models'), ('clip', 'text_encoders'), ('vae', 'vae'), ('loras', 'loras')]
        def scan():
            result = {}
            for key, kind in kinds:
                if scope == 'loras' and key != 'loras':
                    continue
                fresh = folder_paths.get_filename_list_(kind)
                folder_paths.filename_list_cache[kind] = fresh
                folder_paths.cache_helper.set(kind, fresh)
                result[key] = list(fresh[0])
            return result
        return web.json_response({'models': await asyncio.to_thread(scan)})
    except (ProjectError, OSError, TypeError, KeyError, json.JSONDecodeError) as error:
        return error_response(error)


@ROUTES.post('/endless_h3_aio/outputs')
async def outputs_route(request):
    try:
        data = await request.json()
        return web.json_response(public_project(STORE.manage_outputs(
            data['project_id'], data['action'], data.get('jobs'))))
    except (ProjectError, OSError, TypeError, KeyError, json.JSONDecodeError) as error:
        return error_response(error)


@ROUTES.post('/endless_h3_aio/storage')
async def storage_route(request):
    try:
        data = await request.json()
        p = STORE.load(data['project_id'])
        folder = STORE.folder(p['id'])
        if os.name != 'nt':
            raise ProjectError('이 서버에서는 폴더 자동 열기를 지원하지 않습니다.')
        await asyncio.to_thread(os.startfile, str(folder))
        return web.json_response({'opened': True})
    except (ProjectError, OSError, TypeError, KeyError, json.JSONDecodeError) as error:
        return error_response(error)


@ROUTES.get('/endless_h3_aio/project/{project_id}')
async def project_route(request):
    try:
        return web.json_response(public_project(reconcile(request.match_info['project_id'])))
    except (ProjectError, OSError, KeyError) as error:
        return error_response(error)


@ROUTES.post('/endless_h3_aio/cancel')
async def cancel_route(request):
    try:
        data = await request.json()
        p = reconcile(data['project_id'])
        batch = p.get('batch', {})
        stopped_batch = batch.get('state') == 'running'
        if stopped_batch:
            p = STORE.update_batch(p['id'], batch['id'], state='cancelled', finished=time.time(),
                                   error='전체 생성을 중지했습니다.')
        if not p['active']:
            return web.json_response(public_project(p))
        job = p['jobs'][p['active']]
        pid = job.get('prompt_id')
        if not pid:
            if stopped_batch:
                return web.json_response(public_project(p))
            raise ProjectError('생성 구성을 준비 중입니다. 잠시 후 다시 눌러 주세요.')
        queue = PromptServer.instance.prompt_queue
        removed = queue.delete_queue_item(lambda item: item[1] == pid)
        if removed:
            p = STORE.update_job(p['id'], job['id'], state='cancelled', error='대기 중인 작업을 취소했습니다.')
        else:
            # Native atomic prompt-id cancellation cannot interrupt a different user's job.
            queue.interrupt_if_running(pid)
        return web.json_response(public_project(p))
    except (ProjectError, TypeError, KeyError, json.JSONDecodeError) as error:
        return error_response(error)


@ROUTES.post('/endless_h3_aio/project')
async def create_route(request):
    try:
        data = await request.json()
        plan = normalize_plan(data.get('plan', default_plan()))
        return web.json_response(public_project(STORE.create(data.get('name', ''), plan)))
    except (ProjectError, TypeError, KeyError, json.JSONDecodeError) as error:
        return error_response(error)


@ROUTES.post('/endless_h3_aio/validate_plan')
async def validate_plan_route(request):
    try:
        return web.json_response(normalize_plan(await request.json()))
    except (ProjectError, TypeError, KeyError, json.JSONDecodeError) as error:
        return error_response(error)


@ROUTES.post('/endless_h3_aio/plan')
async def save_plan_route(request):
    try:
        data = await request.json()
        plan = normalize_plan(data['plan'])
        with STORE.lock:
            p = STORE.load(data['project_id'])
            if p['active'] or p.get('batch', {}).get('state') == 'running':
                raise ProjectError('생성 중에는 저장 계획을 변경할 수 없습니다. 완료 후 저장해 주세요.')
            if len(plan['clips']) < max((int(k) for k in p['clips']), default=0):
                raise ProjectError('이미 생성한 클립을 목록에서 삭제할 수 없습니다.')
            p['plan'] = plan
            STORE.write(p)
        return web.json_response(public_project(p))
    except (ProjectError, TypeError, KeyError, json.JSONDecodeError) as error:
        return error_response(error)


@ROUTES.post('/endless_h3_aio/node_graph')
async def node_graph_route(request):
    try:
        data = await request.json()
        plan = normalize_plan(data['plan'])
        index = data.get('index', 1)
        if type(index) is not int or not 1 <= index <= len(plan['clips']):
            raise ProjectError('노드로 볼 클립을 선택해 주세요.')
        project = STORE.load(data['project_id']) if data.get('project_id') else {'id': '0' * 32, 'clips': {}}
        project = copy.deepcopy(project)
        warnings = []
        for previous in range(1, index):
            record = project['clips'].get(str(previous))
            if not record or not STORE.output_file(record['latent']).is_file():
                project['clips'][str(previous)] = dict(
                    latent=f'EndlessH3AIO/{project["id"]}/node_view/clip_{previous:05d}.safetensors',
                    frames=clip_frame_count(plan, previous) - overlap_frames(plan, previous))
                if previous in (1, index - 1):
                    warnings.append(f'클립 {previous} 연결 파일이 없습니다. 노드에서 실행하려면 이전 클립 파일을 연결하세요.')
            elif record.get('stale') and previous in (1, index - 1):
                warnings.append(f'클립 {previous}는 재생성이 필요한 이전 결과입니다.')
        clip = plan['clips'][index - 1]
        if clip['mode'] == 'I2V' and not continues_clip(plan, index) and not clip['first_image']:
            warnings.append('첫 클립 시작 이미지를 선택하세요.')
        if clip['mode'] == 'R2V' and not any(clip['images']) and not any(v['name'] for v in clip['videos']) and not any(clip['audios']):
            warnings.append('R2V 참고 이미지·비디오·오디오를 연결하세요.')
        if not clip['prompt'].strip():
            warnings.append('클립 프롬프트가 비어 있습니다.')
        job = dict(id='node_view_' + uuid.uuid4().hex, action='retry', index=index, plan=plan)
        prompt = build_prompt(project, job, STORE, preview=True)
        return web.json_response(dict(prompt=prompt, index=index, warnings=warnings))
    except (ProjectError, TypeError, KeyError, OSError, json.JSONDecodeError) as error:
        return error_response(error)


async def enqueue_job(project_id, plan, action, index=None, client_id=None, *, batch_id=None, source_job=None):
    job = None
    try:
        reconcile(project_id)
        if action == 'upscale':
            if 'RTXVideoVSRRestore' not in nodes.NODE_CLASS_MAPPINGS:
                raise ProjectError('SRFPTyp 비디오 업스케일러를 설치해 주세요.')
            project, job = STORE.reserve_output_upscale(project_id, source_job, normalize_upscale_settings(plan))
        else:
            project, job = STORE.reserve(project_id, plan, action, index, batch_id=batch_id)
        STORE.update_job(project_id, job['id'], process_id=PROCESS_ID)
        if action == 'upscale':
            prompt = await asyncio.to_thread(build_output_upscale_prompt, project, job, STORE)
        else:
            check_assets(plan, job['index'], job['action'])
            await asyncio.to_thread(check_audio_duration, project, job)
            prompt = await asyncio.to_thread(build_prompt, project, job, STORE)
        server = PromptServer.instance
        pid = str(uuid.uuid4())
        json_data = server.trigger_on_prompt(dict(prompt=prompt, client_id=client_id, prompt_id=pid))
        prompt = json_data['prompt']
        server.node_replace_manager.apply_replacements(prompt)
        valid = await execution.validate_prompt(pid, prompt, None)
        if not valid[0]:
            raise ProjectError('생성 구성을 확인해 주세요: ' + json.dumps(valid[3] or valid[1], ensure_ascii=False))
        extra = dict(client_id=client_id, create_time=int(time.time() * 1000),
                     endless_h3_project=project_id, endless_h3_job=job['id'])
        with STORE.lock:
            current = STORE.load(project_id)
            if batch_id and (current.get('batch', {}).get('id') != batch_id or
                             current['batch']['state'] != 'running'):
                raise ProjectError('전체 생성이 중지됐습니다.')
            if current['active'] != job['id']:
                raise ProjectError('대기 등록 전에 작업이 중지됐습니다.')
            number = server.number
            server.number += 1
            STORE.update_job(project_id, job['id'], state='queued', prompt_id=pid)
            server.prompt_queue.put((number, pid, prompt, extra, valid[2], {}))
        return dict(prompt_id=pid, job_id=job['id'], project=public_project(STORE.load(project_id)))
    except Exception as error:
        if job:
            p = STORE.load(project_id)
            cancelled = batch_id and p.get('batch', {}).get('state') == 'cancelled'
            STORE.update_job(project_id, job['id'], state='cancelled' if cancelled else 'failed',
                             error=str(error), finished=time.time())
        raise


@ROUTES.post('/endless_h3_aio/queue')
async def queue_route(request):
    try:
        data = await request.json()
        result = await enqueue_job(data['project_id'], normalize_plan(data['plan']), data['action'],
                                   data.get('index'), data.get('client_id'))
        return web.json_response(result)
    except Exception as error:
        return error_response(error)


@ROUTES.post('/endless_h3_aio/upscale_output')
async def upscale_output_route(request):
    try:
        data = await request.json()
        result = await enqueue_job(data['project_id'], data.get('settings', {}), 'upscale',
                                   client_id=data.get('client_id'), source_job=data['source_job'])
        return web.json_response(result)
    except Exception as error:
        return error_response(error)


async def run_batch(project_id, batch_id):
    try:
        while True:
            p = reconcile(project_id)
            batch = p.get('batch', {})
            if batch.get('id') != batch_id or batch.get('state') != 'running':
                return
            scheduled = batch.get('kind') == 'scheduled_clip'
            if scheduled:
                predecessor = p['jobs'][batch['wait_job']]
                if predecessor['state'] in ('failed', 'cancelled'):
                    raise ProjectError('앞 클립이 완료되지 않아 다음 예약을 중단했습니다. ' + (predecessor.get('error') or ''))
                if predecessor['state'] != 'completed':
                    await asyncio.sleep(.5)
                    continue
            remaining = STORE.prefix(p) < len(p['plan']['clips'])
            restart = batch.get('restart_clip') if not batch.get('restart_started') else None
            if not scheduled and not restart and not remaining and not batch['assemble']:
                STORE.update_batch(project_id, batch_id, state='completed', finished=time.time())
                return
            action = 'retry' if scheduled or restart else ('next' if remaining else 'assemble')
            result = await enqueue_job(project_id, p['plan'], action,
                index=batch.get('target_clip') if scheduled else restart,
                client_id=batch.get('client_id'), batch_id=batch_id)
            if restart:
                STORE.update_batch(project_id, batch_id, restart_started=True)
            while True:
                p = reconcile(project_id)
                if p.get('batch', {}).get('id') != batch_id or p['batch']['state'] != 'running':
                    return
                job = p['jobs'][result['job_id']]
                if job['state'] == 'completed':
                    break
                if job['state'] in ('failed', 'cancelled'):
                    raise ProjectError(job.get('error') or '전체 생성 중 작업이 중단됐습니다.')
                await asyncio.sleep(.5)
            if scheduled or action == 'assemble':
                STORE.update_batch(project_id, batch_id, state='completed', finished=time.time())
                return
    except asyncio.CancelledError:
        p = STORE.load(project_id)
        if p.get('batch', {}).get('id') == batch_id and p['batch']['state'] == 'running':
            STORE.update_batch(project_id, batch_id, state='cancelled', finished=time.time(),
                               error='서버가 종료되어 전체 생성이 중지됐습니다.')
        raise
    except Exception as error:
        p = STORE.load(project_id)
        if p.get('batch', {}).get('id') == batch_id and p['batch']['state'] == 'running':
            STORE.update_batch(project_id, batch_id, state='failed', error=str(error), finished=time.time())


@ROUTES.post('/endless_h3_aio/batch')
async def batch_route(request):
    try:
        data = await request.json()
        if type(data.get('assemble', False)) is not bool:
            raise ProjectError('전체 생성 후 합치기는 ON/OFF로 선택해 주세요.')
        plan = normalize_plan(data['plan'])
        reconcile(data['project_id'])
        p = STORE.start_batch(data['project_id'], plan, data.get('assemble', False), PROCESS_ID, data.get('client_id'), restart_clip=data.get('restart_clip'))
        task = asyncio.create_task(run_batch(p['id'], p['batch']['id']))
        BATCH_TASKS.add(task)
        task.add_done_callback(BATCH_TASKS.discard)
        return web.json_response(dict(project=public_project(p)))
    except (ProjectError, TypeError, KeyError, OSError, json.JSONDecodeError) as error:
        return error_response(error)


@ROUTES.post('/endless_h3_aio/schedule')
async def schedule_route(request):
    try:
        data = await request.json()
        if type(data.get('enabled', True)) is not bool:
            raise ProjectError('다음 예약 생성은 ON/OFF로 선택해 주세요.')
        p = reconcile(data['project_id'])
        if not data.get('enabled', True):
            return web.json_response(dict(project=public_project(STORE.cancel_scheduled(p['id']))))
        plan = normalize_plan(data['plan'])
        active = p['jobs'].get(p['active'])
        if not active or active['action'] in ('assemble', 'upscale'):
            raise ProjectError('클립 생성 중에 다음 클립을 예약해 주세요.')
        index = active['index'] + 1
        if index > len(plan['clips']):
            raise ProjectError('다음 클립 계획이 없습니다.')
        check_assets(plan, index, 'retry')
        p = STORE.schedule_next(p['id'], plan, PROCESS_ID, data.get('client_id'))
        task = asyncio.create_task(run_batch(p['id'], p['batch']['id']))
        BATCH_TASKS.add(task)
        task.add_done_callback(BATCH_TASKS.discard)
        return web.json_response(dict(project=public_project(p)))
    except (ProjectError, TypeError, KeyError, OSError, json.JSONDecodeError) as error:
        return error_response(error)


class EndlessH3AllInOne:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'project_config': ('STRING', {'default': '{}', 'multiline': True})}}

    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('project_report',)
    FUNCTION = 'inspect'
    CATEGORY = 'MiniMax H3/flgaship h3 Studio'
    OUTPUT_NODE = True

    def inspect(self, project_config):
        config = json.loads(project_config)
        plan = normalize_plan(config.get('plan', default_plan()))
        name = config.get('name', '새 프로젝트')
        report = f'{name} · {len(plan["clips"])}개 클립 계획. 노드 안의 다음 클립 생성 버튼을 눌러 주세요.'
        return {'ui': {'text': [report]}, 'result': (report,)}


class EndlessH3BackgroundFrame:
    """Read one reference frame, not an entire clip or its soundtrack."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'video_path': ('STRING',), 'seconds': ('FLOAT', {'default': 0.0, 'min': 0.0, 'max': 15.0})}}

    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'frame'
    CATEGORY = 'MiniMax H3/flgaship h3 Studio/internal'

    @classmethod
    def VALIDATE_INPUTS(cls, video_path, seconds):
        try:
            path = STORE.output_file(video_path)
            if not path.is_file():
                return '배경 참고로 사용할 첫 클립 영상이 없습니다.'
            if not 0 <= seconds <= 15:
                return '배경 참고 시점이 올바르지 않습니다.'
            return True
        except (ProjectError, TypeError):
            return '배경 참고 영상은 스튜디오 저장 폴더 안에 있어야 합니다.'

    @classmethod
    def IS_CHANGED(cls, video_path, seconds):
        stat = STORE.output_file(video_path).stat()
        return (stat.st_mtime_ns, stat.st_size, seconds)

    def frame(self, video_path, seconds):
        import av
        import torch
        if type(seconds) not in (int, float) or not __import__('math').isfinite(seconds) or not 0 <= seconds <= 15:
            raise ProjectError('배경 참고 시점이 올바르지 않습니다.')
        with av.open(str(STORE.output_file(video_path))) as container:
            stream = next(iter(container.streams.video), None)
            if stream is None:
                raise ProjectError('첫 클립에 영상 스트림이 없습니다.')
            stream.thread_type = 'SLICE'
            origin = stream.start_time or 0
            target = origin + int(seconds / stream.time_base)
            if stream.duration is not None and target >= origin + stream.duration:
                raise ProjectError('참고 시점이 첫 클립 길이를 넘습니다. 더 이른 시점을 선택해 주세요.')
            container.seek(target, stream=stream, backward=True, any_frame=False)
            for frame in container.decode(stream):
                if frame.pts is not None and frame.pts < target:
                    continue
                pixels = frame.to_ndarray(format='rgb24')
                return (torch.from_numpy(pixels).to(dtype=torch.float32).div_(255.0).unsqueeze(0),)
        raise ProjectError('선택한 시점의 첫 클립 화면을 읽지 못했습니다.')


class EndlessH3OutputVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'video_path': ('STRING',)}}

    RETURN_TYPES = ('VIDEO', 'INT')
    FUNCTION = 'load'
    CATEGORY = 'MiniMax H3/flgaship h3 Studio/internal'

    @classmethod
    def VALIDATE_INPUTS(cls, video_path):
        try:
            return True if STORE.output_file(video_path).is_file() else '합본 영상 파일이 없습니다.'
        except (ProjectError, TypeError):
            return '스튜디오 아웃풋 폴더 안의 영상을 선택해 주세요.'

    @classmethod
    def IS_CHANGED(cls, video_path):
        stat = STORE.output_file(video_path).stat()
        return (stat.st_mtime_ns, stat.st_size)

    def load(self, video_path):
        import av
        from comfy_api.latest import InputImpl
        path = STORE.output_file(video_path)
        with av.open(str(path)) as container:
            stream = next(iter(container.streams.video), None)
            if stream is None:
                raise ProjectError('선택한 합본에 영상 스트림이 없습니다.')
            frames = stream.frames
            if not frames and stream.duration and stream.average_rate:
                frames = round(float(stream.duration * stream.time_base * stream.average_rate))
            if not frames or frames > 36000000:
                raise ProjectError('합본 영상의 프레임 수를 확인할 수 없습니다.')
        return (InputImpl.VideoFromFile(str(path)), frames)


class EndlessH3StitchScene:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'project_id': ('STRING',), 'job_id': ('STRING',),
            'scene_index': ('INT', {'min':1,'max':9999}), 'video_vae': ('VAE',)},
            'optional': {'audio_vae': ('VAE',), 'previous_scenes': ('STRING', {'default':'[]'}), 'master_audio': ('AUDIO',)}}
    RETURN_TYPES = ('STRING',)
    FUNCTION = 'stitch'
    CATEGORY = 'MiniMax H3/flgaship h3 Studio/internal'

    def stitch(self, project_id, job_id, scene_index, video_vae, audio_vae=None, previous_scenes='[]', master_audio=None):
        return (stitch_scene(STORE, project_id, job_id, scene_index, video_vae, audio_vae, previous_scenes, master_audio),)


class EndlessH3ConcatScenes:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'project_id': ('STRING',), 'job_id': ('STRING',), 'scene_manifest': ('STRING',)}}
    RETURN_TYPES = ('VIDEO','INT')
    FUNCTION = 'merge'
    CATEGORY = 'MiniMax H3/flgaship h3 Studio/internal'

    def merge(self, project_id, job_id, scene_manifest):
        from comfy_api.latest import InputImpl
        output, frames = concat_scenes(STORE, project_id, job_id, scene_manifest)
        return (InputImpl.VideoFromFile(str(output)), frames)


class EndlessH3ConcatClips:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'project_id': ('STRING',), 'job_id': ('STRING',)}}

    RETURN_TYPES = ('VIDEO', 'INT')
    FUNCTION = 'merge'
    CATEGORY = 'MiniMax H3/flgaship h3 Studio/internal'

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float('nan')

    def merge(self, project_id, job_id):
        from comfy_api.latest import InputImpl
        project = STORE.load(project_id)
        job = project['jobs'].get(job_id)
        if job is None:
            raise ProjectError('합치기 작업을 찾을 수 없습니다.')
        output, frames = concat_clips(project, job, STORE)
        return (InputImpl.VideoFromFile(str(output)), frames)


class EndlessH3ProjectCommit:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'video': ('VIDEO',), 'project_id': ('STRING',), 'job_id': ('STRING',),
                             'frames': ('INT', {'min': 1, 'max': 36000000})},
                'optional': {'latent_path': ('STRING',)}}

    RETURN_TYPES = ('STRING',)
    FUNCTION = 'commit'
    OUTPUT_NODE = True
    CATEGORY = 'MiniMax H3/flgaship h3 Studio/internal'

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float('nan')

    def commit(self, video, project_id, job_id, frames, latent_path=''):
        # All native save dependencies have executed before this lightweight commit.
        p = STORE.load(project_id)
        if job_id not in p['jobs']:
            raise ProjectError('저장할 작업을 찾을 수 없습니다.')
        folder = STORE.folder(project_id) / 'jobs' / job_id
        files = [f for f in folder.glob('video_*') if f.suffix.lower() in ('.mp4', '.mkv', '.webm')]
        if len(files) != 1:
            raise ProjectError('완성된 영상 파일을 확인할 수 없어 클립 번호를 유지했습니다.')
        video_path = files[0].relative_to(STORE.output).as_posix()
        latent_relative = Path(latent_path).resolve().relative_to(STORE.output).as_posix() if latent_path else ''
        p = STORE.commit(project_id, job_id, latent_relative, video_path, frames)
        payload = public_project(p)
        PromptServer.instance.send_sync('endless_h3_aio_completed', payload)
        report = f'{p["name"]} · 저장 완료'
        return {'ui': {'text': [report]}, 'result': (report,)}


NODE_CLASS_MAPPINGS = {'EndlessH3StitchScene': EndlessH3StitchScene, 'EndlessH3ConcatScenes': EndlessH3ConcatScenes, 'EndlessH3ConcatClips': EndlessH3ConcatClips, 'EndlessH3AllInOne': EndlessH3AllInOne, 'EndlessH3ProjectCommit': EndlessH3ProjectCommit,
                       'EndlessH3OutputVideo': EndlessH3OutputVideo,
                       'EndlessH3BackgroundFrame': EndlessH3BackgroundFrame}
NODE_DISPLAY_NAME_MAPPINGS = {'EndlessH3StitchScene': 'flgaship h3 · Endless 씬 합치기', 'EndlessH3ConcatScenes': 'flgaship h3 · FFmpeg 씬 연결', 'EndlessH3ConcatClips': 'flgaship h3 · FFmpeg 빠른 합치기', 'EndlessH3AllInOne': 'flgaship h3 올인원 스튜디오',
                             'EndlessH3OutputVideo': 'flgaship h3 · 저장된 합본 불러오기',
                             'EndlessH3BackgroundFrame': 'flgaship h3 · 첫 클립 배경 화면',
                             'EndlessH3ProjectCommit': 'flgaship h3 · 완료 기록'}
WEB_DIRECTORY = './web'
__version__ = '0.1.0'
