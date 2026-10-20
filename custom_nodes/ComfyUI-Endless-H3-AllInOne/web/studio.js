import { app } from '../../../scripts/app.js';

import { api } from '../../../scripts/api.js';

import { StudioCameraWindow } from './camera_window.js?v=native_camera_static_import_20261019';

import { StudioActionPreview } from './studio_action_preview.js?v=hoverloop_20261017';

import { StudioLivePreview } from './live_preview.js?v=flagship20261017';

import { StudioDockLayout } from './studio_layout.js?v=panelnames_20261017';

import { PreviewNodes, previewNodeModel, nodeLocation } from './preview_nodes.js?v=flagship20261017';

import { ensureSequencePlan, sceneForClip, referenceSource, continuesAt, sceneClipIndices, clipLabel, appendScene, splitSceneAt, insertSceneClip, pruneEmptyScenes } from './sequence.js';



const clone = value => JSON.parse(JSON.stringify(value));

export function galleryOutputs(project) {

    return Object.values(project.clips || {}).flatMap(clip => [

        {...clip, kind: 'clip', label: `클립 ${clip.index}`},

        ...(clip.history || []).map((old, i) => ({...old, kind: 'clip', index: clip.index,

            label: `클립 ${clip.index} · 이전 결과 ${i + 1}`, historic: true})),

    ]).concat((project.exports || []).map((item, i) => ({...item, kind: 'full',

        label: `합본 ${i + 1}${item.upscaled ? ` · 업스케일 ${item.scale}×` : ''}`})))

        .filter(item => item.video && item.job)

        .map(item => ({...item, key: `${project.id}:${item.job}`, project_id: project.id,

            project_name: project.name, busy: !!project.active || project.batch?.state === 'running',

            job_status: project.jobs?.[item.job]}));

}

const emptyClip = () => ({prompt: '', seconds: 5, mode: 'I2V', first_image: '', last_image: '', images: [], videos: [], audios: [], seed: -1});

export function clipRefinerConfig(clip) {

    const value = clip.refiner || {};

    const requested = value.mode ?? (typeof value.enabled === 'boolean' ? (value.enabled ? 'on' : 'off') : 'off');

    const mode = requested === 'inherit' ? 'off' : requested;

    return {mode, strength: value.strength ?? .1, reference_clip: value.reference_clip ?? 1, reason: value.reason ?? ''};

}

export function clipRefinerEffective(settings, clip) {

    const r = clipRefinerConfig(clip);

    return {enabled: r.mode === 'on', strength: r.strength, reference_clip: r.reference_clip};

}

export function outputUpscaleTarget(items, selected, preview) {

    if (selected.size > 1) return null;

    const chosen = selected.size ? items.filter(item => selected.has(item.key)) : (preview ? [preview] : []);

    return chosen.length === 1 && chosen[0].kind === 'full' && !chosen[0].gallery_deleted ? chosen[0] : null;

}

export function commonPictureIndices(plan, clip) {

    const text = `${plan.settings.shared_prompt || ''}\n${sceneForClip(plan, clip)?.prompt || ''}\n${clip.prompt}`;

    return [...new Set([...text.matchAll(/<Picture\s+(\d+)>|@picture_(\d+)(?![\w-])/gi)]

        .map(match => Number(match[1] || match[2])))].sort((a, b) => a - b);

}

export function syncReferences(plan) {

    const keys = ['images', 'videos', 'audios'];

    if (!plan.references) {

        const source = plan.clips.find(c => c.mode === 'R2V' && keys.some(k => c[k]?.length));

        plan.references = Object.fromEntries(keys.map(k => [k, clone(source?.[k] || [])]));

    }

    ensureSequencePlan(plan);

    for (const clip of plan.clips) {

        const refs = referenceSource(plan, clip);

        const refiner = clipRefinerConfig(clip);

        if (!clip.refiner || typeof clip.refiner !== 'object' || Array.isArray(clip.refiner)) clip.refiner = refiner;

        else { Object.assign(clip.refiner, refiner); delete clip.refiner.enabled; }

        clip.background_refresh ??= false;

        clip.background_source ??= 'image';

        clip.background_image ??= '';

        clip.background_time ??= 0;

        for (const key of keys) clip[key] ||= [];

        clip.use_common_references ??= !keys.some(k => clip[k].length) ||

            keys.every(k => JSON.stringify(clip[k]) === JSON.stringify(refs[k] || []));

        if (clip.mode === 'R2V' && clip.use_common_references) {

            for (const key of keys) clip[key] = clone(refs[key] || []);

            clip.images = commonPictureIndices(plan, clip).map(i => refs.images[i - 1]).filter(Boolean);

        }

    }

}

export function applyBackgroundToCompleted(plan, project, selected) {

    const source = plan.clips[selected];

    let count = 0;

    for (let i = selected + 1; i < plan.clips.length; i++) {

        if (!project?.clips[String(i + 1)]?.video) continue;

        for (const key of ['background_refresh', 'background_source', 'background_image', 'background_time']) {

            plan.clips[i][key] = source[key];

        }

        count++;

    }

    return count;

}

const aspectPresets = ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9', '9:21', '3:2', '2:3', '4:5', '5:4', '1:2', '2:1'];

const megapixelPresets = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.98, 1, 1.2, 1.5, 1.8, 2];

// Keep the established H3 all-in-one presets, including the 768-pixel short edge.

// Portrait uses the same dimensions with width and height exchanged.

const h3LandscapePresets = new Map([

    [0.2, [608, 352]], [0.3, [736, 416]], [0.4, [864, 480]],

    [0.5, [960, 544]], [0.6, [1056, 608]], [0.7, [1152, 640]],

    [0.8, [1216, 672]], [0.9, [1280, 736]], [0.98, [1344, 768]],

    [1, [1376, 768]], [1.2, [1504, 832]], [1.5, [1664, 928]],

    [1.8, [1824, 1024]], [2, [1920, 1088]],

]);

const aspectValue = aspect => { const [w, h] = aspect.split(':').map(Number); return w / h; };

const gcd = (a, b) => b ? gcd(b, a % b) : a;

const calculatedResolutionFor = (aspect, megapixels) => {

    const ratio = aspectValue(aspect);

    const align = value => Math.min(8192, Math.max(256, Math.round(value / 32) * 32));

    return {width: align(Math.sqrt(megapixels * 1e6 * ratio)), height: align(Math.sqrt(megapixels * 1e6 / ratio))};

};

const resolutionFor = (aspect, megapixels) => {

    const preset = h3LandscapePresets.get(Number(megapixels));

    if (preset && (aspect === '16:9' || aspect === '9:16')) {

        const [longEdge, shortEdge] = preset;

        return aspect === '16:9'

            ? {width: longEdge, height: shortEdge}

            : {width: shortEdge, height: longEdge};

    }

    return calculatedResolutionFor(aspect, megapixels);

};

const migrateResolutionPreset = (settings, selection, locked = false) => {

    if (locked) return selection;

    const matches = value => value?.width === settings.width && value?.height === settings.height;

    let candidate;

    if (matches(selection)) {

        // Only migrate a saved standard choice; an explicit custom ratio stays custom.

        if (['16:9', '9:16'].includes(selection.aspect) && h3LandscapePresets.has(Number(selection.megapixels))) candidate = selection;

    } else {

        // Project files store dimensions without the UI choice. Recognize the old

        // calculated sizes only when they are not already a restored preset.

        const currentPreset = ['16:9', '9:16'].some(aspect => megapixelPresets.some(mp => matches(resolutionFor(aspect, mp))));

        if (!currentPreset) candidate = ['16:9', '9:16'].flatMap(aspect => megapixelPresets.map(megapixels =>

            ({aspect, megapixels, ...calculatedResolutionFor(aspect, megapixels)}))).find(matches);

    }

    if (!candidate || !matches(calculatedResolutionFor(candidate.aspect, candidate.megapixels))) return selection;

    const dimensions = resolutionFor(candidate.aspect, candidate.megapixels);

    Object.assign(settings, dimensions);

    return {aspect: candidate.aspect, megapixels: Number(candidate.megapixels), ...dimensions};

};

const viewURL = (path, type = 'output') => {

    path = path.replaceAll('\\', '/');

    const slash = path.lastIndexOf('/');

    return api.apiURL(`/view?${new URLSearchParams({filename: path.slice(slash + 1), subfolder: slash < 0 ? '' : path.slice(0, slash), type})}`);

};

async function request(path, data) {

    const response = await api.fetchApi(`/endless_h3_aio/${path}`, data === undefined ? {} : {

        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data),

    });

    const result = await response.json();

    if (!response.ok) throw new Error(result.error || '요청을 처리할 수 없습니다.');

    return result;

}

function element(tag, text, className = '') {

    const el = document.createElement(tag);

    if (text !== undefined) el.textContent = text;

    if (className) el.className = className;

    return el;

}



const graphViewKey = 'flgaship_h3_node_view';

let graphViewBar;

function showGraphViewBar() {

    graphViewBar?.remove(); graphViewBar = null;

    const graph = app.rootGraph || app.graph;

    const view = graph?.extra?.[graphViewKey];

    if (!view) return;

    graphViewBar = element('div', undefined, 'eh3-node-view-bar');

    const fontScale = view.origin.nodes.find(node => String(node.id) === String(view.node_id))?.properties?.endless_font_scale ?? 1.5;

    graphViewBar.style.setProperty('--font-scale', String(fontScale));

    graphViewBar.append(element('strong', `flgaship h3 · 클립 ${view.index} 노드 보기`));

    const back = element('button', '올인원으로 돌아가기'); graphViewBar.append(back);

    const status = element('span', view.warnings.join(' ')); graphViewBar.append(status);

    graphViewBar.append(element('span', '노드 수정은 별도 초안으로 보관됩니다. 올인원 계획에 자동 적용되지 않습니다.'));

    back.addEventListener('click', async () => {

        if ((app.rootGraph || app.graph) !== graph || graph.extra?.[graphViewKey] !== view) {

            graphViewBar?.remove(); graphViewBar = null; return;

        }

        back.disabled = true;

        try {

            const draft = clone(graph.serialize());

            delete draft.extra[graphViewKey];

            const origin = clone(view.origin);

            const node = origin.nodes.find(n => String(n.id) === String(view.node_id));

            if (!node) throw new Error('돌아갈 올인원 노드를 찾을 수 없습니다.');

            node.properties ||= {};

            node.properties.endless_node_views ||= {};

            node.properties.endless_node_views[String(view.index)] = {signature: view.signature, workflow: draft};

            node.properties.endless_selected_clip = view.index - 1;

            node.properties.endless_selected_clips = [view.index - 1];

            await app.loadGraphData(origin, true, true, `${view.name} · 올인원.json`);

            showGraphViewBar();

        } catch (error) { status.textContent = error.message; back.disabled = false; }

    });

    document.body.append(graphViewBar);

}



export class EndlessStudio {

    constructor(node, configWidget) {

        this.node = node;

        this.widget = configWidget;

        this.selected = node.properties.endless_selected_clip || 0;

        this.selectedClips = new Set(

            Array.isArray(node.properties.endless_selected_clips) && node.properties.endless_selected_clips.length

                ? node.properties.endless_selected_clips

                : [this.selected]

        );

        this.multiSelectMode = Boolean(node.properties.endless_multi_select);

        this.previewClip = node.properties.endless_preview_clip || null;

        this.previewJob = node.properties.endless_preview_job || null;

        this.previewExport = node.properties.endless_preview_export || null;

        this.previewKind = ['full','camera'].includes(node.properties.endless_preview_kind) ? node.properties.endless_preview_kind : 'clip';

        this.cameraPreviewId=node.properties.endless_camera_preview||'source';

        this.generationMode = ['clip', 'all', 'all_assemble', 'camera'].includes(node.properties.endless_generation_mode)

            ? node.properties.endless_generation_mode : 'clip';

        this.project = null;

        this.galleryProjects = new Map();

        this.galleryScope = node.properties.endless_gallery_scope === 'current' ? 'current' : 'all';

        this.galleryPreview = null;

        this.outputSelection = new Set();

        this.favoritesOnly = false;

        this.dirty = false;

        this.busyRequest = false;

        this.root = element('div', undefined, 'eh3-studio');

        this.root.addEventListener('pointerdown', event => event.stopPropagation());

        this.root.addEventListener('wheel', event => event.stopPropagation(), {passive: true});

        this.disposed = false;

        this.finished = event => {

            (async () => {

                if (event.detail.id === this.state?.project_id) await this.refresh();

                await this.refreshGallery();

            })().catch(error => this.notice(error.message));

        };

        api.addEventListener('endless_h3_aio_completed', this.finished);

        this.livePreview = new StudioLivePreview(api, () => this.project?.jobs?.[this.project.active],

            frame => this.previewNodes?.setLivePreview(frame));

        this.timer = setInterval(() => {

            if(this.cameraWindow?.running&&!this.disposed)this.cameraWindow.restoreJob().catch(error=>this.notice(error.message));

            if ((this.project?.active || this.project?.batch?.state === 'running') && !this.disposed) {

                this.refresh().catch(error => this.notice(error.message));

            }

            if (this.pendingOutputUpscale && !this.disposed) {

                this.refreshOutputUpscale().catch(error => this.notice(error.message));

            }

        }, 2500);

        this.restore();

    }



    async restore() {

        const epoch = this.restoreEpoch = (this.restoreEpoch || 0) + 1;

        try {

            this.config = await request('config');

            if (this.disposed || epoch !== this.restoreEpoch) return;

            let state;

            try { state = JSON.parse(this.widget.value || '{}'); } catch { state = {}; }

            this.state = {name: 'flgaship h3 프로젝트', ...state};

            this.state.plan ||= clone(this.config.default_plan);

            this.state.plan.settings = {...this.config.default_plan.settings, ...this.state.plan.settings};

            this.state.plan.clips ||= [emptyClip()];

            if (['clip', 'all', 'all_assemble', 'camera'].includes(this.node.properties.endless_generation_mode)) {

                this.generationMode = this.node.properties.endless_generation_mode;

            }

            this.selected = Math.min(this.node.properties.endless_selected_clip ?? this.selected,

                                     this.state.plan.clips.length - 1);

            if (this.selected < 0) this.selected = 0;

            if (Array.isArray(this.node.properties.endless_selected_clips) && this.node.properties.endless_selected_clips.length) {

                this.selectedClips = new Set(this.node.properties.endless_selected_clips.filter(i => Number.isInteger(i) && i >= 0 && i < this.state.plan.clips.length));

            }

            if (!this.selectedClips || !this.selectedClips.size) this.selectedClips = new Set([this.selected]);

            if (!this.selectedClips.has(this.selected)) this.selected = [...this.selectedClips][0];

            if (this.state.project_id) {

                try {

                    this.project = await request(`project/${this.state.project_id}`);

                    // A workflow's unsaved plan is retained; project reload is an explicit action.

                    this.selected = Math.min(this.node.properties.endless_selected_clip ?? this.project.next_clip - 1,

                                             this.state.plan.clips.length - 1);

                    if (this.selected < 0) this.selected = 0;

                    if (!Array.isArray(this.node.properties.endless_selected_clips) || !this.node.properties.endless_selected_clips.length) {

                        this.selectedClips = new Set([this.selected]);

                    } else this.selectedClips.add(this.selected);

                } catch (error) { this.state.project_id = null; this.startupError = error.message; }

            }

            if (!this.state.project_id) for (const clip of this.state.plan.clips) clip.background_refresh = false;

            this.render();

            this.persist();

            if (this.startupError) this.notice(this.startupError);

            await this.refreshGallery();

            if(this.node.properties.endless_camera_window?.promptId)this.cameraController().ready().catch(error=>this.notice(error.message));

        } catch (error) {

            this.root.replaceChildren(element('p', `올인원 연결 실패: ${error.message}`),

                element('p', '현재 생성이 끝난 뒤 ComfyUI를 재시작하고 브라우저를 새로고침해 주세요.'));

        }

    }



    persist() {

        this.widget.value = JSON.stringify(this.state);

        this.node.properties.endless_project_id = this.state.project_id || '';

        this.node.properties.endless_selected_clip = this.selected;

        this.node.properties.endless_selected_clips = [...this.selectedClips];

        this.node.properties.endless_multi_select = this.multiSelectMode;

        this.node.properties.endless_preview_clip = this.previewClip;

        this.node.properties.endless_preview_job = this.previewJob;

        this.node.properties.endless_preview_export = this.previewExport;

        this.node.properties.endless_preview_kind = this.previewKind;

        this.node.properties.endless_camera_preview = this.cameraPreviewId||'source';

        this.node.properties.endless_generation_mode = this.generationMode;

        this.node.properties.endless_gallery_scope = this.galleryScope;

        app.graph?.setDirtyCanvas(true, true);

    }



    changed() { syncReferences(this.state.plan); this.updateReferenceSelection(); this.dirty = true; this.persist(); }

    collapsible(parent, key, title, className, open = true) {

        const panels = this.node.properties.endless_panels ||= {};

        const details = element('details', undefined, 'eh3-panel'); parent.append(details);

        details.dataset.panel = key; details.open = panels[key] ?? open;

        const summary = element('summary', title); details.append(summary);

        const panel = element('section', undefined, className); details.append(panel);

        details.addEventListener('toggle', () => {

            if (!details.isConnected) return;

            panels[key] = details.open;

            if (!details.open) panel.querySelectorAll('video,audio').forEach(media => media.pause());

            this.persist();

        });

        return panel;

    }



    setUISize(size) {

        this.node.properties.endless_ui_size = size;

        this.root.dataset.uiSize = size;

        this.sizeLabel.textContent = {small: '작게', normal: '보통', large: '크게'}[size];

        this.smallerButton.disabled = size === 'small';

        this.largerButton.disabled = size === 'large';

        this.persist();

    }

    setUIFontScale(percent, save = true) {

        const value = Number(percent);

        if (!Number.isFinite(value)) return;

        const scale = Math.max(50, Math.min(200, Math.round(value))) / 100;

        this.node.properties.endless_font_scale = scale;

        this.cameraWindow?.setFontScale(scale);

        this.root.style.setProperty('--font-scale', String(scale));

        this.referenceDialog?.menu?.style.setProperty('--font-scale', String(scale));

        if (this.fontScaleRange) this.fontScaleRange.value = String(Math.round(scale * 100));

        if (this.fontScaleNumber) this.fontScaleNumber.value = String(Math.round(scale * 100));

        if (save) this.persist();

    }

    notice(message, isError = true) {

        if (!this.status) return;

        this.status.textContent = message;

        this.status.classList.toggle('eh3-error', isError);

    }

    async resetVRAM() {

        if (this.busyRequest || this.project?.active || this.project?.batch?.state === 'running') {

            throw new Error('작업이 끝난 뒤 VRAM을 리셋해 주세요.');

        }

        this.busyRequest = true;

        this.updateStatus();

        this.notice('생성 큐 확인 중…', false);

        try {

            const response = await api.fetchApi('/queue');

            if (!response.ok) throw new Error(`생성 큐 확인 실패 (${response.status})`);

            const queue = await response.json();

            if (queue.queue_running.length || queue.queue_pending.length) {

                throw new Error('ComfyUI에 실행 또는 대기 중인 작업이 있어 VRAM을 리셋할 수 없습니다.');

            }

            this.notice('모델과 메모리 캐시 해제 요청 중…', false);

            const freed = await api.fetchApi('/free', {

                method: 'POST',

                headers: {'Content-Type': 'application/json'},

                body: JSON.stringify({unload_models: true, free_memory: true}),

            });

            if (!freed.ok) throw new Error(`VRAM 해제 요청 실패 (${freed.status})`);

        } finally {

            this.busyRequest = false;

            if (!this.disposed) this.updateStatus();

        }

        if (!this.disposed) this.notice('VRAM 해제 요청 완료 · 다음 생성 시 모델을 다시 불러옵니다.', false);

    }

    button(label, callback, parent, className = '') {

        const button = element('button', label, className);

        button.type = 'button';

        button.addEventListener('click', async () => {

            try { await callback(); } catch (error) { this.notice(error.message); }

        });

        parent.append(button);

        return button;

    }

    options(select, items, value, emptyLabel) {

        select.replaceChildren();

        if (emptyLabel !== undefined) {

            const option = element('option', emptyLabel); option.value = ''; select.append(option);

        }

        for (const item of items) {

            const option = element('option', item); option.value = item; select.append(option);

        }

        if (value && !items.includes(value)) {

            const option = element('option', `${value} · 파일 확인 필요`); option.value = value; select.append(option);

        }

        select.value = value ?? '';

    }

    field(parent, label, object, key, options = {}) {

        const wrapper = element('label', undefined, 'eh3-field');

        wrapper.append(element('span', label));

        const input = element(options.items ? 'select' : options.multiline ? 'textarea' : 'input');

        input.setAttribute('aria-label', label);

        if (options.items) this.options(input, options.items, object[key], options.emptyLabel);

        else if (typeof object[key] === 'boolean') { input.type = 'checkbox'; input.checked = object[key]; }

        else { if (input.tagName === 'INPUT') input.type = options.type || 'text'; input.value = object[key] ?? ''; }

        if (options.step) input.step = options.step;

        if (options.min !== undefined) input.min = options.min;

        if (options.max !== undefined) input.max = options.max;

        input.disabled = options.disabled || false;

        if (options.asset) {

            this.assetSelectors ||= [];

            this.assetSelectors.push({input, asset: options.asset, filter: options.filter, emptyLabel: options.emptyLabel});

        }

        input.addEventListener('input', () => {

            object[key] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;

            this.changed();

            if (key === 'prompt') this.drawClips();

        });

        const searchable = options.items && (options.searchable || ['model', 'clip', 'video_vae', 'audio_vae', 'turbo_lora', 'reference_lora', 'name', 'audio_file'].includes(key));

        if (searchable) {

            const row = element('div', undefined, 'eh3-file-choice'); wrapper.append(row);

            input.hidden = true; input.setAttribute('aria-label', `${label} 저장값`); row.append(input);

            const trigger = this.button('', () => {

                if (input.disabled) return;

                if (this.referenceDialog?.origin === trigger) { this.referenceDialog.close(); return; }

                this.searchFiles(label, Array.from(input.options, option => ({value: option.value, label: option.textContent})), input.value, value => {

                    if (!input.isConnected || input.disabled || this.busyRequest || this.project?.active || this.project?.batch?.state === 'running') {

                        throw new Error('현재 작업이 끝난 후 파일을 선택해 주세요.');

                    }

                    input.value = value;

                    input.dispatchEvent(new Event('input', {bubbles: true}));

                    input.dispatchEvent(new Event('change', {bubbles: true}));

                }, `${label} 검색`, `${label} 파일 목록`, trigger);

            }, row, 'eh3-file-trigger');

            const updateLabel = () => {

                trigger.textContent = input.selectedOptions[0]?.textContent || options.emptyLabel || '파일 선택';

                trigger.title = trigger.textContent;

            };

            input.addEventListener('input', updateLabel);

            input.addEventListener('files-refreshed', updateLabel); updateLabel();

            trigger.setAttribute('role', 'combobox'); trigger.setAttribute('aria-label', label);

            trigger.setAttribute('aria-haspopup', 'listbox'); trigger.setAttribute('aria-expanded', 'false');

            trigger.addEventListener('keydown', event => {

                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); event.stopPropagation(); trigger.click(); }

            });

            // Busy and geometry locks remain owned by the underlying selector.

            trigger.dataset.fileSearch = 'true'; trigger.disabled = input.disabled;

        } else wrapper.append(input);

        parent.append(wrapper);

        return input;

    }



    captureScroll() {

        const panels = {controls: this.controls, clips: this.clipGrid, editors: this.multiClipContainer, gallery: this.galleryList,

            results: this.results, nodes: this.previewNodes?.list, workspace: this.root.querySelector('.eh3-workspace')};

        const view = Object.fromEntries(Object.entries(panels).filter(([, panel]) => panel)

            .map(([key, panel]) => [key, {top: panel.scrollTop, left: panel.scrollLeft}]));

        if (this.controls) {

            const bounds = this.controls.getBoundingClientRect();

            const candidates = Array.from(this.controls.querySelectorAll('details[data-panel]'))

                .filter(panel => { const r = panel.getBoundingClientRect(); return r.height && r.bottom > bounds.top && r.top < bounds.bottom; });

            const anchor = candidates.filter(panel => panel.getBoundingClientRect().top <= bounds.top).at(-1) || candidates[0];

            if (anchor) view.anchor = {key: anchor.dataset.panel, offset: anchor.getBoundingClientRect().top - bounds.top};

        }

        return view;

    }



    restoreScroll(view) {

        const panels = {controls: this.controls, clips: this.clipGrid, editors: this.multiClipContainer, gallery: this.galleryList,

            results: this.results, nodes: this.previewNodes?.list, workspace: this.root.querySelector('.eh3-workspace')};

        for (const [key, panel] of Object.entries(panels)) {

            if (panel && view[key]) { panel.scrollTop = view[key].top; panel.scrollLeft = view[key].left; }

        }

        const anchor = view.anchor && Array.from(this.controls?.querySelectorAll('details[data-panel]') || [])

            .find(panel => panel.dataset.panel === view.anchor.key);

        if (anchor) this.controls.scrollTop += anchor.getBoundingClientRect().top - this.controls.getBoundingClientRect().top - view.anchor.offset;

    }



    searchFiles(title, files, current, apply, searchLabel = `${title} 검색`, listLabel = `${title} 파일 목록`, origin = document.activeElement) {

        this.referenceDialog?.close();

        const menu = element('div', undefined, 'eh3-file-popover'); menu.setAttribute('popover', 'auto');

        menu.style.setProperty('--font-scale', String(this.node.properties.endless_font_scale ?? 1.5));

        const search = element('input'); search.type = 'search';

        search.placeholder = /^(종횡비|메가픽셀)/.test(title) ? '값 검색' : '파일 이름 검색';

        search.setAttribute('aria-label', searchLabel); menu.append(search);

        const list = element('div', undefined, 'eh3-file-options'); list.setAttribute('role', 'listbox');

        list.setAttribute('aria-label', listLabel); menu.append(list);

        list.id = `eh3-files-${this.node.id}-${this.fileMenuCounter = (this.fileMenuCounter || 0) + 1}`;

        search.setAttribute('aria-controls', list.id);

        const status = element('div', undefined, 'eh3-file-empty'); status.setAttribute('role', 'status'); menu.append(status);

        let matches = [], active = -1, closed = false;

        const position = () => {

            if (closed || !origin?.isConnected) return;

            const rect = origin.getBoundingClientRect(), width = document.documentElement.clientWidth, height = document.documentElement.clientHeight;

            const below = height - rect.bottom - 8, above = rect.top - 8;

            const up = below < Math.min(200, above);

            menu.style.width = `${Math.min(Math.max(rect.width, 280), 560, width - 16)}px`;

            menu.style.maxHeight = `${Math.max(90, Math.min(360, up ? above : below))}px`;

            menu.style.left = `${Math.max(8, Math.min(rect.left, width - menu.offsetWidth - 8))}px`;

            menu.style.top = `${Math.max(8, Math.min(up ? rect.top - menu.offsetHeight - 4 : rect.bottom + 4, height - menu.offsetHeight - 8))}px`;

        };

        const close = (focus = true) => {

            if (closed) return; closed = true;

            window.removeEventListener('resize', position); window.removeEventListener('scroll', position, true);

            if (menu.matches(':popover-open')) menu.hidePopover(); menu.remove();

            if (this.referenceDialog?.menu === menu) this.referenceDialog = null;

            origin?.setAttribute('aria-expanded', 'false'); origin?.removeAttribute('aria-controls');

            if (focus && origin?.isConnected) origin.focus({preventScroll: true});

        };

        this.referenceDialog = {close, origin, menu};

        const highlight = (scroll = true) => {

            Array.from(list.children).forEach((option, i) => option.classList.toggle('active', i === active));

            const option = list.children[active];

            if (!option) { search.removeAttribute('aria-activedescendant'); return; }

            search.setAttribute('aria-activedescendant', option.id);

            if (scroll) {

                const bounds = list.getBoundingClientRect(), rect = option.getBoundingClientRect();

                if (rect.top < bounds.top) list.scrollTop += rect.top - bounds.top;

                else if (rect.bottom > bounds.bottom) list.scrollTop += rect.bottom - bounds.bottom;

            }

        };

        const choose = index => {

            if (!matches[index]) return;

            try { apply(matches[index].value); close(); }

            catch (error) { status.hidden = false; status.textContent = error.message; position(); }

        };

        const draw = () => {

            const words = search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);

            matches = files.filter(file => words.every(word => file.label.toLocaleLowerCase().includes(word)));

            list.replaceChildren();

            matches.forEach((file, i) => {

                const option = this.button(file.label, () => choose(i), list);

                option.setAttribute('role', 'option'); option.setAttribute('aria-selected', String(file.value === current));

                option.id = `${list.id}-${i}`; option.title = file.label;

                option.addEventListener('pointerenter', () => { active = i; highlight(false); });

            });

            active = words.length ? 0 : Math.max(0, matches.findIndex(file => file.value === current));

            status.hidden = !!matches.length; status.textContent = '검색 결과 없음';

            position(); highlight();

        };

        search.addEventListener('input', draw); draw();

        menu.addEventListener('keydown', event => {

            event.stopPropagation();

            if (event.key === 'Escape') { event.preventDefault(); close(); }

            else if (event.key === 'Enter') { event.preventDefault(); choose(active); }

            else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {

                event.preventDefault(); active = Math.max(0, Math.min(matches.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1))); highlight();

            } else if (event.key === 'Tab') close(false);

        });

        menu.addEventListener('pointerdown', event => event.stopPropagation());

        menu.addEventListener('wheel', event => event.stopPropagation(), {passive: true});

        menu.addEventListener('toggle', event => { if (event.newState === 'closed') close(false); });

        // Keep a picker opened from common settings inside that modal's active subtree.

        (origin?.closest('dialog[open]') || document.body).append(menu);

        origin?.setAttribute('aria-expanded', 'true'); origin?.setAttribute('aria-controls', list.id);

        menu.showPopover(); position(); highlight(); search.focus({preventScroll: true});

        window.addEventListener('resize', position); window.addEventListener('scroll', position, true);

    }



    projectName() {

        this.newProjectDialog?.close();

        return new Promise(resolve => {

            let result = null;

            const dialog = this.newProjectDialog = element('dialog', undefined, 'eh3-dialog eh3-new-project-dialog'); this.root.append(dialog);

            dialog.setAttribute('aria-label', '새 작업 만들기');

            dialog.append(element('h3', '새 작업'));

            const label = element('label', undefined, 'eh3-field'); dialog.append(label);

            label.append(element('span', '프로젝트 이름'));

            const input = element('input'); input.type = 'text'; input.maxLength = 160;

            input.value = this.state.name || 'flgaship h3 프로젝트'; input.setAttribute('aria-label', '새 프로젝트 이름'); label.append(input);

            const message = element('p', '현재 프롬프트와 설정을 복사합니다. 생성 결과는 기존 작업에 보관됩니다.', 'eh3-help'); dialog.append(message);

            const actions = element('div', undefined, 'eh3-row'); dialog.append(actions);

            const submit = () => {

                if (!input.value.trim()) { message.textContent = '프로젝트 이름을 입력해 주세요.'; input.focus(); return; }

                result = input.value.trim(); dialog.close();

            };

            this.button('취소', () => dialog.close(), actions);

            this.button('만들기', submit, actions);

            input.addEventListener('keydown', event => {

                event.stopPropagation(); if (event.key === 'Enter') { event.preventDefault(); submit(); }

            });

            dialog.addEventListener('close', () => {

                dialog.remove(); if (this.newProjectDialog === dialog) this.newProjectDialog = null;

                resolve(result);

            }, {once: true});

            dialog.showModal(); input.focus({preventScroll: true}); input.select();

        });

    }



    async newProject() {

        const blocked = () => this.busyRequest || this.project?.active || this.project?.batch?.state === 'running';

        if (blocked()) throw new Error('현재 작업이 끝난 후 새 프로젝트를 만들어 주세요.');

        const name = await this.projectName();

        if (!name || this.disposed) return;

        if (blocked()) throw new Error('현재 작업이 끝난 후 새 프로젝트를 만들어 주세요.');

        this.busyRequest = true; this.updateStatus();

        try {

            const plan = clone(this.state.plan);

            const resolution = migrateResolutionPreset(plan.settings, this.state.resolution);

            for (const clip of plan.clips) clip.background_refresh = false;

            const p = await request('project', {name, plan});

            this.state = {name: p.name, project_id: p.id, plan: p.plan, resolution};

            this.project = p; this.selected = 0; this.selectedClips = new Set([0]); this.previewClip = null; this.previewJob = null; this.previewExport = null; this.previewKind = 'clip'; this.dirty = false;

            this.galleryPreview = null;

            this.persist();

        } finally { this.busyRequest = false; if (!this.disposed) this.render(); }

    }



    async refresh() {

        if (this.disposed) return;

        if (!this.state?.project_id) { await this.refreshGallery(); return; }

        const previousActive = this.project?.active;

        const previousBatch = this.project?.batch?.state;

        const previousClips = this.project?.clips || {};

        const previousExport = this.project?.exports.at(-1)?.job;

        const p = await request(`project/${this.state.project_id}`);

        if (this.disposed) return;

        const completed = Object.values(p.clips).filter(clip => previousClips[String(clip.index)]?.job !== clip.job)

            .sort((a, b) => b.created - a.created);

        if (completed.length) { this.galleryPreview = null; this.previewClip = completed[0].index; this.previewJob = null; this.previewKind = 'clip'; }

        if (p.exports.at(-1)?.job !== previousExport) {

            this.previewExport = p.exports.at(-1)?.job || null;

            this.galleryPreview = null;

            if (this.previewExport) this.previewKind = 'full';

        }

        this.project = p;

        this.persist();

        if ((previousActive && previousActive !== p.active) || previousBatch !== p.batch?.state) {

            const job = p.jobs[previousActive];

            if (job?.state === 'completed' || p.batch?.state === 'running') {

                this.selected = Math.min((p.active ? p.jobs[p.active].index : p.next_clip) - 1,

                                         this.state.plan.clips.length - 1);

                this.selectedClips = new Set([this.selected]);

                this.persist();

            }

            this.render();

            if (job?.state === 'failed' && p.batch?.state !== 'running') this.notice(job.error);

        } else { this.updateStatus(); this.previewNodes?.revealActive(); }

    }



    updateStatus() {

        const active = this.project?.active && this.project.jobs[this.project.active];

        const batch = this.project?.batch;

        const auto = batch?.state === 'running';

        const cameraBusy=!!this.cameraWindow?.running||!!this.cameraWindow?.submitting;

        const cameraMode=this.generationMode==='camera';

        const busy = !!active || auto || this.busyRequest || cameraBusy;

        const next = this.project?.next_clip || 1;

        const scheduled = auto && batch.kind === 'scheduled_clip';

        const waiting = scheduled && active?.id === batch.wait_job;

        this.generateButton.classList.toggle('running', busy);

        this.generateButton.setAttribute('aria-busy', String(busy));

        this.generateLabel.textContent = busy ? '생성 중…' : 'Generate';

        if (this.cameraButton) {

            this.cameraButton.disabled = this.cameraButton.dataset.ready !== 'true';

            this.cameraButton.classList.toggle('selected', !this.cameraButton.disabled);

        }

        this.generateButton.disabled = busy || (this.generationMode === 'clip' ? this.selected + 1 > next :

            this.generationMode === 'all' && next > this.state.plan.clips.length);

        this.generateButton.title = this.generationMode === 'clip' ? `선택한 ${clipLabel(this.state.plan, this.selected)} 생성 · 완료 클립은 다시 생성` :

            this.generationMode === 'all' ? '남은 모든 클립 생성' : '남은 모든 클립 생성 후 합치기';

        this.generationTarget.textContent = this.generationMode === 'clip' ? `${clipLabel(this.state.plan, this.selected)}${this.project?.clips[String(this.selected + 1)] ? ' · 다시 생성' : ''}` :

            this.generationMode === 'all' ? '남은 전체 클립' : '남은 전체 클립 → 합치기';

        this.modeInputs.forEach(input => { input.disabled = busy || (input.value==='camera'&&!this.cameraReferences().length); });

        if(cameraMode){this.generateButton.disabled=busy||!this.cameraReferences().length;this.generateButton.title='본 UI 설정으로 카메라 영상 생성';this.generationTarget.textContent='카메라 디렉팅';}

        this.scheduleButton.textContent = waiting ? `✓ 클립 ${batch.target_clip} 예약 · 취소` : '다음 예약 생성';

        this.scheduleButton.classList.toggle('selected', waiting);

        this.scheduleButton.setAttribute('aria-pressed', String(waiting));

        this.scheduleButton.disabled = cameraMode || cameraBusy || this.busyRequest || !this.config.scheduled_clip_supported ||

            (!waiting && (this.generationMode !== 'clip' || auto || !active || ['assemble', 'upscale'].includes(active.action) || active.index >= this.state.plan.clips.length));

        this.scheduleButton.title = this.config.scheduled_clip_supported ? '현재 클립 저장 성공 후 다음 클립 한 개만 자동 생성 · 다시 누르면 예약 취소' :

            '현재 생성이 끝난 후 ComfyUI를 재시작하면 예약 기능이 적용됩니다.';

        this.mergeButton.disabled = busy || next <= this.state.plan.clips.length || next === 1;

        this.addButton.disabled = busy;

        this.saveButton.disabled = busy;

        this.newButton.disabled = busy;

        this.projectSelect.disabled = busy;

        this.modeSelect.disabled = busy;

        this.cancelButton.disabled = !(active || auto || cameraBusy) || this.busyRequest;

        this.nodeViewButton.disabled = this.busyRequest || cameraMode || cameraBusy;

        this.vramResetButton.disabled = busy;

        this.sequenceToggle.disabled = busy || !this.config.sequence_mode_supported;

        this.sequenceToggle.title = this.config.sequence_mode_supported ? 'OFF 일반 연속 클립 / ON 씬 안에 클립 · 씬 설정 유지' : 'ComfyUI 재시작 후 시퀀스 모드를 사용할 수 있습니다.';

        const sequenceUnavailable = (this.state.plan.sequence_mode || this.state.plan.scenes?.length > 1) && !this.config.sequence_mode_supported;

        if (sequenceUnavailable) { this.generateButton.disabled = true; this.saveButton.disabled = true; this.scheduleButton.disabled = true; this.nodeViewButton.disabled = true; }

        this.sequencePanel?.querySelectorAll('input,textarea,select,button').forEach(input => { input.disabled = busy; });

        this.upscalePanel?.querySelectorAll('button').forEach(button => { button.disabled = busy; });

        this.lorasPanel?.querySelectorAll('input,select,button').forEach(input => { input.disabled = busy; });

        this.optimizerPanel?.querySelectorAll('input,select,button').forEach(input => {

            input.disabled = busy || input.dataset.unavailable === 'true';

        });

        this.refinerPanel?.querySelectorAll('input,select,button').forEach(input => {

            input.disabled = busy || !this.config.clip_refiner_per_clip_only || input.dataset.refinerLocked === 'true';

        });

        this.inputPanel?.querySelectorAll('input,select,button').forEach(input => { input.disabled = busy || input.dataset.unavailable === 'true'; });

        this.audioPanel?.querySelectorAll('input,select,button').forEach(input => {

            input.disabled = busy || !!this.project?.geometry;

        });

        this.resolutionPanel?.querySelectorAll('select').forEach(input => {

            input.disabled = busy || !!this.project?.geometry;

        });

        this.editor?.querySelectorAll('input,textarea,select,button').forEach(input => { input.disabled = busy; });

        this.cameraWindow?.executionPanel?.querySelectorAll('input,button').forEach(input=>{input.disabled=busy;});

        if (busy) this.settingsPanel?.querySelectorAll('input,textarea,select,button').forEach(input => { input.disabled = true; });

        this.root.querySelectorAll('[data-file-search]').forEach(button => {

            button.disabled = button.parentElement.querySelector('select').disabled;

        });

        this.root.querySelectorAll('.eh3-asset-refresh').forEach(button => {

            button.disabled = this.assetRefreshing || !this.config.asset_refresh_supported;

        });

        if (active) {

            const label = active.action === 'upscale' ? '선택 영상 업스케일' : active.action === 'assemble' ? '전체 영상 합치기' : `클립 ${active.index}`;

            this.notice(`${auto && !scheduled ? '전체 자동 실행 · ' : ''}${label} · ${active.state === 'running' ? '생성 중' : '대기 중'}${waiting ? ` · 다음 클립 ${batch.target_clip} 예약됨` : ''} · 완료 ${next - 1} / ${this.state.plan.clips.length}`, false);

        } else if (auto) {

            this.notice(scheduled ? `예약 클립 ${batch.target_clip} 준비 중` : `전체 자동 실행 · 완료 ${next - 1} / ${batch.total} · ${next > batch.total ? '합치기 준비 중' : `클립 ${next} 준비 중`}`, false);

        } else if (batch?.state === 'failed') {

            const latest = Object.values(this.project.jobs).sort((a, b) => b.created - a.created)[0];

            if (!latest || latest.batch_id === batch.id || scheduled || batch.kind === 'scheduled_clip') this.notice(`${batch.kind === 'scheduled_clip' ? '예약' : '전체 실행'} 중단 · ${batch.error}`);

            else this.notice(`완료 ${next - 1} / 계획 ${this.state.plan.clips.length} · 다음은 클립 ${next}`, false);

        } else if (batch?.state === 'completed' && next > this.state.plan.clips.length) {

            this.notice(batch.kind === 'scheduled_clip' ? `예약 클립 ${batch.target_clip} 생성 완료` :

                batch.assemble ? '전체 클립 생성과 영상 합치기가 완료됐습니다.' : '전체 클립 생성 완료 · 합치기를 누를 수 있습니다.', false);

        } else this.notice(`완료 ${next - 1}/${this.state.plan.clips.length} · 다음 ${next}${this.dirty ? ' · 수정됨' : ''}`, false);

        if(cameraBusy||cameraMode)this.notice(this.cameraWindow?.message||'카메라 구간을 설정한 뒤 Generate를 누르세요.',!!this.cameraWindow?.error);

        this.drawClips();

        this.drawPreview();

    }



    renderScenes(parent) {

        if (!this.state.plan.sequence_mode) { this.sequencePanel = null; return; }

        const plan = this.state.plan;

        const scene = sceneForClip(plan, plan.clips[this.selected]);

        const panel = this.sequencePanel = this.collapsible(parent, 'scenes', '씬 계획', 'eh3-scene-panel');

        const grid = element('div', undefined, 'eh3-scene-grid'); panel.append(grid);

        plan.scenes.forEach((item, i) => {

            const indices = plan.clips.flatMap((clip, n) => clip.scene_id === item.id ? [n] : []);

            const complete = indices.filter(n => this.project?.clips[String(n + 1)] && !this.project.clips[String(n + 1)].stale).length;

            const button = this.button(`${i + 1} · ${item.name} (${indices.length})`, () => {

                if (!indices.length) return;

                this.selected = indices[0]; this.selectedClips = new Set([this.selected]);

                this.persist(); this.render();

            }, grid, 'eh3-scene-button' + (item === scene ? ' selected' : ''));

            button.setAttribute('aria-pressed', String(item === scene));

            button.title = `완료 ${complete}/${indices.length} · ${item.continue_previous ? '앞 씬 연결' : '새 씬 시작'}`;

        });

        const row = element('div', undefined, 'eh3-row'); panel.append(row);

        this.button('+ 씬 추가', () => {

            const clip = {...emptyClip(), mode: plan.clips[this.selected].mode, use_common_references: true};

            this.selected = appendScene(plan, this.selected, clip);

            this.selectedClips = new Set([this.selected]); this.changed(); this.render();

        }, row);

        this.button('여기서 씬 분리', () => {

            splitSceneAt(plan, this.selected);

            this.selectedClips = new Set([this.selected]); this.changed(); this.render();

        }, row).title = '선택 클립부터 현재 씬의 끝까지 새 씬으로 분리 · 클립 번호와 생성 파일 유지';

        this.field(panel, '씬 이름', scene, 'name').addEventListener('change', () => this.render());

        this.field(panel, '씬 공통 프롬프트', scene, 'prompt', {multiline: true});

        if (plan.scenes.indexOf(scene) > 0) {

            this.field(panel, '앞 씬에서 이어가기', scene, 'continue_previous').addEventListener('change', () => this.render());

        }

        panel.append(element('p', scene.continue_previous ? '앞 씬의 마지막 클립을 이어받습니다.' :

            '씬 첫 클립은 새로 시작 · 씬 안에서는 앞 클립 연결', 'eh3-help'));

    }



    drawClips() {

        if (!this.clipList) return;

        const prevScroll = this.clipGrid?.scrollTop || 0;

        this.clipList.replaceChildren();



        const visibleIndices = sceneClipIndices(this.state.plan, this.selected);

        const totalCount = this.state.plan.clips.length;

        let completedCount = 0;

        for (let i = 0; i < totalCount; i++) {

            if (!visibleIndices.includes(i)) continue;

            const rec = this.project?.clips[String(i + 1)];

            if (rec && !rec.missing && !rec.stale && !rec.gallery_deleted) completedCount++;

        }



        const bar = element('div', undefined, 'eh3-clip-bar');

        this.clipList.append(bar);



        const stat = element('span', `클립 ${visibleIndices.length}개 · 완료 ${completedCount}개 · 선택 ${this.selectedClips.size}개`, 'eh3-clip-stat');

        bar.append(stat);



        const barTools = element('div', undefined, 'eh3-clip-bar-tools');

        bar.append(barTools);



        const isAllSelected = this.selectedClips.size === visibleIndices.length && visibleIndices.every(i => this.selectedClips.has(i));

        const allBtn = this.button(isAllSelected ? '선택 초기화' : '전체 선택', () => {

            if (isAllSelected) {

                this.selectedClips = new Set([this.selected]);

            } else {

                this.selectedClips = new Set(visibleIndices);

            }

            this.persist();

            this.render();

        }, barTools, 'eh3-clip-tool-btn' + (isAllSelected ? ' selected' : ''));

        allBtn.title = isAllSelected ? '현재 선택 클립 1개만 선택' : '모든 클립을 한번에 선택하여 확인/수정';



        const multiBtn = this.button(this.multiSelectMode ? '✓ 다중 선택' : '다중 선택', () => {

            this.multiSelectMode = !this.multiSelectMode;

            this.persist();

            this.drawClips();

        }, barTools, 'eh3-clip-tool-btn' + (this.multiSelectMode ? ' selected' : ''));

        multiBtn.title = '켜짐: 번호 클릭 시 토글 다중 선택\n꺼짐: 일반 클릭 시 1개만 선택 (Ctrl+클릭으로 다중 선택)';



        const grid = this.clipGrid = element('div', undefined, 'eh3-clip-grid');

        this.clipList.append(grid);



        this.state.plan.clips.forEach((clip, i) => {

            if (!visibleIndices.includes(i)) return;

            const record = this.project?.clips[String(i + 1)];

            const isDone = Boolean(record && !record.missing && !record.stale && !record.gallery_deleted);

            const isStale = Boolean(record?.stale);

            const isMissing = Boolean(record?.missing);

            const isSelected = this.selectedClips.has(i);

            const isPrimary = (i === this.selected);



            const stateLabel = isMissing ? '파일 누락' : isStale ? '재생성 필요' : record?.gallery_deleted ? '완료 · 휴지통' : isDone ? '완료' : '미생성';

            const classes = [

                'eh3-clip-square',

                isDone ? 'done' : '',

                isStale ? 'stale' : '',

                isMissing ? 'missing' : '',

                isSelected ? 'selected' : '',

                isPrimary ? 'primary-focus' : '',

            ].filter(Boolean).join(' ');



            const button = element('button', undefined, classes);

            button.type = 'button';

            grid.append(button);



            const num = element('span', String(visibleIndices.indexOf(i) + 1), 'eh3-clip-num');

            button.append(num);



            const dot = element('span', undefined, 'eh3-clip-dot');

            button.append(dot);



            const promptSnippet = clip.prompt.trim() ? clip.prompt.trim().slice(0, 100) : '(프롬프트 없음)';

            button.title = `${clipLabel(this.state.plan, i)} [${stateLabel}] · 전체 번호 ${i + 1}\n길이: ${clip.seconds || 5}초 | 시드: ${clip.seed ?? -1}\n프롬프트: ${promptSnippet}\n\n• 클릭: 선택\n• [다중 선택] 또는 Ctrl+클릭: 다중 선택`;

            button.setAttribute('aria-label', `${clipLabel(this.state.plan, i)} ${stateLabel}`);

            button.setAttribute('aria-pressed', String(isSelected));

            button.disabled = this.busyRequest;



            button.addEventListener('click', (e) => {

                const isMulti = this.multiSelectMode || e.ctrlKey || e.metaKey || e.shiftKey;

                if (isMulti) {

                    if (this.selectedClips.has(i)) {

                        if (this.selectedClips.size > 1) {

                            this.selectedClips.delete(i);

                            if (this.selected === i) {

                                this.selected = [...this.selectedClips][0];

                            }

                        }

                    } else {

                        this.selectedClips.add(i);

                        this.selected = i;

                    }

                } else {

                    this.selected = i;

                    this.selectedClips = new Set([i]);

                }

                this.previewClip = this.selected + 1;

                this.galleryPreview = null;

                this.previewJob = null;

                this.previewKind = 'clip';

                this.persist();

                this.render();

            });

        });



        if (this.clipGrid) this.clipGrid.scrollTop = prevScroll;

    }

    drawPreview() {

        if(this.previewKind==='camera'){this.drawCameraPreview();this.drawGallery();return;}

        if(this.cameraTab)this.cameraTab.classList.remove('selected');

        if(this.cameraPreviewSelect)this.cameraPreviewSelect.hidden=true;

        if (this.project) this.galleryProjects.set(this.project.id, this.project);

        if (this.galleryPreview) {

            this.galleryPreview = this.galleryItems().find(item => item.key === this.galleryPreview.key && !item.gallery_deleted) || null;

        }

        const allClips = Object.values(this.project?.clips || {}).sort((a, b) => a.index - b.index);

        const clips = allClips.filter(clip => !clip.gallery_deleted);

        const history = allClips.flatMap(clip => (clip.history || []).filter(old => !old.gallery_deleted)

            .map(old => ({...old, index: clip.index, historic: true})));

        const record = (this.galleryPreview?.kind === 'clip' ? this.galleryPreview : null) || [...clips, ...history].find(clip => clip.job === this.previewJob) ||

            clips.find(clip => clip.index === this.previewClip) || clips.at(-1) || history.at(-1);

        const exports = (this.project?.exports || []).filter(item => !item.gallery_deleted);

        const exportFile = (this.galleryPreview?.kind === 'full' ? this.galleryPreview : null) || exports.find(item => item.job === this.previewExport) || exports.at(-1);

        const path = record?.video;

        this.previewSelect.replaceChildren();

        for (const clip of clips) {

            const option = element('option', `클립 ${clip.index}${clip.stale ? ' · 재생성 필요' : ''}`);

            option.value = String(clip.index); this.previewSelect.append(option);

        }

        this.previewSelect.disabled = !clips.length;

        if (this.galleryPreview && this.galleryPreview.project_id !== this.state.project_id) this.previewSelect.disabled = true;

        this.previewSelect.value = record ? String(record.index) : '';

        if (path && this.video.dataset.path !== path) {

            this.video.src = viewURL(path); this.video.dataset.path = path;

            this.video.load();

        }

        if (!path) { this.video.pause(); this.video.removeAttribute('src'); delete this.video.dataset.path; }

        this.video.hidden = !path;

        this.previewEmpty.hidden = !!path;

        this.previewLabel.textContent = record ? `클립 ${record.index} 결과${record.historic ? ' · 이전 생성 버전' : record.stale ? ' · 이전 결과, 재생성 필요' : ''}` : '완료된 클립이 아직 없습니다.';

        this.clipLink.hidden = !path;

        if (path) this.clipLink.href = viewURL(path);

        const fullPath = exportFile?.video;

        if (fullPath && this.fullVideo.dataset.path !== fullPath) {

            this.fullVideo.src = viewURL(fullPath); this.fullVideo.dataset.path = fullPath;

            this.fullVideo.load();

        }

        if (!fullPath) { this.fullVideo.pause(); this.fullVideo.removeAttribute('src'); delete this.fullVideo.dataset.path; }

        this.fullVideo.hidden = !fullPath;

        this.fullEmpty.hidden = !!fullPath;

        this.fullLabel.textContent = exportFile ? `${exportFile.label || `합본 ${exports.indexOf(exportFile) + 1}`}${exportFile.outdated ? ' · 현재 수정 내용은 미반영' : ' · 전체 영상'}` : '합친 영상이 아직 없습니다.';

        this.exportLink.hidden = !exportFile;

        if (exportFile) this.exportLink.href = viewURL(fullPath);

        if (this.video.error && path) this.previewLabel.textContent = '영상을 불러오지 못했습니다. 원본 파일 열기로 확인하세요.';

        if (this.fullVideo.error && fullPath) this.fullLabel.textContent = '합본을 불러오지 못했습니다. 원본 파일 열기로 확인하세요.';

        const full = this.previewKind === 'full';

        this.clipCard.hidden = full; this.fullCard.hidden = !full;

        (full ? this.video : this.fullVideo).pause();

        this.clipTab.classList.toggle('selected', !full); this.fullTab.classList.toggle('selected', full);

        this.clipTab.setAttribute('aria-pressed', String(!full)); this.fullTab.setAttribute('aria-pressed', String(full));

        this.previewSelect.hidden = full;

        this.previewTitle.textContent = `${this.galleryPreview ? `${this.galleryPreview.project_name} · ` : ''}${full ? this.fullLabel.textContent : this.previewLabel.textContent}`;

        const selectedResult = full ? exportFile : record;

        const job = selectedResult?.job_status || this.project?.jobs[selectedResult?.job];

        const seconds = job?.finished > job?.created ? job.finished - job.created : null;

        this.processingTime.textContent = seconds === null ? '저장된 결과를 선택해 주세요' :

            `처리 시간 ${Math.floor(seconds / 60)}분 ${(seconds % 60).toFixed(1)}초`;

        const previewProject = this.galleryPreview ? this.galleryProjects.get(this.galleryPreview.project_id) : this.project;

        const previewPlan = previewProject?.jobs?.[selectedResult?.job]?.plan || previewProject?.plan || this.state.plan;

        const previewVersion = record && previewProject?.clips?.[String(record.index)];

        const versions = previewVersion ? [...(previewVersion.history || []), previewVersion] : [];

        const version = versions.findIndex(item => item.job === record?.job);

        const previewText = full ? '미리보기 · 전체 합본' : record ?

            `미리보기 · ${nodeLocation(previewPlan, record.index)}${version > 0 ? ` · 재생성 ${version}` : ''}` : '미리보기 · 결과 없음';

        this.previewNodes.draw(previewNodeModel(this.state.plan, this.project, this.selected), {

            live: this.livePreview?.current(),

            previewJob: full ? null : record?.job,

            previewText: this.galleryPreview && this.galleryPreview.project_id !== this.state.project_id ?

                `${this.galleryPreview.project_name} · ${previewText}` : previewText,

            busy: this.busyRequest,

        });

        this.updateVideoMeta();

        this.drawGallery(record?.job, exportFile?.job);

    }



    updateVideoMeta() {

        const media = this.previewKind === 'full' ? this.fullVideo : this.video;

        const resolution = media?.dataset.path && media.readyState >= 1 && media.videoWidth ? `${media.videoWidth} × ${media.videoHeight}` : '';

        this.videoMeta.textContent = resolution;

        this.videoMeta.hidden = !resolution;

    }



    renderPreview() {

        const preview = this.previewArea = element('section', undefined, 'eh3-preview'); this.results.append(preview);

        const toolbar = element('div', undefined, 'eh3-preview-toolbar'); preview.append(toolbar);

        this.clipTab = this.button('클립', () => { this.galleryPreview = null; this.previewKind = 'clip'; this.persist(); this.drawPreview(); }, toolbar);

        this.fullTab = this.button('전체 합본', () => { this.galleryPreview = null; this.previewKind = 'full'; this.persist(); this.drawPreview(); }, toolbar);

        this.cameraTab=this.button('카메라',()=>{this.galleryPreview=null;this.previewKind='camera';this.persist();this.drawPreview();},toolbar);

        this.cameraPreviewSelect=element('select');this.cameraPreviewSelect.setAttribute('aria-label','카메라 원본·결과 선택');toolbar.append(this.cameraPreviewSelect);this.cameraPreviewSelect.hidden=true;

        this.cameraPreviewSelect.addEventListener('change',()=>{this.galleryPreview=null;this.cameraPreviewId=this.cameraPreviewSelect.value;this.persist();this.drawPreview();});

        this.previewSelect = element('select'); this.previewSelect.setAttribute('aria-label', '미리볼 완료 클립'); toolbar.append(this.previewSelect);

        this.previewSelect.addEventListener('change', () => {

            this.galleryPreview = null;

            this.previewClip = Number(this.previewSelect.value); this.selected = this.previewClip - 1;

            this.selectedClips = new Set([this.selected]);

            this.previewJob = null; this.previewKind = 'clip'; this.persist(); this.render();

        });

        this.mergeButton = this.button('합치기', () => this.queue('assemble'), toolbar);

        this.mergeButton.title = '완료된 전체 클립으로 합본만 생성';

        this.previewTitle = element('span', undefined, 'eh3-preview-title'); toolbar.append(this.previewTitle);

        const stage = this.previewStage = element('div', undefined, 'eh3-preview-stage'); preview.append(stage);

        const screen = this.previewScreen = element('div', undefined, 'eh3-viewer'); stage.append(screen);

        this.previewNodes = new PreviewNodes(stage, (index, job) => {

            this.selected = index; this.selectedClips = new Set([index]);

            this.galleryPreview = null; this.previewClip = index + 1;

            this.previewJob = job; this.previewKind = 'clip'; this.persist(); this.render();

        }, this.previewNodes?.activeKey, viewURL);

        this.videoMeta = element('span', undefined, 'eh3-video-meta'); screen.append(this.videoMeta);

        this.clipCard = element('div', undefined, 'eh3-preview-card'); screen.append(this.clipCard);

        this.previewLabel = element('span'); this.previewLabel.hidden = true;

        this.video = element('video'); this.video.setAttribute('aria-label', '클립 영상 미리보기');

        this.video.controls = true; this.video.preload = 'metadata'; this.video.playsInline = true; this.clipCard.append(this.video);

        this.video.addEventListener('loadedmetadata', () => this.updateVideoMeta());

        this.video.addEventListener('error', () => { if (this.video.dataset.path) this.drawPreview(); });

        this.previewEmpty = element('p', '생성한 영상이 여기에 표시됩니다.', 'eh3-preview-empty'); this.clipCard.append(this.previewEmpty);

        this.clipLink = element('a', '↗ 원본 열기'); this.clipLink.target = '_blank'; this.clipLink.rel = 'noopener'; this.clipCard.append(this.clipLink);

        this.fullCard = element('div', undefined, 'eh3-preview-card'); screen.append(this.fullCard);

        this.fullLabel = element('span'); this.fullLabel.hidden = true;

        this.fullVideo = element('video'); this.fullVideo.setAttribute('aria-label', '전체 합본 미리보기');

        this.fullVideo.controls = true; this.fullVideo.preload = 'metadata'; this.fullVideo.playsInline = true; this.fullCard.append(this.fullVideo);

        this.fullVideo.addEventListener('loadedmetadata', () => this.updateVideoMeta());

        this.fullVideo.addEventListener('error', () => { if (this.fullVideo.dataset.path) this.drawPreview(); });

        this.fullEmpty = element('p', '전체 합치기를 완료하면 표시됩니다.', 'eh3-preview-empty'); this.fullCard.append(this.fullEmpty);

        this.exportLink = element('a', '↗ 원본 열기'); this.exportLink.target = '_blank'; this.exportLink.rel = 'noopener'; this.fullCard.append(this.exportLink);

        this.processingTime = element('div', undefined, 'eh3-processing-time'); preview.append(this.processingTime);

        this.processingTime.title = '작업 접수부터 저장 완료까지의 시간입니다. 큐 대기와 저장 시간이 포함됩니다.';

        const gallery = this.outputGallery = element('section', undefined, 'eh3-output-gallery'); this.results.append(gallery);

        const header = element('div', undefined, 'eh3-gallery-header'); gallery.append(header);

        header.append(element('strong', 'OUTPUTS'));

        this.galleryCount = element('span', undefined, 'eh3-help'); header.append(this.galleryCount);

        this.button('↻ 새로고침', async () => {

            await this.refresh();

            await this.refreshGallery();

            for (const media of [this.video, this.fullVideo]) {

                if (media.dataset.path) { media.src = `${viewURL(media.dataset.path)}&t=${Date.now()}`; media.load(); }

            }

        }, header);

        this.favoriteButton = this.button('☆ 즐겨찾기', () => this.outputAction('favorite'), header);

        this.favoriteButton.title = '선택한 결과를 즐겨찾기에 추가 · 모두 즐겨찾기이면 해제';

        this.storageButton = this.button('↗ 저장소', async () => {

            await request('storage', {project_id: this.galleryPreview?.project_id || this.state.project_id});

            this.notice('ComfyUI가 실행 중인 PC에서 프로젝트 출력 폴더를 열었습니다.', false);

        }, header);

        this.storageButton.title = '미리보기 영상의 프로젝트 출력 폴더 열기';

        this.deleteButton = this.button('삭제', () => this.outputAction('trash'), header);

        this.deleteButton.title = '체크한 결과를 휴지통으로 이동 · 연결 데이터 유지';

        this.outputUpscaleButton = this.button('선택 영상 업스케일', () => this.upscaleOutput(), header);

        this.outputUpscaleButton.title = '전체 합본 한 개를 선택 · 현재 업스케일 설정으로 새 결과 저장';

        const tools = element('div', undefined, 'eh3-gallery-tools'); gallery.append(tools);

        this.galleryScopeSelect = element('select'); tools.append(this.galleryScopeSelect);

        this.galleryScopeSelect.setAttribute('aria-label', '아웃풋 프로젝트 범위');

        for (const [value, text] of [['all', '전체 프로젝트'], ['current', '현재 프로젝트만']]) {

            const option = element('option', text); option.value = value; this.galleryScopeSelect.append(option);

        }

        this.galleryScopeSelect.value = this.galleryScope;

        this.galleryScopeSelect.addEventListener('change', () => {

            this.galleryScope = this.galleryScopeSelect.value; this.outputSelection.clear();

            this.galleryPreview = null; this.persist(); this.drawPreview();

        });

        const all = element('label', undefined, 'eh3-output-check'); tools.append(all);

        this.selectAllOutputs = element('input'); this.selectAllOutputs.type = 'checkbox';

        this.selectAllOutputs.setAttribute('aria-label', '아웃풋 전체 선택'); all.append(this.selectAllOutputs, element('span', '전체 선택'));

        this.selectAllOutputs.addEventListener('change', () => {

            for (const item of this.visibleOutputs || []) {

                if (this.selectAllOutputs.checked && !item.busy) this.outputSelection.add(item.key);

                else this.outputSelection.delete(item.key);

            }

            this.updateOutputTools();

        });

        this.favoriteFilter = this.button('☆ 즐겨찾기만', () => {

            this.favoritesOnly = !this.favoritesOnly; this.drawPreview();

        }, tools);

        this.restoreOutputsButton = this.button('휴지통', () => this.showOutputTrash(), tools);

        this.galleryList = element('div', undefined, 'eh3-gallery-grid'); gallery.append(this.galleryList);

        this.galleryKey = null;

    }



    async refreshGallery() {

        if (this.disposed) return;

        if (this.galleryRequest) return this.galleryRequest;

        this.galleryRequest = (async () => {

            const {projects} = await request('projects');

            this.config.projects = projects;

            const ids = new Set(projects.map(p => p.id));

            for (const id of this.galleryProjects.keys()) if (!ids.has(id)) this.galleryProjects.delete(id);

            const pending = projects.filter(p => this.galleryProjects.get(p.id)?.updated !== p.updated);

            const failed = [];

            // Bound metadata requests; videos load only when their thumbnails are visible.

            for (let i = 0; i < pending.length; i += 4) {

                await Promise.all(pending.slice(i, i + 4).map(async p => {

                    try {

                        const result = await request(`project/${p.id}`);

                        if (!this.disposed) this.galleryProjects.set(p.id, {id: result.id, name: result.name,

                            updated: result.updated, clips: result.clips, exports: result.exports,

                            jobs: result.jobs, active: result.active, batch: result.batch});

                    } catch { failed.push(p.name); }

                }));

                if (this.disposed) return;

            }

            if (!this.disposed) {

                this.drawPreview();

                if (failed.length) this.notice(`${failed.length}개 프로젝트 목록을 불러오지 못했습니다. 새로고침으로 다시 시도해 주세요.`);

            }

        })();

        try { await this.galleryRequest; } finally { this.galleryRequest = null; }

    }



    galleryItems() {

        const projects = this.galleryScope === 'current' ? (this.project ? [this.project] : []) : [...this.galleryProjects.values()];

        const cameras=this.cameraItems().filter(item=>this.galleryScope!=='current'||item.project_id===(this.state.project_id||''));

        return projects.flatMap(galleryOutputs).concat(cameras).sort((a, b) => (b.created || 0) - (a.created || 0) || a.key.localeCompare(b.key));

    }



    drawGallery(clipJob, exportJob) {

        const all = this.galleryItems();

        this.trashedOutputs = all.filter(item => item.gallery_deleted);

        const available = all.filter(item => !item.gallery_deleted);

        const items = this.visibleOutputs = available.filter(item => !this.favoritesOnly || item.favorite);

        const valid = new Set(items.map(item => item.key));

        for (const job of this.outputSelection) if (!valid.has(job)) this.outputSelection.delete(job);

        const stamp = JSON.stringify([this.galleryScope, this.favoritesOnly, items.map(item => [item.key, item.project_name, item.video, !!item.favorite, !!item.stale, !!item.outdated])]);

        if (stamp !== this.galleryKey) {

            this.galleryObserver?.disconnect();

            this.galleryKey = stamp; this.galleryList.replaceChildren();

            this.galleryObserver = new IntersectionObserver(entries => {

                for (const entry of entries) {

                    const video = entry.target;

                    if (entry.isIntersecting && !video.getAttribute('src')) {

                        video.src = video.dataset.src; video.load();

                    } else if (!entry.isIntersecting && video.getAttribute('src')) {

                        video.pause(); video.removeAttribute('src'); video.load();

                    }

                }

            }, {root: this.results, rootMargin: '80px'});

            for (const item of items) {

                const tile = element('div', undefined, 'eh3-gallery-tile'); this.galleryList.append(tile);

                tile.dataset.key = item.key;

                const card = this.button('', () => {

                    this.galleryPreview = item;

                    this.previewKind = item.kind;

                    if(item.kind==='camera')this.cameraPreviewId=item.job;

                    if (item.kind!=='camera'&&item.project_id === this.state.project_id) {

                        if (item.kind === 'clip') { this.previewClip = item.index; this.previewJob = item.job; this.selected = item.index - 1; this.selectedClips = new Set([this.selected]); }

                        else this.previewExport = item.job;

                    }

                    this.persist();

                    if (item.project_id === this.state.project_id) this.render(); else this.drawPreview();

                    (item.kind !== 'full' ? this.video : this.fullVideo).scrollIntoView({block: 'nearest'});

                }, tile, 'eh3-gallery-card');

                card.setAttribute('aria-label', `${item.project_name} · ${item.label} 보기`);

                card.title = `${item.project_name} · ${item.label}${item.created ? ` · ${new Date(item.created * 1000).toLocaleString('ko-KR')}` : ''}`;

                card.dataset.kind = item.kind; card.dataset.job = item.job; card.dataset.key = item.key;

                const thumbnail = element('video'); thumbnail.preload = 'metadata'; thumbnail.muted = true;

                thumbnail.playsInline = true; thumbnail.setAttribute('aria-hidden', 'true');

                thumbnail.dataset.src = viewURL(item.video); card.append(thumbnail);

                card.append(element('span', item.project_name, 'eh3-gallery-project'), element('strong', `${item.favorite ? '★ ' : ''}${item.label}`), element('span',

                    item.historic ? '이전 생성 버전' : item.stale ? '재생성 필요' : item.outdated ? '수정 전 합본' : '저장 완료'));

                this.galleryObserver.observe(thumbnail);

                const check = element('input', undefined, 'eh3-gallery-check'); check.type = 'checkbox';

                check.setAttribute('aria-label', `${item.label} 선택`); tile.append(check);

                check.addEventListener('change', () => {

                    if (check.checked) this.outputSelection.add(item.key); else this.outputSelection.delete(item.key);

                    this.updateOutputTools();

                });

            }

            if (!items.length) this.galleryList.append(element('p', this.favoritesOnly ? '즐겨찾기 결과가 없습니다.' : '생성된 결과가 여기에 쌓입니다.', 'eh3-help'));

        }

        for (const card of this.galleryList.querySelectorAll('button')) {

            const selected = this.galleryPreview ? card.dataset.key === this.galleryPreview.key :

                card.dataset.kind==='camera' ? this.previewKind==='camera'&&card.dataset.job===this.cameraPreviewId :

                card.dataset.key === `${this.state.project_id}:${card.dataset.kind === 'clip' ? clipJob : exportJob}` && card.dataset.kind === this.previewKind;

            card.classList.toggle('selected', selected); card.setAttribute('aria-pressed', String(selected));

        }

        this.updateOutputTools();

    }



    updateOutputTools() {

        const supported = !!this.config.output_tools_supported;

        const busy = this.busyRequest || (this.visibleOutputs || []).some(item => this.outputSelection.has(item.key) && item.busy);

        const count = this.outputSelection.size;

        this.galleryCount.textContent = `${this.visibleOutputs?.length || 0}개${count ? ` · ${count}개 선택` : ''}`;

        this.deleteButton.textContent = count ? `삭제 (${count})` : '삭제';

        this.favoriteButton.disabled = this.deleteButton.disabled = !supported || !!busy || !count;

        this.storageButton.disabled = !supported || !(this.galleryPreview?.project_id || this.state.project_id);

        const upscaleTarget = this.outputUpscaleTarget();

        this.outputUpscaleButton.disabled = !this.config.output_upscale_supported || this.busyRequest ||

            !!this.pendingOutputUpscale || !upscaleTarget || upscaleTarget.busy;

        this.outputUpscaleButton.textContent = this.pendingOutputUpscale ? '업스케일 진행 중' : '선택 영상 업스케일';

        this.outputUpscaleButton.title = !this.config.output_upscale_supported ? 'ComfyUI 재시작 후 사용할 수 있습니다.' :

            upscaleTarget ? `${upscaleTarget.project_name} · ${upscaleTarget.label} · ${this.state.plan.settings.scale}배 새 결과 저장` :

                '갤러리에서 전체 합본 한 개를 클릭하거나 체크해 주세요.';

        this.restoreOutputsButton.textContent = `휴지통${this.trashedOutputs?.length ? ` (${this.trashedOutputs.length})` : ''}`;

        this.restoreOutputsButton.disabled = !supported || this.busyRequest || !this.trashedOutputs?.length;

        this.selectAllOutputs.disabled = !supported || !!busy || !this.visibleOutputs?.length;

        const selectable = (this.visibleOutputs || []).filter(item => !item.busy);

        const marked = selectable.filter(item => this.outputSelection.has(item.key)).length;

        this.selectAllOutputs.checked = marked > 0 && marked === selectable.length;

        this.selectAllOutputs.indeterminate = marked > 0 && marked < selectable.length;

        this.favoriteFilter.classList.toggle('selected', this.favoritesOnly);

        this.favoriteFilter.setAttribute('aria-pressed', String(this.favoritesOnly));

        for (const tile of this.galleryList.querySelectorAll('.eh3-gallery-tile')) {

            const selected = this.outputSelection.has(tile.dataset.key);

            tile.classList.toggle('checked', selected);

            const checkbox = tile.querySelector('input'); checkbox.checked = selected;

            checkbox.disabled = !supported || this.busyRequest || !!this.visibleOutputs.find(item => item.key === tile.dataset.key)?.busy;

        }

        if (!supported) this.deleteButton.title = '현재 생성이 끝난 후 ComfyUI를 재시작하면 사용할 수 있습니다.';

    }



    outputUpscaleTarget() {

        let preview = this.galleryPreview;

        if (!preview && this.previewKind === 'full') {

            preview = this.galleryItems().find(item => item.project_id === this.state.project_id &&

                item.kind === 'full' && item.video === this.fullVideo.dataset.path);

        }

        return outputUpscaleTarget(this.galleryItems(), this.outputSelection, preview);

    }



    async upscaleOutput() {

        if (this.busyRequest || this.pendingOutputUpscale) return;

        const item = this.outputUpscaleTarget();

        if (!item || item.busy) throw new Error('생성이 끝난 전체 합본 한 개를 선택해 주세요.');

        this.busyRequest = true; this.updateStatus();

        try {

            const result = await request('upscale_output', {project_id: item.project_id, source_job: item.job,

                settings: this.state.plan.settings, client_id: api.clientId});

            this.galleryProjects.set(item.project_id, result.project);

            if (item.project_id === this.state.project_id) this.project = result.project;

            this.pendingOutputUpscale = {project_id: item.project_id, job_id: result.job_id};

            this.drawPreview();

            this.notice(`${item.project_name} · ${item.label} 업스케일 예약 · 원본 유지`, false);

        } finally { this.busyRequest = false; if (!this.disposed) this.updateStatus(); }

    }



    async refreshOutputUpscale() {

        if (this.outputUpscalePolling || !this.pendingOutputUpscale) return;

        this.outputUpscalePolling = true;

        const pending = this.pendingOutputUpscale;

        try {

            const p = await request(`project/${pending.project_id}`);

            if (this.disposed || this.pendingOutputUpscale !== pending) return;

            this.galleryProjects.set(p.id, p);

            if (p.id === this.state.project_id) this.project = p;

            const job = p.jobs[pending.job_id];

            if (job && ['completed', 'failed', 'cancelled'].includes(job.state)) {

                this.pendingOutputUpscale = null;

                if (job.state === 'completed') {

                    const item = galleryOutputs(p).find(item => item.job === pending.job_id);

                    this.outputSelection.clear(); this.galleryPreview = item; this.previewKind = 'full';

                    if (p.id === this.state.project_id) this.previewExport = item.job;

                    this.persist(); this.notice('업스케일 완료 · 새 결과가 갤러리에 추가됐습니다.', false);

                } else this.notice(job.error || '업스케일이 중단됐습니다. 원본은 유지됩니다.');

            }

            this.drawPreview();

        } finally { this.outputUpscalePolling = false; }

    }



    async outputAction(action, keys = [...this.outputSelection]) {

        if (this.busyRequest || !keys.length) return;

        const selected = this.galleryItems().filter(item => keys.includes(item.key));

        if (selected.length !== keys.length) throw new Error('선택한 결과가 변경됐습니다. 새로고침해 주세요.');

        if (selected.some(item => item.busy)) throw new Error('선택한 프로젝트 생성이 끝난 후 아웃풋을 정리해 주세요.');

        const groups = new Map();

        for (const item of selected) {

            if(item.kind==='camera'){const record=this.node.properties.endless_camera_window.results.find(result=>result.job===item.job);if(action==='favorite')record.favorite=!record.favorite;else if(action==='trash')record.gallery_deleted=true;else if(action==='restore')record.gallery_deleted=false;continue;}

            if (!groups.has(item.project_id)) groups.set(item.project_id, []);

            groups.get(item.project_id).push(item.job);

        }

        this.busyRequest = true; this.updateStatus();

        try {

            for (const [project_id, jobs] of groups) {

                const p = await request('outputs', {project_id, action, jobs});

                this.galleryProjects.set(project_id, p);

                if (project_id === this.state.project_id) this.project = p;

            }

            this.outputDialog?.close();

            if (action !== 'favorite') this.outputSelection.clear();

            this.persist();

        } finally { this.busyRequest = false; if (!this.disposed) this.render(); }

        this.notice(action === 'trash' ? `${keys.length}개를 휴지통으로 옮겼습니다. 연결 데이터는 유지됩니다.` :

            action === 'restore' ? `${keys.length}개를 복원했습니다.` : '즐겨찾기를 변경했습니다.', false);

    }



    showOutputTrash() {

        this.outputDialog?.close();

        const dialog = this.outputDialog = element('dialog', undefined, 'eh3-dialog eh3-trash-dialog'); this.root.append(dialog);

        dialog.setAttribute('aria-label', '아웃풋 휴지통');

        const header = element('div', undefined, 'eh3-settings-header'); dialog.append(header);

        header.append(element('h3', '휴지통'));

        this.button('닫기', () => dialog.close(), header);

        const selected = new Set();

        const list = element('div', undefined, 'eh3-trash-list'); dialog.append(list);

        for (const item of this.trashedOutputs || []) {

            const row = element('label', undefined, 'eh3-trash-item'); list.append(row);

            const check = element('input'); check.type = 'checkbox'; check.setAttribute('aria-label', `${item.project_name} · ${item.label} 복원 선택`);

            check.disabled = item.busy;

            row.append(check, element('span', `${item.project_name} · ${item.label}${item.busy ? ' · 생성 중' : ''}`));

            check.addEventListener('change', () => {

                if (check.checked) selected.add(item.key); else selected.delete(item.key);

                restore.disabled = !selected.size; restore.textContent = selected.size ? `선택 복원 (${selected.size})` : '선택 복원';

            });

        }

        const restore = this.button('선택 복원', () => this.outputAction('restore', [...selected]), dialog); restore.disabled = true;

        dialog.addEventListener('close', () => { dialog.remove(); if (this.outputDialog === dialog) this.outputDialog = null; });

        dialog.showModal();

    }



    async refreshAssets(scope) {

        if (this.assetRefreshing) return;

        this.assetRefreshing = true;

        this.referenceDialog?.close();

        this.root.querySelectorAll('.eh3-asset-refresh').forEach(button => { button.disabled = true; });

        try {

            const result = await request('assets_refresh', {scope});

            if (this.disposed) return;

            Object.assign(this.config.models, result.models);

            this.assetSelectors = (this.assetSelectors || []).filter(item => item.input.isConnected);

            for (const item of this.assetSelectors) {

                if (!result.models[item.asset]) continue;

                const files = item.filter ? result.models[item.asset].filter(item.filter) : result.models[item.asset];

                this.options(item.input, files, item.input.value, item.emptyLabel);

                item.input.dispatchEvent(new Event('files-refreshed'));

            }

            this.notice(`${scope === 'loras' ? 'LoRA' : '모델'} 목록을 새로고침했습니다.`, false);

        } finally {

            this.assetRefreshing = false;

            this.root.querySelectorAll('.eh3-asset-refresh').forEach(button => { button.disabled = !this.config.asset_refresh_supported; });

        }

    }



    requireClipRefinerBackend() {

        if (!this.config.clip_refiner_per_clip_only) {

            throw new Error('클립별 리파이너를 적용하려면 현재 작업이 끝난 뒤 ComfyUI를 재시작하고 새로고침해 주세요.');

        }

    }



    async queue(action) {

        if ((this.state.plan.sequence_mode || this.state.plan.scenes?.length > 1) && !this.config.sequence_mode_supported) throw new Error('ComfyUI 재시작 후 씬 계획을 생성하거나 저장해 주세요.');

        if (this.busyRequest || this.project?.active || this.project?.batch?.state === 'running'||this.cameraWindow?.running||this.cameraWindow?.submitting) return;

        if (action !== 'assemble') this.requireClipRefinerBackend();

        this.state.resolution = migrateResolutionPreset(this.state.plan.settings, this.state.resolution, !!this.project?.geometry);

        syncReferences(this.state.plan);

        this.busyRequest = true; this.updateStatus();

        try {

            if (!this.state.project_id) {

                const p = await request('project', {name: this.state.name, plan: this.state.plan});

                this.state.project_id = p.id; this.project = p; this.persist();

            }

            const restart = action === 'restart_background';

            const batch = action === 'all' || action === 'all_assemble' || restart;

            const result = await request(batch ? 'batch' : 'queue', {project_id: this.state.project_id,

                plan: this.state.plan, action, assemble: action === 'all_assemble' || (restart && this.generationMode === 'all_assemble'),

                ...(restart ? {restart_clip: this.selected + 1} : {}),

                index: this.selected + 1, client_id: api.clientId});

            this.project = result.project; this.dirty = false; this.persist(); this.render();

        } finally { this.busyRequest = false; if (!this.disposed) this.render(); }

    }



    async showNodes() {

        if (this.busyRequest) return;

        this.requireClipRefinerBackend();

        if (typeof app.loadApiJson !== 'function' || typeof app.loadGraphData !== 'function') {

            throw new Error('현재 ComfyUI 화면에서 노드 전환을 지원하지 않습니다.');

        }

        const graph = app.rootGraph || app.graph;

        if (!graph?.serialize || this.node.graph !== graph) throw new Error('루트 워크플로우에서 올인원 노드를 열어 주세요.');

        const index = this.selected + 1;

        const plan = clone(this.state.plan);

        const projectId = this.state.project_id;

        const signature = JSON.stringify({plan, index,

            clips: this.project?.clips || {}});

        const cached = this.node.properties.endless_node_views?.[String(index)];

        this.busyRequest = true; this.updateStatus();

        try {

            const result = await request('node_graph', {plan, project_id: projectId, index});

            if (this.disposed || (app.rootGraph || app.graph) !== graph) return;

            if (projectId !== this.state.project_id || index !== this.selected + 1 ||

                JSON.stringify(plan) !== JSON.stringify(this.state.plan)) {

                throw new Error('계획이 변경됐습니다. 노드 보기 버튼을 다시 눌러 주세요.');

            }

            this.persist();

            const origin = clone(graph.serialize());

            const view = {origin, node_id: this.node.id, index, signature,

                          name: this.state.name, warnings: result.warnings};

            try {

                if (cached?.signature === signature) {

                    const draft = clone(cached.workflow);

                    draft.extra ||= {}; draft.extra[graphViewKey] = view;

                    await app.loadGraphData(draft, true, true, `${view.name} · 클립 ${view.index} 노드.json`);

                } else {

                    await app.loadApiJson(result.prompt, `${view.name} · 클립 ${view.index} 노드.json`);

                    const nativeGraph = app.rootGraph || app.graph;

                    nativeGraph.extra ||= {}; nativeGraph.extra[graphViewKey] = view;

                    nativeGraph.setDirtyCanvas(true, true);

                }

                showGraphViewBar();

            } catch (error) {

                await app.loadGraphData(origin, true, true, `${view.name} · 올인원.json`);

                throw error;

            }

        } finally {

            this.busyRequest = false;

            if (!this.disposed) this.updateStatus();

        }

    }



    async uploadReferences(files, kind, available, apply) {

        if (!files.length) return;

        if (this.busyRequest || this.project?.active || this.project?.batch?.state === 'running') {

            this.notice('현재 작업이 끝난 후 참고 파일을 바꿔 주세요.'); return;

        }

        if (files.length > available) { this.notice(`이 항목에는 ${available}개를 더 추가할 수 있습니다.`); return; }

        const extensions = {image: /\.(png|jpe?g|webp|gif|bmp|tiff?|avif)$/i,

            video: /\.(mp4|webm|mov|mkv|avi|m4v)$/i, audio: /\.(wav|mp3|flac|ogg|m4a|aac|opus)$/i}[kind];

        if (files.some(file => !extensions.test(file.name))) { this.notice('이 항목에 맞는 참고 파일을 선택해 주세요.'); return; }

        this.busyRequest = true; this.updateStatus();

        const names = [];

        let applied = false, failure;

        try {

            for (const file of files) {

                const form = new FormData(); form.append('image', file); form.append('type', 'input'); form.append('overwrite', 'false');

                const response = await api.fetchApi('/upload/image', {method: 'POST', body: form});

                const data = await response.json(); if (!response.ok) throw new Error(data.error || '참고 파일 업로드 실패');

                const name = data.subfolder ? `${data.subfolder}/${data.name}` : data.name;

                names.push(name);

                const library = this.config[{image: 'images', video: 'videos', audio: 'audio_files'}[kind]] ||= [];

                if (!library.includes(name)) library.push(name);

            }

            if (!this.disposed) { apply(names); this.changed(); applied = true; }

        } catch (error) {

            failure = `${error.message}${names.length ? ` · ${names.length}개 업로드 완료 파일은 기존 파일 선택에서 다시 추가할 수 있습니다.` : ''}`;

        } finally {

            this.busyRequest = false;

            if (!this.disposed) {

                if (applied) this.render(); else this.updateStatus();

                if (failure) this.notice(failure);

            }

        }

    }



    pickReferences(kind, available, apply) {

        const chooser = element('input'); chooser.type = 'file';

        chooser.accept = {image: 'image/*', video: 'video/*,.mkv,.avi,.m4v', audio: 'audio/*,.m4a,.flac,.opus'}[kind]; chooser.multiple = available > 1;

        chooser.addEventListener('change', () => this.uploadReferences([...chooser.files], kind, available, apply));

        chooser.click();

    }



    referenceLibrary(kind, apply) {

        const label = {image: '이미지', video: '비디오', audio: '오디오'}[kind];

        const view = this.captureScroll();

        const files = this.config[{image: 'images', video: 'videos', audio: 'audio_files'}[kind]] || [];

        this.searchFiles(`기존 ${label}`, files.map(name => ({value: name, label: name})), null, name => {

            if (this.busyRequest || this.project?.active || this.project?.batch?.state === 'running') throw new Error('현재 작업이 끝난 후 참고 파일을 바꿔 주세요.');

            apply([name]); this.changed(); this.render(view);

        }, '참고 파일 검색', `기존 ${label} 파일`);

    }



    referenceCards(parent, label, kind, entries, limit, apply, change, audioOffset = 0) {

        const panel = element('section', undefined, `eh3-references eh3-references-${kind}`); parent.append(panel);

        const header = element('div', undefined, 'eh3-reference-header'); panel.append(header);

        header.append(element('h4', `${label} (${entries.length}/${limit})`));

        if (entries.length < limit) this.button('기존 파일 선택', () => this.referenceLibrary(kind, apply), header);

        const grid = element('div', undefined, 'eh3-reference-grid'); panel.append(grid);

        entries.forEach((entry, i) => {

            const name = typeof entry === 'string' ? entry : entry.name;

            const tag = limit === 1 ? label : `${{image: 'Picture', video: 'Video', audio: 'Audio'}[kind]} ${i + 1 + audioOffset}`;

            const card = element('div', undefined, 'eh3-reference-card'); card.title = `${tag} · ${name}`; grid.append(card);

            const media = element(kind === 'image' ? 'img' : kind); media.src = viewURL(name, 'input');

            if (kind === 'image') { media.alt = `${tag} · ${name}`; media.loading = 'lazy'; }

            else { media.controls = true; media.muted = kind === 'video'; media.preload = 'metadata'; media.playsInline = true; }

            if (kind === 'audio') card.append(element('div', '♪', 'eh3-reference-audio-art'));

            const failure = element('span', '미리보기를 불러올 수 없습니다.', 'eh3-reference-error'); failure.hidden = true;

            media.addEventListener('error', () => { failure.hidden = false; });

            card.append(media, failure);

            this.button('×', () => { const next = [...entries]; next.splice(i, 1); change(next); this.changed(); this.render(); }, card, 'eh3-reference-remove')

                .setAttribute('aria-label', `${tag} 삭제`);

            const footer = element('div', undefined, 'eh3-reference-footer'); card.append(footer);

            footer.append(element('strong', tag));

            const file = element('span', name, 'eh3-reference-name'); file.title = name; footer.append(file);

            if (limit > 1) {

                const order = element('div', undefined, 'eh3-reference-order'); footer.append(order);

                const move = offset => {

                    const next = [...entries]; [next[i], next[i + offset]] = [next[i + offset], next[i]];

                    change(next); this.changed(); this.render();

                };

                if (i > 0) this.button('←', () => move(-1), order).setAttribute('aria-label', `${tag} 앞으로 이동`);

                if (i < entries.length - 1) this.button('→', () => move(1), order).setAttribute('aria-label', `${tag} 뒤로 이동`);

            }

            if (kind === 'video') {

                const audioNumber = entries.slice(0, i).filter(v => v.use_audio).length + 1;

                const sound = this.button(entry.use_audio ? `소리 참고 ON · Audio ${audioNumber}` : '소리 참고 OFF', () => {

                    const next = [...entries]; next[i] = {...entry, use_audio: !entry.use_audio};

                    change(next); this.changed(); this.render();

                }, footer, entry.use_audio ? 'selected' : '');

                sound.setAttribute('aria-pressed', String(!!entry.use_audio)); sound.setAttribute('aria-label', `${tag} 소리 참고`);

            }

        });

        if (entries.length < limit) {

            const add = this.button('+', () => this.pickReferences(kind, limit - entries.length, apply), grid, 'eh3-reference-add');

            add.setAttribute('aria-label', `${label} 추가`); add.title = '클릭해 업로드 · 파일을 끌어놓아도 추가됩니다.';

        }

        panel.addEventListener('dragover', event => { if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); event.stopPropagation(); } });

        panel.addEventListener('drop', event => {

            if (!event.dataTransfer?.files.length) return;

            event.preventDefault(); event.stopPropagation();

            this.uploadReferences([...event.dataTransfer.files], kind, limit - entries.length, apply);

        });

    }



    imageField(parent, label, target, key) {

        this.referenceCards(parent, label, 'image', target[key] ? [target[key]] : [], 1,

            names => { target[key] = names[0]; }, entries => { target[key] = entries[0] || ''; });

    }



    async generate() {

        if(this.generationMode==='camera'){

            if(this.busyRequest||this.project?.active||this.project?.batch?.state==='running'||this.cameraWindow?.running||this.cameraWindow?.submitting)return;

            const refs=this.cameraReferences();if(!refs.length)throw Error('R2V 참고 비디오를 먼저 넣어 주세요.');

            this.busyRequest=true;this.updateStatus();

            try{

                const camera=this.cameraController();camera.setReferences(refs);await camera.ready();

                if(!camera.sources.includes(camera.state.widgets.source_video))camera.useSource(camera.sources[0]);

                if(!this.state.project_id){const project=await request('project',{name:this.state.name,plan:this.state.plan});this.state.project_id=project.id;this.project=project;this.persist();}

                await camera.queue();

            }finally{this.busyRequest=false;this.updateStatus();}

            return;

        }

        // A single selected clip also uses retry for first-time generation; the server

        // enforces that all preceding AV context is available before queueing.

        await this.queue(this.generationMode === 'clip' ? 'retry' : this.generationMode);

    }



    async scheduleNext() {

        if (this.busyRequest || !this.project?.active) return;

        const batch = this.project.batch;

        const enabled = !(batch?.state === 'running' && batch.kind === 'scheduled_clip');

        if (enabled) this.requireClipRefinerBackend();

        this.busyRequest = true; this.updateStatus();

        try {

            const result = await request('schedule', {project_id: this.state.project_id,

                plan: this.state.plan, enabled, client_id: api.clientId});

            this.project = result.project; this.persist();

        } finally { this.busyRequest = false; if (!this.disposed) this.render(); }

    }



    renderInputFiles() {

        this.cameraButton = null;

        const c = this.state.plan.clips[this.selected];

        const panel = this.inputPanel = this.collapsible(this.inputRail, 'inputs',

            `입력 파일 · ${clipLabel(this.state.plan, this.selected)} · ${c.mode}`, 'eh3-input-files');

        const toolbar = element('div', undefined, 'eh3-input-toolbar');

        const content = element('div', undefined, 'eh3-input-content');

        const media = element('div', undefined, 'eh3-input-media');

        const utilities = element('div', undefined, 'eh3-input-utilities');

        panel.append(toolbar, content); content.append(media, utilities);

        if (c.mode === 'I2V' && !continuesAt(this.state.plan, this.selected)) this.imageField(media, '첫 클립 시작 이미지', c, 'first_image');

        if (c.mode === 'I2V' && continuesAt(this.state.plan, this.selected)) toolbar.append(element('p', '시작은 이전 클립에서 이어집니다.', 'eh3-help'));

        if (c.mode === 'R2V') {

            const commonLabel = this.state.plan.sequence_mode ? '씬 공통 참고' : '공통 참고';

            const scope = {value: c.use_common_references ? commonLabel : '클립 전용'};

            const select = this.field(toolbar, '참고 적용', scope, 'value', {items: [commonLabel, '클립 전용']});

            select.addEventListener('change', () => {

                c.use_common_references = scope.value === commonLabel;

                if (!c.use_common_references) {

                    for (const key of ['images', 'videos', 'audios']) c[key] = clone(referenceSource(this.state.plan, c)[key]);

                }

                this.changed(); this.render();

            });

            const refs = c.use_common_references ? referenceSource(this.state.plan, c) : c;

            toolbar.append(element('p', c.use_common_references

                ? '프롬프트의 <Picture N> 자동 선택'

                : `클립 ${this.selected + 1}에만 적용`, 'eh3-help'));

            this.referenceSelection = element('p', undefined, 'eh3-help'); toolbar.append(this.referenceSelection);

            refs.images = (refs.images || []).filter(Boolean); refs.videos = (refs.videos || []).map(v => typeof v === 'string' ? {name: v, use_audio: false} : v).filter(v => v?.name); refs.audios = (refs.audios || []).filter(Boolean);

            this.referenceCards(media, '참고 이미지', 'image', refs.images, 9,

                names => { refs.images.push(...names); }, entries => { refs.images = entries; });

            this.referenceCards(media, '참고 비디오', 'video', refs.videos, 3,

                names => { refs.videos.push(...names.map(name => ({name, use_audio: false}))); }, entries => { refs.videos = entries; });

            this.referenceCards(media, '참고 오디오', 'audio', refs.audios, 3,

                names => { refs.audios.push(...names); }, entries => { refs.audios = entries; }, refs.videos.filter(v => v.use_audio).length);

            panel.title = '공통 이미지는 프롬프트에 적힌 Picture 번호만 자동 전달합니다. 사용하지 않는 이미지는 흐리게 표시합니다. 모델에 전달할 때 선택된 이미지와 프롬프트 번호를 함께 변환하므로 원본 프롬프트는 바뀌지 않습니다. 비디오·오디오는 공통 목록 전체를 참고합니다. 클립 전용은 이 클립만 변경합니다.';

            this.updateReferenceSelection();

            this.cameraButton = this.button('카메라 디렉팅 ▣', () => this.openCameraDirecting(), this.controls, 'eh3-camera-button');

            this.cameraButton.dataset.ready = String(refs.videos.length > 0);

            this.cameraButton.setAttribute('aria-expanded', String(!!this.cameraWindow && !this.cameraWindow.root.hidden));

            this.cameraButton.setAttribute('aria-label', '4번 카메라 디렉팅 창 열기');

            this.cameraButton.title = refs.videos.length

                ? '왼쪽에 4번 카메라 설정 창을 엽니다. 창을 여는 것만으로 생성하지 않습니다.'

                : 'R2V 참고 비디오를 추가하면 활성화됩니다.';

        } else if (c.mode === 'I2V') this.imageField(media, '끝 이미지 · 선택 사항', c, 'last_image');

        this.renderBackgroundRefresh(utilities, c);

        this.renderLipSync(utilities);

    }



    cameraController(){return this.cameraWindow ||= new StudioCameraWindow(this,api);}

    cameraReferences(){

        const clip=this.state.plan.clips[this.selected];if(clip?.mode!=='R2V')return [];

        return (clip.use_common_references?referenceSource(this.state.plan,clip):clip).videos||[];

    }

    cameraItems(){

        return (this.node.properties.endless_camera_window?.results||[]).map((item,index)=>({...item,kind:'camera',key:`camera:${item.job}`,label:`카메라 디렉팅 ${index+1}`,project_id:item.project_id||'',project_name:item.project_name||'카메라',video:(item.subfolder?item.subfolder+'/':'')+item.filename,busy:false,job_status:{created:item.created,finished:item.finished}}));

    }

    drawCameraPreview(){

        const camera=this.cameraWindow,state=camera?.state||this.node.properties.endless_camera_window||{};

        const items=this.cameraItems().filter(item=>!item.gallery_deleted);

        if(this.galleryPreview?.kind==='camera')this.galleryPreview=items.find(item=>item.key===this.galleryPreview.key)||null;

        const chosen=this.galleryPreview?.kind==='camera'?this.galleryPreview:items.find(item=>item.job===this.cameraPreviewId);

        const live=this.cameraPreviewId==='live'?state.segmentPreview:null;

        const source=state.widgets?.source_video;

        const path=chosen?.video||(live?(live.subfolder?live.subfolder+'/':'')+live.filename:source);

        const type=chosen?'output':live?'temp':'input';

        this.cameraPreviewSelect.replaceChildren();

        for(const [value,label] of [['source','참고 비디오'],...(state.segmentPreview?[['live','생성 구간 미리보기']]:[]),...items.map(item=>[item.job,item.label])]){const option=element('option',label);option.value=value;this.cameraPreviewSelect.append(option);}

        this.cameraPreviewSelect.value=chosen?.job||this.cameraPreviewId||'source';this.cameraPreviewSelect.hidden=false;

        const url=path?viewURL(path.replaceAll('\\','/').replace(/^[A-Za-z]:.*[\\/]/,''),type):'';

        const key=url||'';if(this.video.dataset.path!==key){this.video.pause();this.video.dataset.path=key;if(url){this.video.src=url;this.video.load();}else this.video.removeAttribute('src');}

        this.video.hidden=!url;this.previewEmpty.hidden=!!url;this.previewEmpty.textContent='참고 비디오를 넣고 카메라 구간을 설정해 주세요.';

        this.clipCard.hidden=false;this.fullCard.hidden=true;this.fullVideo.pause();this.previewSelect.hidden=true;

        this.clipTab.classList.remove('selected');this.fullTab.classList.remove('selected');this.cameraTab.classList.add('selected');

        this.clipLink.hidden=!url;if(url)this.clipLink.href=url;

        this.previewTitle.textContent=chosen?.label||(live?'카메라 생성 구간':'카메라 참고 비디오');

        const seconds=chosen?.finished-chosen?.created;this.processingTime.textContent=seconds>0?`카메라 처리 시간 ${Math.floor(seconds/60)}분 ${(seconds%60).toFixed(1)}초`:camera?.message||'카메라 구간 설정';

        this.previewNodes.draw(previewNodeModel(this.state.plan,this.project,this.selected),{previewText:this.previewTitle.textContent,busy:!!camera?.running});this.updateVideoMeta();

    }

    async openCameraDirecting() {

        const clip = this.state.plan.clips[this.selected];

        if (clip.mode !== 'R2V') return;

        const refs = clip.use_common_references ? referenceSource(this.state.plan, clip) : clip;

        if (!refs.videos?.length) return;

        if(!this.busyRequest&&!this.project?.active&&this.project?.batch?.state!=='running'){

            this.generationMode='camera';this.galleryPreview=null;this.previewKind='camera';this.persist();this.render();

        }

        await this.cameraController().open(refs.videos);

    }



    renderBackgroundRefresh(parent, c) {

        const record = this.project?.clips[String(this.selected + 1)];

        if (!record?.video) return; // Regeneration only; no option on an ungenerated clip.

        const panel = element('div', undefined, 'eh3-background'); parent.append(panel);

        panel.append(element('h4', '배경 참고 · 재생성'));

        const enabled = this.field(panel, '배경 참고 갱신', c, 'background_refresh');

        enabled.addEventListener('change', () => this.render());

        if (!this.config.background_refresh_supported) {

            panel.append(element('p', '현재 생성이 끝난 후 ComfyUI를 재시작하면 사용할 수 있습니다.', 'eh3-help'));

            enabled.dataset.unavailable = 'true'; return;

        }

        if (!c.background_refresh) return;

        const source = {value: c.background_source === 'clip1' ? '첫 클립 화면' : '새 배경 이미지'};

        const selector = this.field(panel, '배경 참고 출처', source, 'value', {items: ['새 배경 이미지', '첫 클립 화면']});

        selector.addEventListener('change', () => {

            c.background_source = source.value === '첫 클립 화면' ? 'clip1' : 'image'; this.changed(); this.render();

        });

        if (c.background_source === 'image') {

            this.imageField(panel, '배경 이미지', c, 'background_image');

        } else {

            this.field(panel, '첫 클립 참고 시점 · 초', c, 'background_time', {type: 'number', min: 0, max: 15, step: .1});

            const first = this.project.clips['1'];

            if (first?.video) {

                const card = element('div', undefined, 'eh3-reference-card'); panel.append(card);

                const video = element('video'); video.src = viewURL(first.video); video.controls = true;

                video.muted = true; video.preload = 'metadata'; card.append(video);

                video.addEventListener('loadedmetadata', () => {

                    if (c.background_time < video.duration) video.currentTime = c.background_time;

                }, {once: true});

                this.button('표시한 시점 사용', () => {

                    c.background_time = Math.round(video.currentTime * 1000) / 1000; this.changed(); this.render();

                }, panel);

            }

        }

        panel.append(element('p', '배경용 참고를 추가합니다. 인물이 없는 이미지나 배경이 잘 보이는 화면을 권장합니다. 인물 참고·연결은 유지하지만 배경만 분리하는 마스크는 아닙니다.', 'eh3-help'));

        if (c.mode !== 'R2V') panel.append(element('p', 'ON인 재생성은 기존 R2V 전환 LoRA와 참고 조건을 사용합니다. I2V 시작·끝 이미지와 체인 연결은 유지합니다.', 'eh3-help'));

        const row = element('div', undefined, 'eh3-row'); panel.append(row);

        this.button('이후 완료 클립에도 적용', () => {

            const count = applyBackgroundToCompleted(this.state.plan, this.project, this.selected);

            this.changed(); this.notice(`이후 완료 클립 ${count}개에 배경 참고 설정을 복사했습니다. 아직 생성하지 않았습니다.`);

        }, row);

        this.button('이 클립부터 재생성', async () => {

            if (!c.background_refresh) throw new Error('배경 참고 갱신을 먼저 켜 주세요.');

            await this.queue('restart_background');

        }, row, 'primary');

        panel.append(element('p', '선택 클립부터 마지막까지 다시 생성합니다. 이전 결과는 갤러리에 보관됩니다. 한 클립만 바꾸려면 하단 클립 생성 → Generate를 사용하세요.', 'eh3-help'));

    }



    updateReferenceSelection() {

        if (!this.referenceSelection?.isConnected) return;

        const c = this.state.plan.clips[this.selected];

        if (c.mode !== 'R2V') return;

        const numbers = commonPictureIndices(this.state.plan, c);

        const invalid = numbers.filter(i => !referenceSource(this.state.plan, c).images[i - 1]);

        this.referenceSelection.textContent = c.use_common_references

            ? invalid.length ? `이미지 등록 필요: Picture ${invalid.join(', ')}`

                : numbers.length ? `이 클립 사용: Picture ${numbers.join(', ')}` : '이 클립 이미지 참고 OFF · Picture 번호 없음'

            : '클립 전용 목록 전체 사용 · 번호는 이 목록 순서';

        this.inputPanel.querySelectorAll('.eh3-references-image .eh3-reference-card').forEach((card, i) => {

            if (card.closest('.eh3-background')) return;

            card.classList.toggle('eh3-reference-inactive', c.use_common_references && !numbers.includes(i + 1));

        });

    }



    bulkImport() {

        const dialog = element('dialog', undefined, 'eh3-dialog');

        dialog.append(element('h3', '클립별 프롬프트 일괄 입력'), element('p', '각 클립 사이를 ===CLIP=== 한 줄로 구분하세요. 현재 미생성 계획을 교체합니다.'));

        const text = element('textarea'); text.placeholder = '첫 클립 프롬프트\n===CLIP===\n두 번째 클립 프롬프트'; dialog.append(text);

        const actions = element('div', undefined, 'eh3-row'); dialog.append(actions);

        this.button('적용', () => {

            if (Object.keys(this.project?.clips || {}).length) throw new Error('이미 생성한 프로젝트에는 일괄 교체를 적용할 수 없습니다. 새 프로젝트에서 사용해 주세요.');

            const parts = text.value.split(/^\s*===CLIP===\s*$/m).map(s => s.trim()).filter(Boolean);

            if (!parts.length) throw new Error('프롬프트를 입력해 주세요.');

            const indices = sceneClipIndices(this.state.plan, this.selected);

            const base = this.state.plan.clips[indices[0]] || emptyClip();

            const added = parts.map(prompt => ({...clone(base), prompt}));

            if (this.state.plan.sequence_mode) this.state.plan.clips.splice(indices[0], indices.length, ...added);

            else this.state.plan.clips = added;

            this.selected = this.state.plan.sequence_mode ? indices[0] : 0; this.selectedClips = new Set([this.selected]); this.changed(); this.render(); dialog.close(); dialog.remove();

        }, actions, 'primary');

        this.button('취소', () => { dialog.close(); dialog.remove(); }, actions);

        dialog.addEventListener('cancel', () => dialog.remove());

        document.body.append(dialog); dialog.showModal();

    }



    render(view = this.captureScroll()) {

        this.actionPreview ||= new StudioActionPreview(this.root);

        this.actionPreview.hide();

        this.panelLayout?.dispose();

        this.previewNodes?.dispose();

        this.multiClipContainer = null;

        syncReferences(this.state.plan);

        const scrollEpoch = this.scrollRestoreEpoch = (this.scrollRestoreEpoch || 0) + 1;

        this.referenceDialog?.close();

        this.settingsDialog?.close();

        this.outputDialog?.close();

        this.newProjectDialog?.close();

        this.assetSelectors = [];

        this.root.querySelectorAll('.eh3-reference-card video, .eh3-reference-card audio').forEach(media => media.pause());

        this.video?.pause(); this.fullVideo?.pause();

        this.galleryObserver?.disconnect();

        this.root.replaceChildren();

        if (this.node.properties.endless_font_revision !== 'large20261017') {

            this.node.properties.endless_font_scale = Math.max(Number(this.node.properties.endless_font_scale) || 1.5, 1.5);

            this.node.properties.endless_font_revision = 'large20261017';

        }

        this.setUIFontScale((this.node.properties.endless_font_scale ?? 1.5) * 100, false);

        this.selected = Math.min(this.selected, this.state.plan.clips.length - 1);

        if (this.selected < 0) this.selected = 0;

        if (!this.selectedClips || !this.selectedClips.size) {

            this.selectedClips = new Set([this.selected]);

        } else {

            const maxIdx = this.state.plan.clips.length - 1;

            const valid = [...this.selectedClips].filter(i => Number.isInteger(i) && i >= 0 && i <= maxIdx);

            const visible = sceneClipIndices(this.state.plan, this.selected);

            this.selectedClips = new Set(valid.filter(i => visible.includes(i)));

            if (!this.selectedClips.size) this.selectedClips.add(this.selected);

        }

        if (!this.selectedClips.has(this.selected)) {

            this.selected = [...this.selectedClips][0];

        }

        const c = this.state.plan.clips[this.selected];

        const heading = element('div', undefined, 'eh3-heading');

        heading.append(element('strong', 'Flagship Scene UI'));

        const tools = element('div', undefined, 'eh3-header-tools'); heading.append(tools);

        const sizes = ['small', 'normal', 'large'];

        this.smallerButton = this.button('−', () => this.setUISize(sizes[Math.max(0, sizes.indexOf(this.root.dataset.uiSize) - 1)]), tools);

        this.smallerButton.setAttribute('aria-label', 'UI 작게');

        this.sizeLabel = element('span', undefined, 'eh3-size-label'); tools.append(this.sizeLabel);

        this.largerButton = this.button('+', () => this.setUISize(sizes[Math.min(2, sizes.indexOf(this.root.dataset.uiSize) + 1)]), tools);

        this.largerButton.setAttribute('aria-label', 'UI 크게');

        this.setUISize(this.node.properties.endless_ui_size || 'normal');

        for (const [label, open] of [['접기', false], ['펼치기', true]]) {

            this.button(label, () => {

                this.root.querySelectorAll('details.eh3-panel').forEach(details => { details.open = open; });

            }, tools).title = `모든 메뉴 ${open ? '펼치기' : '접기'}`;

        }

        this.vramResetButton = this.button('↻ VRAM 리셋' , () => this.resetVRAM(), tools);

        this.vramResetButton.title = '생성 대기 상태에서 모델과 메모리 캐시 해제 · 다음 생성 시 모델 재로딩';

        this.settingsButton = this.button('⚙ 공통 설정', () => {

            this.updateStatus(); this.settingsDialog.showModal();

        }, tools, 'eh3-settings-button');

        this.settingsButton.setAttribute('aria-label', '공통 설정 열기');

        this.settingsButton.setAttribute('aria-haspopup', 'dialog');

        this.root.append(heading);

        const workspace = element('div', undefined, 'eh3-workspace'); this.root.append(workspace);

        this.controls = element('div', undefined, 'eh3-controls'); workspace.append(this.controls);

        this.controls.setAttribute('role', 'region'); this.controls.setAttribute('aria-label', '생성 및 설정');

        this.results = element('aside', undefined, 'eh3-results'); workspace.append(this.results);

        this.results.setAttribute('aria-label', '미리보기와 아웃풋 갤러리');

        const commandbar = element('section', undefined, 'eh3-commandbar'); this.root.insertBefore(commandbar, workspace);

        commandbar.setAttribute('aria-label', '생성 컨트롤');

        this.inputRail = element('div', undefined, 'eh3-input-rail'); this.root.insertBefore(this.inputRail, workspace);

        this.renderInputFiles();

        const projectPanel = this.collapsible(this.controls, 'project', 'PROJECT WORKSPACE', 'eh3-project-panel');

        this.sequenceToggle = this.button(this.state.plan.sequence_mode ? '시퀀스 모드 · ON' : '일반 모드 · OFF', () => {

            if (!this.config.sequence_mode_supported) throw new Error('ComfyUI 재시작 후 시퀀스 모드를 사용할 수 있습니다.');

            this.state.plan.sequence_mode = !this.state.plan.sequence_mode;

            this.selectedClips = new Set([this.selected]); this.changed(); this.render();

        }, projectPanel, 'eh3-sequence-toggle');

        this.sequenceToggle.setAttribute('role', 'switch');

        this.sequenceToggle.setAttribute('aria-checked', String(!!this.state.plan.sequence_mode));

        this.sequenceToggle.title = 'OFF 일반 연속 클립 / ON 씬 안에 클립 · 끄더라도 씬 설정 유지';

        const projectRow = element('div', undefined, 'eh3-row eh3-project-row'); projectPanel.append(projectRow);

        this.projectSelect = element('select'); projectRow.append(this.projectSelect);

        const list = [...this.config.projects];

        if (this.project) {

            const current = {...this.project, completed: this.project.next_clip - 1};

            const index = list.findIndex(p => p.id === current.id);

            if (index >= 0) list[index] = current;

            else list.unshift(current);

        }

        const placeholder = element('option', '저장된 프로젝트 선택'); placeholder.value = ''; this.projectSelect.append(placeholder);

        for (const p of list) {

            const date = new Date((p.updated || p.created) * 1000).toLocaleString('ko-KR');

            const option = element('option', `${p.name} · ${date} · ${p.completed ?? Object.keys(p.clips || {}).length}클립`);

            option.value = p.id; this.projectSelect.append(option);

        }

        this.projectSelect.value = this.state.project_id || '';

        this.projectSelect.addEventListener('change', async () => {

            try {

                if (!this.projectSelect.value) return;

                if (this.dirty && !window.confirm('저장되지 않은 수정 내용이 있습니다. 선택한 프로젝트를 불러올까요?')) {

                    this.projectSelect.value = this.state.project_id || ''; return;

                }

                const p = await request(`project/${this.projectSelect.value}`);

                this.project = p; this.state = {project_id: p.id, name: p.name, plan: p.plan};

                this.galleryPreview = null;

                this.previewClip = null; this.previewJob = null; this.previewExport = null; this.previewKind = 'clip';

                this.selected = Math.min(p.next_clip - 1, p.plan.clips.length - 1); this.selectedClips = new Set([this.selected]); this.dirty = false; this.persist(); this.render();

            } catch (error) { this.notice(error.message); }

        });

        this.newButton = this.button('+ 새 작업', () => this.newProject(), projectRow);

        this.button('↻', async () => {

            this.config.projects = (await request('projects')).projects; await this.refresh(); this.render();

        }, projectRow).setAttribute('aria-label', '프로젝트 목록 새로고침');

        this.field(projectPanel, '프로젝트 이름', this.state, 'name', {disabled: !!this.state.project_id});

        this.modeSelect = this.field(projectPanel, '생성 방식', c, 'mode', {items: ['I2V', 'R2V', 'T2V']});

        this.modeSelect.addEventListener('change', () => this.render());

        this.modeSelect.previousElementSibling.textContent = `생성 방식 · ${clipLabel(this.state.plan, this.selected)}`;

        const actions = element('div', undefined, 'eh3-row eh3-actions'); commandbar.append(actions);

        const modes = element('div', undefined, 'eh3-generation-modes'); commandbar.prepend(modes);

        modes.setAttribute('role', 'radiogroup'); modes.setAttribute('aria-label', '생성 범위');

        this.modeInputs = [];

        for (const [value, title] of [['clip', '클립 생성'], ['all', '전체 생성'], ['all_assemble', '전체 생성+합치기'], ['camera','카메라 디렉팅']]) {

            const label = element('label', undefined, 'eh3-generation-mode'); modes.append(label);

            const input = element('input'); input.type = 'radio'; input.name = `eh3-generation-${this.node.id}`;

            input.value = value; input.checked = this.generationMode === value; label.append(input, element('span', title));

            input.addEventListener('change', () => { if (input.checked) { this.generationMode = value;if(value==='camera'){this.galleryPreview=null;this.previewKind='camera';this.cameraController();}this.persist();this.render(); } });

            this.modeInputs.push(input);

        }

        this.generateButton = this.button('', () => this.generate(), commandbar, 'eh3-generate'); commandbar.prepend(this.generateButton);

        const generateCopy = element('span', undefined, 'eh3-generate-copy');

        this.generateLabel = element('span', 'Generate', 'eh3-generate-label');

        this.generationTarget = element('span', undefined, 'eh3-generation-target');

        generateCopy.append(this.generateLabel, this.generationTarget);

        const trigger = element('span', undefined, 'eh3-generate-trigger'); trigger.setAttribute('aria-hidden', 'true');

        this.generateButton.append(generateCopy, trigger);

        this.scheduleButton = this.button('다음 예약 생성', () => this.scheduleNext(), actions);

        this.cancelButton = this.button('■ 중지', async () => {

            if(this.cameraWindow?.running||this.cameraWindow?.submitting){await this.cameraWindow.cancel();return;}

            await request('cancel', {project_id: this.state.project_id}); await this.refresh();

        }, actions);

        this.nodeViewButton = this.button('노드 보기', () => this.showNodes(), actions);

        this.nodeViewButton.title = '선택 클립의 원래 노드 연결 보기';

        this.status = element('div', undefined, 'eh3-status'); commandbar.append(this.status);

        this.renderPreview();

        const work = element('div', undefined, 'eh3-work'); this.controls.append(work);

        this.renderScenes(work);

        const sidebar = this.collapsible(work, 'clips', '클립 계획', 'eh3-sidebar');

        this.clipList = element('div', undefined, 'eh3-clip-list'); sidebar.append(this.clipList);

        this.addButton = this.button('+ 클립 추가', () => {

            const last = sceneClipIndices(this.state.plan, this.selected).at(-1);

            const base = clone(this.state.plan.clips[last] || emptyClip()); base.prompt = ''; base.last_image = '';

            base.background_refresh = false;

            base.use_common_references = true;

            base.refiner = clipRefinerConfig({});

            const newIndex = insertSceneClip(this.state.plan, this.selected, base, this.project);

            this.selected = newIndex;

            this.selectedClips = new Set([newIndex]);

            this.changed(); this.render();

        }, sidebar);

        const bulk = this.button('일괄 입력', () => this.bulkImport(), sidebar);

        bulk.disabled = !!this.project?.active || this.project?.batch?.state === 'running';

        this.saveButton = this.button('저장', async () => {

            if (!this.state.project_id) { await this.newProject(); return; }

            this.project = await request('plan', {project_id: this.state.project_id, plan: this.state.plan});

            this.dirty = false; this.persist(); this.render();

        }, sidebar);

        this.button('JSON 불러오기', () => {

            const chooser = element('input'); chooser.type = 'file'; chooser.accept = '.json,application/json';

            chooser.onchange = async () => {

                try {

                    if (Object.keys(this.project?.clips || {}).length) throw new Error('계획 전체 불러오기는 새 프로젝트에서 사용해 주세요.');

                    let plan = JSON.parse(await chooser.files[0].text());

                    if (Array.isArray(plan)) plan = {settings: this.state.plan.settings,

                        clips: plan.map(item => typeof item === 'string' ? {...emptyClip(), prompt: item} : item)};

                    if (!Array.isArray(plan.clips) && !plan.scenes?.some(scene => Array.isArray(scene.clips))) throw new Error('새 올인원의 clips 목록이 있는 계획 JSON을 선택해 주세요.');

                    if ((plan.sequence_mode || plan.scenes?.length > 1) && !this.config.sequence_mode_supported) throw new Error('ComfyUI 재시작 후 씬 계획을 불러와 주세요.');

                    plan = await request('validate_plan', plan);

                    plan.clips.forEach((clip, i) => { if (!this.project?.clips[String(i + 1)]?.video) clip.background_refresh = false; });

                    this.state.plan = plan; this.selected = 0; this.selectedClips = new Set([0]); this.changed(); this.render();

                } catch (error) { this.notice(error.message); }

            }; chooser.click();

        }, sidebar);

        this.button('JSON 내보내기', () => {

            const blob = new Blob([JSON.stringify(this.state.plan, null, 2)], {type: 'application/json'});

            const url = URL.createObjectURL(blob); const link = element('a'); link.href = url;

            link.download = `${this.state.name || 'flgaship h3'}.json`; link.click(); URL.revokeObjectURL(url);

        }, sidebar);

        this.renderClipEditor(work);

        this.renderRefiners(work);

        this.resolutionPanel = this.collapsible(work, 'resolution', '해상도', 'eh3-resolution');

        const resolutionGrid = element('div', undefined, 'eh3-grid'); this.resolutionPanel.append(resolutionGrid);

        this.renderResolution(resolutionGrid);

        this.renderLoras(work);

        this.renderOptimizers(work);

        if(this.generationMode==='camera')this.cameraController().renderMainSettings(work);

        this.renderUpscale();

        this.renderSettings();

        actions.title = '생성은 이 버튼으로 실행합니다. 중간 클립을 재생성하면 뒤 클립도 다시 생성해야 합니다.';

        this.previewArea.classList.add('eh3-preview-area');

        this.previewNodes.root.remove();

        this.panelLayout = new StudioDockLayout(this.root, workspace,

            {'1': this.controls, '2': this.results, '3': this.previewNodes.root}, this.node.properties, () => this.persist());

        if (this.cameraButton) this.panelLayout.panels.find(panel => panel.dataset.studioPanel === '1')

            .querySelector('.eh3-pane-header').append(this.cameraButton);

        this.updateStatus();

        this.restoreScroll(view);

        requestAnimationFrame(() => {

            if (!this.disposed && scrollEpoch === this.scrollRestoreEpoch) {

                this.restoreScroll(view); this.previewNodes?.revealActive();

            }

        });

    }



    renderClipEditor(parent) {

        const totalClips = this.state.plan.clips.length;

        const validSelected = [...this.selectedClips]

            .filter(i => Number.isInteger(i) && i >= 0 && i < totalClips)

            .sort((a, b) => a - b);



        if (validSelected.length === 0) {

            validSelected.push(Math.max(0, Math.min(this.selected, totalClips - 1)));

            this.selectedClips = new Set(validSelected);

            this.selected = validSelected[0];

        }



        const isMulti = validSelected.length > 1;

        const isAll = validSelected.length === totalClips && totalClips > 1;



        const title = isAll

            ? `전체 클립 설정 (${totalClips}개 클립)`

            : isMulti

                ? `선택 클립 설정 (${validSelected.length}개 선택 / 전체 ${totalClips}개)`

                : `${clipLabel(this.state.plan, validSelected[0])} 설정`;



        this.editor = this.collapsible(parent, 'editor', title, 'eh3-editor');



        if (!isMulti) {

            const i = validSelected[0];

            const c = this.state.plan.clips[i];

            const record = this.project?.clips[String(i + 1)];

            const textPanel = this.collapsible(this.editor, 'clip_text', '프롬프트 · 길이 · 시드', 'eh3-clip-text');

            this.field(textPanel, '이 클립의 프롬프트', c, 'prompt', {multiline: true});

            const row = element('div', undefined, 'eh3-row'); textPanel.append(row);

            this.field(row, '길이 · 초', c, 'seconds', {type: 'number', min: 3, max: 15, step: .1});

            const seed = this.field(row, '시드 · -1 랜덤', c, 'seed');

            seed.addEventListener('change', () => {

                const number = Number(seed.value);

                if (!Number.isSafeInteger(number)) {

                    c.seed = -1; seed.value = '-1';

                    this.notice('브라우저에서는 안전하게 저장할 수 있는 정수 시드만 입력해 주세요.');

                } else {

                    c.seed = number; this.changed();

                }

            });

            const highest = Math.max(0, ...Object.keys(this.project?.clips || {}).map(Number));

            if (!record && i + 1 > highest && totalClips > 1) {

                this.button('이 미생성 클립 삭제', () => {

                    this.state.plan.clips.splice(i, 1);

                    pruneEmptyScenes(this.state.plan);

                    this.selected = Math.max(0, i - 1);

                    this.selectedClips = new Set([this.selected]);

                    this.changed(); this.render();

                }, this.editor);

            }

        } else {

            const toolbar = element('div', undefined, 'eh3-multi-editor-toolbar');

            this.editor.append(toolbar);



            const info = element('span', `${validSelected.length}개 클립 동시 표시 · 번호 클릭으로 추가/제외`, 'eh3-help');

            toolbar.append(info);



            this.button('현재 1개만 보기', () => {

                this.selectedClips = new Set([this.selected]);

                this.persist();

                this.render();

            }, toolbar, 'eh3-clip-tool-btn');



            const container = this.multiClipContainer = element('div', undefined, 'eh3-multi-clip-container');

            this.editor.append(container);



            for (const i of validSelected) {

                const c = this.state.plan.clips[i];

                const record = this.project?.clips[String(i + 1)];

                const isDone = Boolean(record && !record.missing && !record.stale && !record.gallery_deleted);

                const isStale = Boolean(record?.stale);

                const isMissing = Boolean(record?.missing);

                const state = isMissing ? '파일 누락' : isStale ? '재생성 필요' : record?.gallery_deleted ? '완료 · 휴지통' : isDone ? '완료' : '미생성';

                const stateClass = isStale ? 'stale' : isDone ? 'done' : 'pending';



                const card = element('div', undefined, `eh3-clip-editor-card ${stateClass}`);

                container.append(card);



                const cardHeader = element('div', undefined, 'eh3-clip-editor-header');

                card.append(cardHeader);



                const titleWrap = element('div', undefined, 'eh3-clip-editor-title-wrap');

                cardHeader.append(titleWrap);



                const cardTitle = element('strong', `클립 ${i + 1}`, 'eh3-clip-card-title');

                const stateBadge = element('span', state, `eh3-clip-state-badge ${stateClass}`);

                titleWrap.append(cardTitle, stateBadge);



                const actions = element('div', undefined, 'eh3-clip-card-actions');

                cardHeader.append(actions);



                const focusBtn = this.button('이것만 보기', () => {

                    this.selected = i;

                    this.selectedClips = new Set([i]);

                    this.previewClip = i + 1;

                    this.previewJob = null;

                    this.previewKind = 'clip';

                    this.persist();

                    this.render();

                }, actions, 'eh3-clip-card-tool-btn');

                focusBtn.title = `클립 ${i + 1}만 단독 선택`;



                const highest = Math.max(0, ...Object.keys(this.project?.clips || {}).map(Number));

                if (!record && i + 1 > highest && totalClips > 1) {

                    const delBtn = this.button('삭제', () => {

                        this.state.plan.clips.splice(i, 1);

                    pruneEmptyScenes(this.state.plan);

                        this.selectedClips.delete(i);

                        const updated = new Set();

                        for (const s of this.selectedClips) {

                            if (s > i) updated.add(s - 1);

                            else updated.add(s);

                        }

                        this.selectedClips = updated;

                        if (this.selectedClips.size === 0) {

                            this.selected = Math.max(0, i - 1);

                            this.selectedClips.add(this.selected);

                        } else {

                            this.selected = [...this.selectedClips][0];

                        }

                        this.changed(); this.render();

                    }, actions, 'eh3-clip-card-del-btn');

                    delBtn.title = `클립 ${i + 1} 계획 삭제`;

                }



                this.field(card, `클립 ${i + 1} 프롬프트`, c, 'prompt', {multiline: true});



                const row = element('div', undefined, 'eh3-row');

                card.append(row);

                this.field(row, '길이 · 초', c, 'seconds', {type: 'number', min: 3, max: 15, step: .1});

                const seed = this.field(row, '시드 · -1 랜덤', c, 'seed');

                seed.addEventListener('change', () => {

                    const number = Number(seed.value);

                    if (!Number.isSafeInteger(number)) {

                        c.seed = -1; seed.value = '-1';

                        this.notice('브라우저에서는 안전하게 저장할 수 있는 정수 시드만 입력해 주세요.');

                    } else {

                        c.seed = number; this.changed();

                    }

                });

            }

        }

    }



    renderRefiners(parent) {

        const panel = this.refinerPanel = this.collapsible(parent, 'clip_refiner', '클립 리파이너', 'eh3-refiner');

        const s = this.state.plan.settings;

        const supported = !!this.config.clip_refiner_per_clip_only;

        if (!supported) panel.append(element('p', '백엔드 업데이트 적용 전입니다. 현재 작업이 끝난 뒤 ComfyUI를 재시작하고 새로고침해 주세요.', 'eh3-help'));

        panel.append(element('p', '각 클립에서 켠 경우에만 적용됩니다. 새 클립·설정 누락·기존 공통 따름은 OFF입니다. 얼굴 복원 기능은 아닙니다.', 'eh3-help'));

        for (const i of [...this.selectedClips].sort((a, b) => a - b)) {

            const c = this.state.plan.clips[i];

            if (!c) continue;

            c.refiner = clipRefinerConfig(c);

            const r = c.refiner;

            const card = element('div', undefined, 'eh3-refiner-card'); panel.append(card);

            card.append(element('strong', `클립 ${i + 1}`));

            const grid = element('div', undefined, 'eh3-grid'); card.append(grid);

            const choice = {enabled: r.mode === 'on'};

            const mode = this.field(grid, '리파이너 ON / OFF', choice, 'enabled', {disabled: !supported});

            mode.addEventListener('change', () => {

                r.mode = mode.checked ? 'on' : 'off';

                // Re-enable a measured clip only with a valid earlier reference.

                if (r.mode === 'on' && r.reference_clip >= i + 1) r.reference_clip = 1;

                this.changed(); this.render();

            });

            const strength = this.field(grid, '클립 강도', r, 'strength', {type: 'number', step: .05, min: 0, max: 3, disabled: !supported || r.mode !== 'on'});

            strength.dataset.refinerLocked = String(r.mode !== 'on');

            const reference = this.field(grid, '기준 클립 번호', r, 'reference_clip', {type: 'number', step: 1, min: 1, max: Math.max(1, i), disabled: !supported || r.mode !== 'on' || i === 0});

            reference.dataset.refinerLocked = String(r.mode !== 'on' || i === 0);

            strength.addEventListener('change', () => this.render());

            reference.addEventListener('change', () => this.render());

            const effective = clipRefinerEffective(s, c);

            const text = !effective.enabled || effective.strength === 0 ? '적용: OFF · 원본 latent 통과' : i === 0

                ? '적용: 첫 클립 측정만 · 보정 없음'

                : `적용: ON · 강도 ${effective.strength} · 기준 클립 ${effective.reference_clip}`;

            card.append(element('p', text, 'eh3-help'));

            if (r.reason) card.append(element('p', `작성기 판단 메모: ${r.reason}`, 'eh3-help'));

        }

        panel.append(element('p', '같은 장면의 앞 클립을 기준으로 선택하세요. 약한 0.1~0.2는 비교용 시작값이며 품질 보장이 아닙니다. 설정 변경은 다음 생성·재생성부터 적용됩니다.', 'eh3-help'));

    }



    renderResolution(parent) {

        const s = this.state.plan.settings;

        const locked = !!this.project?.geometry || !!this.project?.active || this.busyRequest || this.project?.batch?.state === 'running';

        const previousWidth = s.width, previousHeight = s.height;

        this.state.resolution = migrateResolutionPreset(s, this.state.resolution, locked);

        if (s.width !== previousWidth || s.height !== previousHeight) this.changed();

        let selection = this.state.resolution;

        if (!selection || selection.width !== s.width || selection.height !== s.height) {

            const divisor = gcd(s.width, s.height);

            const preset = aspectPresets.flatMap(aspect => megapixelPresets.map(megapixels =>

                ({aspect, megapixels, ...resolutionFor(aspect, megapixels)})))

                .find(value => value.width === s.width && value.height === s.height);

            selection = preset || {aspect: `${s.width / divisor}:${s.height / divisor}`, megapixels: s.width * s.height / 1e6,

                                   width: s.width, height: s.height};

            this.state.resolution = selection;

        }

        const aspectOptions = [...aspectPresets];

        if (!aspectOptions.includes(selection.aspect)) aspectOptions.unshift(selection.aspect);

        const mpOptions = [...megapixelPresets];

        if (!mpOptions.includes(selection.megapixels)) mpOptions.unshift(selection.megapixels);

        const choices = {aspect: selection.aspect, megapixels: `${Number(selection.megapixels.toFixed(6))} MP`};

        for (const [key, label, values] of [

            ['aspect', '종횡비 · 프로젝트 시작 후 고정', aspectOptions],

            ['megapixels', '메가픽셀 · 프로젝트 시작 후 고정', mpOptions.map(value => `${Number(value.toFixed(6))} MP`)],

        ]) {

            const input = this.field(parent, label, choices, key, {items: values, searchable: true, disabled: locked});

            input.addEventListener('input', () => {

                if (this.project?.geometry || this.project?.active || this.busyRequest || this.project?.batch?.state === 'running') return;

                selection[key] = key === 'megapixels' ? parseFloat(input.value) : input.value;

                Object.assign(s, resolutionFor(selection.aspect, selection.megapixels));

                selection.width = s.width; selection.height = s.height;

                this.changed(); updateSummary();

            });

        }

        const summary = element('p', undefined, 'eh3-help'); summary.style.gridColumn = '1 / -1'; parent.append(summary);

        const updateSummary = () => {

            summary.textContent = `실제 해상도 ${s.width} × ${s.height} · ${(s.width * s.height / 1e6).toFixed(3)} MP · 32픽셀 단위로 맞춤${locked ? ' · 해상도를 바꾸려면 새 프로젝트를 만드세요.' : ''}`;

        };

        updateSummary();

    }



    renderUpscale() {

        const s = this.state.plan.settings;

        s.color_treatment ??= 'Auto Natural';

        s.output_quality ??= 95;

        const panel = this.upscalePanel = this.collapsible(this.controls, 'upscale', '업스케일', 'eh3-upscale', s.upscale);

        const grid = element('div', undefined, 'eh3-grid'); panel.append(grid);

        const choices = (label, key, values) => {

            const group = element('div', undefined, 'eh3-choice');

            group.setAttribute('role', 'group'); group.setAttribute('aria-label', label);

            group.append(element('div', label, 'eh3-choice-label'));

            const row = element('div', undefined, 'eh3-choice-buttons'); group.append(row);

            grid.append(group);

            const buttons = values.map(([value, title]) => {

                const button = this.button(title, () => {

                    if (this.busyRequest || this.project?.active || this.project?.batch?.state === 'running') return;

                    s[key] = value; this.changed(); markSelection(); this.updateStatus();

                }, row);

                return {value, button};

            });

            const markSelection = () => buttons.forEach(({value, button}) => {

                const selected = s[key] === value;

                button.classList.toggle('selected', selected);

                button.setAttribute('aria-pressed', String(selected));

            });

            markSelection();

        };

        choices('업스케일', 'upscale', [[false, 'OFF'], [true, 'ON']]);

        const scales = Array.from({length: 13}, (_, i) => 1 + i * .25);

        if (!scales.includes(s.scale)) scales.push(s.scale);

        choices('배율', 'scale', scales.sort((a, b) => a - b).map(value => [value, `${value}×`]));

        choices('VRAM', 'memory_profile', [

            ['Auto', 'Auto'], ['Quality', 'Quality'], ['Low VRAM', 'Low VRAM'],

        ]);

        choices('Auto Color', 'color_treatment', [

            ['Off', 'OFF'], ['Auto Natural', '자연스럽게'], ['Auto Bright', '밝게'],

        ]);

        choices('Output Quality', 'output_quality', Array.from({length: 20}, (_, i) => [80 + i, String(80 + i)]));

        panel.title = '전체 합본에 적용. 출력 품질은 저장 압축 품질이며 생성 디테일을 늘리는 설정은 아닙니다.';

        choices('모션 리페어', 'motion_repair', [

            ['Auto', 'Auto'], ['Action Strong', '액션'],

            ['NVIDIA 가변 프레임 보간', 'NVIDIA 가변 보간'], ['Off', 'OFF'],

        ]);

        choices('강도', 'motion_repair_strength',

                Array.from({length: 9}, (_, i) => [10 + i * 5, `${10 + i * 5}%`]));

    }



    renderLoras(parent) {

        const s = this.state.plan.settings;

        const panel = this.lorasPanel = this.collapsible(parent, 'loras', '추가 LoRA', 'eh3-loras-panel', s.loras.length > 0);

        panel.setAttribute('aria-label', '추가 LoRA · 모든 클립');

        panel.title = '선택한 LoRA와 강도는 모든 클립에 공통 적용됩니다.';

        const refresh = this.button('↻ LoRA 새로고침', () => this.refreshAssets('loras'), panel, 'eh3-asset-refresh');

        refresh.disabled = !this.config.asset_refresh_supported;

        const loras = element('div', undefined, 'eh3-loras'); panel.append(loras);

        for (const [i, lora] of s.loras.entries()) {

            const row = element('div', undefined, 'eh3-row'); loras.append(row);

            this.field(row, `추가 LoRA ${i + 1}`, lora, 'name', {asset: 'loras', items: this.config.models.loras, emptyLabel: '선택 안 함'});

            this.field(row, '강도', lora, 'strength', {type: 'number', step: .05});

            this.button('제거', () => { s.loras.splice(i, 1); this.changed(); this.render(); }, row);

        }

        this.button('+ 추가 LoRA', () => { s.loras.push({name: '', strength: 1}); this.changed(); this.render(); }, loras);

    }



    renderOptimizers(parent) {

        const s = this.state.plan.settings;

        s.attention_mode ??= s.sage ? 'h3_sage' : 'off';

        s.cache_mode ??= 'off';

        s.fp16_accumulation ??= false;

        s.easycache_threshold ??= .12;

        s.spectrum_blend ??= .5;

        const panel = this.optimizerPanel = this.collapsible(parent, 'optimizers', '옵티마이저', 'eh3-optimizers', false);

        panel.setAttribute('aria-label', '옵티마이저 · 모든 클립');

        const grid = element('div', undefined, 'eh3-grid'); panel.append(grid);

        const choices = (label, key, values) => {

            const group = element('div', undefined, 'eh3-choice'); grid.append(group);

            group.setAttribute('role', 'group'); group.setAttribute('aria-label', label);

            group.append(element('div', label, 'eh3-choice-label'));

            const row = element('div', undefined, 'eh3-choice-buttons'); group.append(row);

            const buttons = values.map(([value, title, node]) => {

                const button = this.button(title, () => {

                    if (this.busyRequest || this.project?.active || this.project?.batch?.state === 'running') return;

                    s[key] = value;

                    if (key === 'attention_mode') s.sage = value === 'h3_sage';

                    this.changed(); markSelection(); this.updateStatus();

                }, row);

                if (node && this.config.dependencies?.[node] === false) {

                    button.dataset.unavailable = 'true'; button.disabled = true;

                    button.title = `${node} 노드가 설치되어 있지 않습니다.`;

                }

                return {value, button};

            });

            const markSelection = () => buttons.forEach(({value, button}) => {

                const selected = s[key] === value;

                button.classList.toggle('selected', selected);

                button.setAttribute('aria-pressed', String(selected));

            });

            markSelection();

        };

        choices('Attention', 'attention_mode', [

            ['off', '기본'], ['h3_sage', 'H3 Sage', 'MiniMaxH3MemoryEfficientSageAttentionPatch'],

            ['kj_sage', 'KJ Sage', 'PathchSageAttentionKJ'],

            ['pytorch', 'PyTorch', 'ModelAttentionBackend'],

            ['kitchen', 'Kitchen', 'ModelAttentionBackend'],

        ]);

        const chunks = [...new Set([1, 2, 4, 8, 16, s.chunks])].sort((a, b) => a - b);

        choices('메모리 분할', 'chunks', chunks.map(value =>

            [value, value === 1 ? 'OFF' : `${value}분할`, value > 1 ? 'MiniMaxChunkFeedForward' : null]));

        choices('FP16 누산', 'fp16_accumulation', [

            [false, 'OFF'], [true, 'ON', 'ModelPatchTorchSettings'],

        ]);

        choices('캐시', 'cache_mode', [

            ['off', 'OFF'], ['easycache', 'EasyCache', 'EasyCache'],

            ['spectrum', 'Spectrum', 'SpectrumApplyMiniMaxH3'],

        ]);

        this.field(grid, 'EasyCache 임계값', s, 'easycache_threshold', {type: 'number', min: 0, max: 3, step: .01});

        this.field(grid, 'Spectrum 영상 강도', s, 'spectrum_blend', {type: 'number', min: 0, max: 1, step: .01});

        panel.title = '모든 클립에 적용. 캐시와 FP16 누산은 결과에 영향을 줄 수 있습니다. Spectrum 기록은 시스템 RAM에 저장합니다.';

    }



    renderLipSync(parent) {

        const s = this.state.plan.settings;

        const locked = !!this.project?.geometry;

        const panel = this.audioPanel = this.collapsible(parent, 'audio', '립싱크 오디오 · 프로젝트 공통', 'eh3-lipsync', !!s.audio_file);

        panel.setAttribute('aria-label', '립싱크 오디오 · 프로젝트 공통');

        this.field(panel, '오디오 · 비우면 H3 음성 생성', s, 'audio_file', {

            items: this.config.audio_files || [], emptyLabel: 'H3에서 음성 생성', disabled: locked,

        });

        const row = element('div', undefined, 'eh3-row'); panel.append(row);

        const upload = this.button('오디오 업로드', () => {

            if (this.busyRequest || this.project?.geometry || this.project?.active || this.project?.batch?.state === 'running') return;

            const chooser = element('input'); chooser.type = 'file'; chooser.accept = 'audio/*';

            chooser.onchange = async () => {

                if (!chooser.files?.length) return;

                try {

                    const form = new FormData(); form.append('image', chooser.files[0]); form.append('type', 'input');

                    const response = await api.fetchApi('/upload/image', {method: 'POST', body: form});

                    const data = await response.json(); if (!response.ok) throw new Error(data.error || '업로드 실패');

                    if (this.disposed || this.project?.geometry || this.project?.active || this.project?.batch?.state === 'running') return;

                    s.audio_file = data.subfolder ? `${data.subfolder}/${data.name}` : data.name;

                    this.config.audio_files ||= []; this.config.audio_files.push(s.audio_file); this.changed(); this.render();

                } catch (error) { this.notice(error.message); }

            }; chooser.click();

        }, row);

        upload.disabled = locked;

        panel.append(element('p', locked

            ? '시작 후 고정 · 변경하려면 새 작업'

            : '모든 클립 공통 · 시작 후 고정', 'eh3-help'));

    }



    renderSettings() {

        const s = this.state.plan.settings;

        const dialog = this.settingsDialog = element('dialog', undefined, 'eh3-dialog eh3-settings-dialog');

        dialog.setAttribute('aria-label', '공통 설정'); this.root.append(dialog);

        const header = element('div', undefined, 'eh3-settings-header'); dialog.append(header);

        header.append(element('h3', '⚙ 공통 설정'));

        const refresh = this.button('↻ 모델 새로고침', () => this.refreshAssets('models'), header, 'eh3-asset-refresh');

        refresh.disabled = !this.config.asset_refresh_supported;

        this.button('닫기', () => dialog.close(), header);

        const appearance = element('div', undefined, 'eh3-font-settings'); dialog.append(appearance);

        appearance.append(element('h4', '화면 글꼴 · Noto Sans KR'));

        const row = element('div', undefined, 'eh3-font-scale-row'); appearance.append(row);

        const label = element('label', 'UI 폰트 배율', 'eh3-field'); row.append(label);

        const range = this.fontScaleRange = element('input'); range.type = 'range'; range.min = '50'; range.max = '200'; range.step = '1';

        range.setAttribute('aria-label', 'UI 폰트 배율 슬라이더'); label.append(range);

        const numberLabel = element('label', '배율 · %', 'eh3-field'); row.append(numberLabel);

        const number = this.fontScaleNumber = element('input'); number.type = 'number'; number.min = '50'; number.max = '200'; number.step = '1';

        number.setAttribute('aria-label', 'UI 폰트 배율 퍼센트'); numberLabel.append(number);

        range.value = number.value = String(Math.round((this.node.properties.endless_font_scale ?? 1.5) * 100));

        range.addEventListener('input', () => this.setUIFontScale(range.value));

        number.addEventListener('input', () => {

            if (number.value !== '' && Number(number.value) >= 50 && Number(number.value) <= 200) this.setUIFontScale(number.value);

        });

        number.addEventListener('change', () => this.setUIFontScale(number.value === '' ? (this.node.properties.endless_font_scale ?? 1.5) * 100 : number.value));

        this.button('기본 150%', () => this.setUIFontScale(150), row);

        appearance.append(element('p', '50~200% · 즉시 적용 · 워크플로우에 저장', 'eh3-help'));

        const panel = this.settingsPanel = element('div', undefined, 'eh3-settings'); dialog.append(panel);

        this.field(panel, '공통 프롬프트 · 모든 클립에 포함', s, 'shared_prompt', {multiline: true});

        const grid = element('div', undefined, 'eh3-grid'); panel.append(grid);

        const models = this.config.models;

        this.field(grid, 'H3 모델', s, 'model', {asset: 'model', filter: k => /h3/i.test(k), items: models.model.filter(k => /h3/i.test(k))});

        this.field(grid, '텍스트 인코더', s, 'clip', {asset: 'clip', filter: k => /minimax/i.test(k), items: models.clip.filter(k => /minimax/i.test(k))});

        this.field(grid, '비디오 VAE', s, 'video_vae', {asset: 'vae', filter: k => /h3.*video/i.test(k), items: models.vae.filter(k => /h3.*video/i.test(k))});

        this.field(grid, '오디오 VAE', s, 'audio_vae', {asset: 'vae', filter: k => /h3.*audio/i.test(k), items: models.vae.filter(k => /h3.*audio/i.test(k))});

        this.field(grid, '터보 LoRA', s, 'turbo_lora', {asset: 'loras', filter: k => /h3/i.test(k), items: models.loras.filter(k => /h3/i.test(k)), emptyLabel: '사용 안 함'});

        this.field(grid, '터보 강도', s, 'turbo_strength', {type: 'number', step: .05});

        this.field(grid, 'R2V 전환 LoRA · FL2VA용', s, 'reference_lora', {asset: 'loras', filter: k => /h3/i.test(k), items: models.loras.filter(k => /h3/i.test(k)), emptyLabel: '사용 안 함'});

        this.field(grid, 'R2V 전환 강도', s, 'reference_strength', {type: 'number', step: .05});

        this.field(grid, '스텝', s, 'steps', {type: 'number', min: 1, max: 200, step: 1});

        this.field(grid, '샘플러', s, 'sampler', {items: this.config.samplers});

        this.field(grid, '스케줄러', s, 'scheduler', {items: this.config.schedulers});

        this.field(grid, '연결 길이 · 프로젝트 시작 후 고정', s, 'context_length', {items: ['22', '5', '39', '56']});

        this.field(grid, '시그마 · 영상', s, 'shift_video', {type: 'number', step: .1});

        this.field(grid, '시그마 · 음성', s, 'shift_audio', {type: 'number', step: .1});

        this.field(grid, 'R2V 참고 크기', s, 'ref_image_size', {items: ['max', 'match']});

        panel.append(element('p', '옵티마이저는 추가 LoRA 아래, 질감 보정은 클립 설정 아래의 클립 리파이너 메뉴에서 선택합니다.', 'eh3-help'));

        if (this.project?.geometry) {

            for (const label of grid.querySelectorAll('label')) {

                if (label.firstChild.textContent.includes('프로젝트 시작 후 고정')) label.querySelector('input,select').disabled = true;

            }

        }

        if (this.project?.active) panel.querySelectorAll('input,textarea,select,button').forEach(el => { el.disabled = true; });

    }



    dispose() {

        this.actionPreview?.dispose();

        this.cameraWindow?.dispose();

        this.livePreview?.dispose();

        this.panelLayout?.dispose();

        this.previewNodes?.dispose();

        this.newProjectDialog?.close();

        this.outputDialog?.close();

        this.settingsDialog?.close();

        this.referenceDialog?.close();

        this.root.querySelectorAll('.eh3-reference-card video, .eh3-reference-card audio').forEach(media => media.pause());

        this.disposed = true; clearInterval(this.timer); api.removeEventListener('endless_h3_aio_completed', this.finished);

        this.video?.pause(); this.root.remove();

        this.fullVideo?.pause();

        this.galleryObserver?.disconnect();

    }

}



const style = document.createElement('link');

style.rel = 'stylesheet'; style.href = new URL('./studio.css?v=desk_20261017', import.meta.url).href; document.head.append(style);

app.registerExtension({

    name: 'EndlessH3.AllInOneStudio',

    afterConfigureGraph() { showGraphViewBar(); },

    async beforeRegisterNodeDef(nodeType, nodeData) {

        if (nodeData.name !== 'EndlessH3AllInOne') return;

        const created = nodeType.prototype.onNodeCreated;

        nodeType.prototype.onNodeCreated = function () {

            created?.apply(this, arguments);

            const config = this.widgets.find(w => w.name === 'project_config');

            if (!config) return;

            config.type = 'converted-widget'; config.computeSize = () => [0, -4];

            if (config.inputEl) config.inputEl.style.display = 'none';

            this.title = 'Flagship Scene UI';

            const studio = new EndlessStudio(this, config);

            this.endlessStudio = studio;

            this.addDOMWidget('endless_studio', 'div', studio.root, {

                serialize: false, hideOnZoom: false, canvasOnly: true, hideInPanel: true, getValue: () => null, setValue: () => {},

                computeSize: () => [720, 620],

            });

            this.setSize([1280, 1140]);

            const removed = this.onRemoved;

            this.onRemoved = function () { studio.dispose(); removed?.apply(this, arguments); };

        };

        const configure = nodeType.prototype.onConfigure;

        nodeType.prototype.onConfigure = function () {

            configure?.apply(this, arguments);

            this.title = 'Flagship Scene UI';

            // Configure sets restored widget values after onNodeCreated.

            if (this.endlessStudio) this.endlessStudio.restore();

        };

    },

});

