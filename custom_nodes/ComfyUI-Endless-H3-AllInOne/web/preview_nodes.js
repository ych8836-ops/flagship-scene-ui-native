import { sceneForClip, sceneClipIndices, continuesAt } from './sequence.js';

export function nodeLocation(plan, index) {
    const clip = plan?.clips?.[index - 1];
    if (!clip) return '';
    const scene = sceneForClip(plan, clip);
    return scene ? `씬 ${plan.scenes.indexOf(scene) + 1} · 클립 ${sceneClipIndices(plan, index - 1).indexOf(index - 1) + 1}` : `클립 ${index}`;
}

const workingState = job => ({preparing: '준비 중', queued: '대기 중', running: '생성 중', failed: '실패', cancelled: '취소됨'}[job.state] || job.state);

export function previewNodeModel(plan, project, selected) {
    const active = project?.jobs?.[project.active];
    const clipJob = active && !['assemble', 'upscale'].includes(active.action) ? active : null;
    const groups = plan.sequence_mode ? plan.scenes.map((scene, i) =>
        ({id: scene.id, title: `씬 ${i + 1}`, name: scene.name === `씬 ${i + 1}` ? '' : scene.name, rows: []})) :
        [{id: 'normal', title: '일반 모드', name: '', rows: []}];
    for (const [i, clip] of plan.clips.entries()) {
        const index = i + 1;
        const saved = project?.clips?.[String(index)];
        const results = saved ? [...(saved.history || []), saved] : [];
        const versions = results.map((result, n) => ({
            key: result.job, job: result.job, version: n,
            title: n ? `재생성 ${n}` : '원본',
            state: result.missing ? '파일 누락' : result.gallery_deleted ? '휴지통' :
                result === saved ? (result.stale ? '재생성 필요' : '최신 결과') : '이전 결과',
            tone: result.missing ? 'failed' : result.gallery_deleted ? 'pending' : result.stale && result === saved ? 'stale' : 'done',
            available: !!result.video && !result.missing && !result.gallery_deleted,
            video: result.video,
        }));
        const running = clipJob?.index === index ? clipJob : null;
        const lastAttempt = running || Object.values(project?.jobs || {}).filter(job =>
            job.index === index && !['assemble', 'upscale'].includes(job.action) &&
            ['failed', 'cancelled'].includes(job.state) && job.created > (saved?.created || 0))
            .sort((a, b) => b.created - a.created)[0];
        if (lastAttempt) versions.push({key: lastAttempt.id, version: results.length,
            title: saved ? `재생성 ${results.length}` : '원본',
            state: `${saved ? '재생성 · ' : ''}${workingState(lastAttempt)}`,
            tone: lastAttempt.state === 'failed' ? 'failed' : lastAttempt.state === 'cancelled' ? 'pending' : 'active',
            active: !!running, available: false});
        if (!versions.length) versions.push({key: `planned_${index}`, version: 0, title: '원본', state: '미생성', tone: 'pending', available: false});
        const group = groups.find(item => item.id === (plan.sequence_mode ? clip.scene_id : 'normal'));
        const contextPlan = running?.plan || project?.jobs?.[saved?.job]?.plan || plan;
        const connected = index > 1 && continuesAt(contextPlan, index - 1);
        if (group) group.rows.push({index, number: group.rows.length + 1, selected: i === selected,
            active: !!running, label: nodeLocation(plan, index), versions,
            link: index === 1 ? 'start' : !connected || saved?.stale ? 'broken' : 'connected',
            linkLabel: index === 1 ? '첫 클립' : !connected ? '앞 클립 연결 끊음 · 독립 생성' :
                saved?.stale ? '앞 클립 변경 · 재생성 필요' : saved || running ? '앞 클립 컨텍스트 연결' : '앞 클립 연결 예정'});
    }
    let activity = '생성 대기';
    if (active) {
        const prefix = active.action === 'assemble' ? '전체 합치기' : active.action === 'upscale' ? '영상 업스케일' :
            `${nodeLocation(active.plan || plan, active.index)}${project.clips?.[String(active.index)] ? ' · 재생성' : ''}`;
        activity = `${prefix} · ${workingState(active)}`;
    } else if (project?.batch?.state === 'running') {
        activity = `${nodeLocation(plan, project.batch.target_clip || project.next_clip)} · 생성 준비`;
    }
    return {groups: groups.filter(group => group.rows.length), activity,
        activeKey: active?.id || null, total: plan.clips.length,
        scenes: plan.sequence_mode ? groups.filter(group => group.rows.length).length : 0};
}

function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
}

export class PreviewNodes {
    constructor(parent, select, activeKey = null, mediaURL = null) {
        this.root = el('section', undefined, 'eh3-preview-nodes');
        this.root.setAttribute('aria-label', '씬과 클립 생성 이력 그래픽');
        const header = el('div', undefined, 'eh3-node-map-header');
        header.append(el('strong', '씬 · 클립'), this.count = el('span'));
        this.activity = el('div', undefined, 'eh3-node-map-activity');
        this.activity.setAttribute('role', 'status');
        this.preview = el('div', undefined, 'eh3-node-map-preview');
        const legend = el('div', undefined, 'eh3-node-map-legend');
        legend.append(el('span', '● 연결', 'connected'), el('span', '● 끊김·재생성 필요', 'broken'));
        this.list = el('div', undefined, 'eh3-node-map-list');
        this.list.tabIndex = 0;
        this.list.setAttribute('aria-label', '클립 노드와 재생성 버전 목록');
        this.root.append(header, this.activity, this.preview, legend, this.list);
        this.mediaURL = mediaURL;
        this.liveSlots = new Map();
        this.hover = el('div', undefined, 'eh3-node-hover'); this.hover.hidden = true;
        this.hoverVideo = el('video'); this.hoverVideo.muted = true; this.hoverVideo.playsInline = true;
        this.hoverVideo.preload = 'metadata'; this.hoverVideo.loop = true;
        this.hoverLabel = el('span'); this.hover.append(this.hoverVideo, this.hoverLabel); this.root.append(this.hover);
        parent.append(this.root);
        this.select = select;
        this.signature = '';
        this.activeKey = activeKey;
    }

    scrollState() {
        return {top: this.list.scrollTop, left: this.list.scrollLeft};
    }

    restoreScroll(view) {
        if (view) { this.list.scrollTop = view.top; this.list.scrollLeft = view.left; }
    }

    draw(model, {previewJob, previewText, busy, live = null}) {
        this.count.textContent = `${model.scenes ? `씬 ${model.scenes} · ` : ''}클립 ${model.total}`;
        this.activity.textContent = model.activity;
        this.activity.classList.toggle('working', !!model.activeKey);
        this.preview.textContent = previewText;
        const signature = JSON.stringify([model, previewJob, busy]);
        if (signature === this.signature) { this.setLivePreview(live); return; }
        this.signature = signature;
        this.hideHover(); this.liveSlots.clear();
        const view = this.scrollState();
        const focused = this.list.contains(document.activeElement) ? document.activeElement.dataset.nodeKey : null;
        this.list.replaceChildren();
        let current;
        let focus;
        for (const group of model.groups) {
            const scene = el('section', undefined, `eh3-node-scene ${group.rows[0].link}`);
            const heading = el('div', undefined, 'eh3-node-scene-heading');
            heading.append(el('strong', group.title), el('span', `${group.rows.length}클립`));
            if (group.name) heading.append(el('small', group.name));
            scene.append(heading);
            for (const row of group.rows) {
                const line = el('div', undefined, `eh3-node-clip-line ${row.link}`);
                line.setAttribute('role', 'group'); line.setAttribute('aria-label', row.label);
                line.title = row.linkLabel;
                row.versions.forEach((version, n) => {
                    const button = el('button', undefined, `eh3-clip-node ${version.tone}${row.selected ? ' chosen' : ''}`);
                    button.type = 'button'; button.dataset.nodeKey = version.key;
                    button.dataset.link = ['stale', 'failed'].includes(version.tone) ? 'broken' : 'connected';
                    button.dataset.clip = String(row.index);
                    button.setAttribute('aria-label', `${row.label} · ${version.title} · ${version.state}`);
                    button.title = `${row.label} · 전체 클립 ${row.index}\n${version.title} · ${version.state}\n${version.available ? '클릭하여 이 결과 미리보기' : '클릭하여 클립 선택'}`;
                    button.disabled = busy;
                    button.append(el('strong', n ? version.title : `클립 ${row.number}`),
                        el('span', n ? `클립 ${row.number} · 전체 ${row.index}` : `원본 · 전체 ${row.index}`),
                        el('small', version.state));
                    if (version.job && version.job === previewJob) {
                        button.classList.add('viewing'); button.setAttribute('aria-current', 'true');
                    }
                    if (version.active) { button.classList.add('working'); current = button; }
                    if (version.active && version.tone === 'active') {
                        const slot = el('span', undefined, 'eh3-node-live');
                        const image = el('img'); image.alt = `${row.label} 생성 중 미리보기`; image.hidden = true;
                        const label = el('small', '샘플링 미리보기 대기'); slot.append(image, label); button.append(slot);
                        this.liveSlots.set(version.key, {image, label});
                    } else if (version.available && version.tone !== 'failed' && this.mediaURL) {
                        const show = () => this.showHover(this.mediaURL(version.video), `${row.label} · ${version.title}`);
                        button.addEventListener('pointerenter', show); button.addEventListener('focus', show);
                        button.addEventListener('pointerleave', () => this.hideHover());
                        button.addEventListener('blur', () => this.hideHover());
                    }
                    if (version.key === focused) focus = button;
                    button.addEventListener('click', () => this.select(row.index - 1, version.available ? version.job : null));
                    line.append(button);
                });
                scene.append(line);
            }
            this.list.append(scene);
        }
        this.restoreScroll(view);
        focus?.focus({preventScroll: true});
        if (model.activeKey && model.activeKey !== this.activeKey && current) this.pendingReveal = current;
        this.activeKey = model.activeKey;
        this.setLivePreview(live);
    }

    setLivePreview(frame) {
        for (const [key, {image, label}] of this.liveSlots) {
            const visible = frame?.job === key;
            image.hidden = !visible; label.hidden = visible;
            if (visible) image.src = frame.url;
            else image.removeAttribute('src');
        }
    }

    showHover(url, label) {
        if (!url) return;
        this.hoverVideo.src = url; this.hoverLabel.textContent = label; this.hover.hidden = false;
        this.hoverVideo.play()?.catch(() => {});
    }

    hideHover() {
        this.hover.hidden = true; this.hoverVideo.pause(); this.hoverVideo.removeAttribute('src'); this.hoverVideo.load();
    }

    dispose() { this.hideHover(); this.setLivePreview(null); this.liveSlots.clear(); }

    revealActive() {
        if (!this.pendingReveal) return;
        const bounds = this.list.getBoundingClientRect();
        const rect = this.pendingReveal.getBoundingClientRect();
        if (rect.top < bounds.top) this.list.scrollTop += rect.top - bounds.top - 8;
        else if (rect.bottom > bounds.bottom) this.list.scrollTop += rect.bottom - bounds.bottom + 8;
        if (rect.right > bounds.right) this.list.scrollLeft += rect.right - bounds.right + 8;
        else if (rect.left < bounds.left) this.list.scrollLeft += rect.left - bounds.left - 8;
        this.pendingReveal = null;
    }
}
