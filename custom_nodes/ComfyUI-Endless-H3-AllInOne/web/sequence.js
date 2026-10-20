const clone = value => JSON.parse(JSON.stringify(value));
const keys = ['images', 'videos', 'audios'];
export function ensureSequencePlan(plan) {
    plan.sequence_mode ??= false;
    plan.scenes ||= [{id: 'scene_1', name: '씬 1', prompt: '', continue_previous: false}];
    for (const [i, scene] of plan.scenes.entries()) {
        scene.id ||= `scene_${i + 1}`;
        scene.name ??= `씬 ${i + 1}`;
        scene.prompt ??= '';
        scene.continue_previous ??= false;
        scene.references ||= clone(plan.references || {images: [], videos: [], audios: []});
        for (const key of keys) scene.references[key] ||= [];
    }
    for (const clip of plan.clips) clip.scene_id ||= plan.scenes[0].id;
}
export function sceneForClip(plan, clip) {
    return plan.sequence_mode ? plan.scenes?.find(scene => scene.id === clip.scene_id) : null;
}
export function referenceSource(plan, clip) {
    return sceneForClip(plan, clip)?.references || plan.references;
}
export function continuesAt(plan, index) {
    if (index <= 0) return false;
    if (!plan.sequence_mode) return true;
    const clip = plan.clips[index];
    return clip.scene_id === plan.clips[index - 1].scene_id || !!sceneForClip(plan, clip)?.continue_previous;
}
export function sceneClipIndices(plan, index) {
    if (!plan.sequence_mode) return plan.clips.map((_, i) => i);
    const id = plan.clips[index]?.scene_id;
    return plan.clips.flatMap((clip, i) => clip.scene_id === id ? [i] : []);
}
export function clipLabel(plan, index) {
    const scene = sceneForClip(plan, plan.clips[index] || {});
    return scene ? `${scene.name} · 클립 ${sceneClipIndices(plan, index).indexOf(index) + 1}` : `클립 ${index + 1}`;
}
function newScene(plan, source) {
    let number = plan.scenes.length + 1;
    while (plan.scenes.some(scene => scene.id === `scene_${number}`)) number++;
    return {id: `scene_${number}`, name: `씬 ${number}`, prompt: '', continue_previous: false,
        references: clone(source?.references || plan.references)};
}
export function appendScene(plan, index, clip) {
    ensureSequencePlan(plan);
    const scene = newScene(plan, sceneForClip(plan, plan.clips[index]));
    plan.scenes.push(scene);
    clip.scene_id = scene.id;
    plan.clips.push(clip);
    return plan.clips.length - 1;
}
export function splitSceneAt(plan, index) {
    ensureSequencePlan(plan);
    const current = sceneForClip(plan, plan.clips[index]);
    const indices = sceneClipIndices(plan, index);
    if (!current || index === indices[0]) throw new Error('씬의 두 번째 이후 클립을 선택해 분리해 주세요.');
    const scene = newScene(plan, current);
    plan.scenes.splice(plan.scenes.indexOf(current) + 1, 0, scene);
    for (const i of indices.filter(i => i >= index)) plan.clips[i].scene_id = scene.id;
    return index;
}
export function insertSceneClip(plan, index, clip, project) {
    ensureSequencePlan(plan);
    const insert = plan.sequence_mode ? sceneClipIndices(plan, index).at(-1) + 1 : plan.clips.length;
    if (Object.keys(project?.clips || {}).some(key => Number(key) > insert)) {
        throw new Error('뒤 씬에 완료된 클립이 있어 번호를 밀 수 없습니다. 새 씬을 마지막에 추가하거나 미생성 구간에서 추가해 주세요.');
    }
    clip.scene_id = plan.clips[index].scene_id;
    plan.clips.splice(insert, 0, clip);
    return insert;
}
export function pruneEmptyScenes(plan) {
    const used = new Set(plan.clips.map(clip => clip.scene_id));
    plan.scenes = plan.scenes.filter(scene => used.has(scene.id));
}
