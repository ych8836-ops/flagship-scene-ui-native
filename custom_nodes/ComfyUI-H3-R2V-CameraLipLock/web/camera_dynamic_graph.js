// Expand camera branches in the submitted prompt; keep the editable canvas intact.
const copy = value => JSON.parse(JSON.stringify(value));
const link = value => Array.isArray(value) && value.length === 2 && Number.isInteger(value[1]);
const reference = (id, slot = 0) => [String(id), slot];
const sharedInputs = new Set(["model", "clip", "vae", "audio_vae"]);
let runtimeTemplatePromise = null;

async function loadRuntimeTemplate() {
    if (!runtimeTemplatePromise) {
        runtimeTemplatePromise = fetch("/h3r2v_camera_lip_lock/runtime_template", { cache: "no-store" })
            .then(async response => {
                if (!response.ok) throw new Error(`카메라 내부 워크플로우를 불러오지 못했습니다. HTTP ${response.status}`);
                return response.json();
            })
            .catch(error => { runtimeTemplatePromise = null; throw error; });
    }
    return copy(await runtimeTemplatePromise);
}

export async function materializeCameraWorkflow(original, templateLoader = loadRuntimeTemplate) {
    const timelines = Object.entries(original).filter(([, node]) => node.class_type === "H3R2VCameraTimeline");
    if (!timelines.length) return copy(original);
    if (timelines.length !== 1) throw new Error("ONE NODE 카메라 워크플로우는 올인원 노드 하나만 사용할 수 있습니다.");
    const [, visibleTimeline] = timelines[0];
    const applyModel = workflow => {
        const selected = String(visibleTimeline.inputs?.unet_name || "").trim();
        if (!selected) return workflow;
        const loaders = Object.values(workflow).filter(node => node.class_type === "UNETLoader");
        if (!loaders.length) throw new Error("카메라 내부 워크플로우에 UNETLoader가 없습니다.");
        for (const loader of loaders) loader.inputs.unet_name = selected;
        return workflow;
    };
    const applyUpscaler = workflow => {
        const generated = Object.entries(workflow).filter(([, node]) => node.class_type === "RTXVideoVSRRestore" && node._meta?.h3_camera_generated_upscaler === true);
        if (visibleTimeline.inputs?.upscale_enabled !== true) {
            for (const [id, node] of generated) {
                for (const save of Object.values(workflow)) {
                    if (save.class_type === "SaveVideo" && link(save.inputs?.video) && String(save.inputs.video[0]) === id) save.inputs.video = copy(node.inputs.video);
                }
                delete workflow[id];
            }
            return workflow;
        }
        const saves = Object.entries(workflow).filter(([, node]) => node.class_type === "SaveVideo" && link(node.inputs?.video));
        if (saves.length !== 1) throw new Error("최종 업스케일 연결에는 SaveVideo가 정확히 하나 필요합니다.");
        const [, save] = saves[0];
        const currentSourceId = String(save.inputs.video[0]);
        let upscalerId = workflow[currentSourceId]?.class_type === "RTXVideoVSRRestore" ? currentSourceId : null;
        if (!upscalerId) {
            upscalerId = String(1 + Math.max(0, ...Object.keys(workflow).map(Number).filter(Number.isFinite)));
            workflow[upscalerId] = {
                class_type: "RTXVideoVSRRestore",
                inputs: { video: copy(save.inputs.video) },
                _meta: { title: "FINAL · SRFPTyp UPSCALE / RESTORE", h3_camera_generated_upscaler: true },
            };
            save.inputs.video = reference(upscalerId);
        }
        const inputs = workflow[upscalerId].inputs;
        Object.assign(inputs, {
            scale: Number(visibleTimeline.inputs.upscale_scale ?? 2),
            upscale_quality: visibleTimeline.inputs.upscale_quality || "Ultra",
            restore_mode: visibleTimeline.inputs.upscale_restore_mode || "Auto Scan (Clean/Chain90)",
            quality_target: visibleTimeline.inputs.upscale_quality_target || "110% Master",
            color_treatment: visibleTimeline.inputs.upscale_color_treatment || "Auto Natural",
            output_quality: Number(visibleTimeline.inputs.upscale_output_quality ?? 95),
            encode_preset: visibleTimeline.inputs.upscale_encode_preset || "slow",
            temporal_mode: visibleTimeline.inputs.upscale_temporal_mode || "Auto Temporal",
            subject_recovery: visibleTimeline.inputs.upscale_subject_recovery || "Auto",
            enabled: true,
            hdr_enabled: visibleTimeline.inputs.upscale_output_mode === "HDR",
            output_mode: visibleTimeline.inputs.upscale_output_mode || "SDR",
        });
        return workflow;
    };
    const finish = workflow => applyUpscaler(applyModel(workflow));
    if (Object.values(original).some(node => node.class_type === "H3R2VCameraLipLock")) return finish(copy(original));
    const template = await templateLoader();
    const runtimeTimelineId = Object.keys(template).find(id => template[id].class_type === "H3R2VCameraTimeline");
    if (!runtimeTimelineId) throw new Error("카메라 내부 워크플로우에 Timeline 노드가 없습니다.");
    template[runtimeTimelineId].inputs = { ...template[runtimeTimelineId].inputs, ...copy(visibleTimeline.inputs) };
    template[runtimeTimelineId]._meta = { ...template[runtimeTimelineId]._meta, ...copy(visibleTimeline._meta || {}) };
    return finish(template);
}

const shotDirectives = {
    "wide shot": "a clearly wide full-body composition with substantial environment visible around the performer; the camera is physically farther away",
    "medium shot": "a waist-up medium composition with natural headroom",
    "medium close-up": "a chest-up medium close-up with the face clearly readable",
    "close-up": "a tight face-and-shoulders close-up with the face occupying most of the frame",
    "extreme close-up": "an extreme facial close-up centered on the eyes and mouth",
    "low angle": "a distinctly low camera position looking upward at the performer with visible perspective change",
    "high angle": "a distinctly elevated camera looking downward at the performer",
    "over-the-shoulder": "an over-the-shoulder composition with a foreground shoulder edge and the performer beyond it",
    "left side profile": "a strict left-side profile, camera placed about 90 degrees to the performer's front; only the left facial profile is visible",
    "right side profile": "a strict right-side profile, camera placed about 90 degrees to the performer's front; only the right facial profile is visible",
    "rear view": "a rear view from behind the performer; the face and mouth are not visible",
    "top-down overhead view": "a strong top-down overhead composition with the camera above the performer looking downward",
};
const movementDirectives = {
    "static camera": "lock the camera position with no pan, tilt, zoom or drift",
    "slow pan left": "pan visibly and continuously to the left while keeping subject motion unchanged",
    "slow pan right": "pan visibly and continuously to the right while keeping subject motion unchanged",
    "slow tilt up": "tilt visibly upward through the shot",
    "slow tilt down": "tilt visibly downward through the shot",
    "slow dolly in": "physically dolly toward the performer with real background parallax; do not imitate this with a digital crop",
    "slow dolly out": "physically dolly away from the performer with increasing environmental coverage and real parallax",
    "smooth tracking shot": "track laterally alongside the performer with obvious but smooth background parallax",
    "smooth orbit left": "orbit left around the performer, changing viewpoint while keeping identity stable",
    "smooth orbit right": "orbit right around the performer, changing viewpoint while keeping identity stable",
    "subtle handheld": "use restrained natural handheld motion without abrupt shake",
};

export function segmentBounds(segment) {
    const start = Math.round(segment.start_seconds != null ? Number(segment.start_seconds) * 24 : Number(segment.start_frame));
    const end = Math.round(segment.end_seconds != null ? Number(segment.end_seconds) * 24 : Number(segment.end_frame));
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end - start < 5 || end - start > 360) {
        throw new Error("각 카메라 구간은 5프레임 이상, 15초 이하여야 합니다. 시작·종료 시간을 확인하세요.");
    }
    return { start, end };
}

export function splitSegment(segments, selected) {
    if (segments.length >= 64) throw new Error("카메라 구간은 최대 64개까지 지원합니다.");
    const result = copy(segments);
    const { start, end } = segmentBounds(result[selected]);
    if (end - start < 10) throw new Error("이 구간은 너무 짧습니다. 10프레임 이상인 구간을 선택하세요.");
    const mid = Math.floor((start + end) / 2);
    const part = (a, b) => ({ ...result[selected], start_frame: a, end_frame: b, start_seconds: a / 24, end_seconds: b / 24 });
    result.splice(selected, 1, part(start, mid), part(mid, end));
    return result;
}

export function removeSegment(segments, selected) {
    if (segments.length <= 1) throw new Error("구간은 최소 1개가 필요합니다.");
    const result = copy(segments);
    result.splice(selected, 1);
    return result;
}

function cameraPrompt(segment, count) {
    const shot = segment.shot || "medium shot";
    const movement = segment.movement || "static camera";
    const shotDirective = shotDirectives[shot] || shot;
    const movementDirective = movementDirectives[movement] || movement;
    return `subject_definitions:
<Subject 1> is the principal performer identified by the supplied identity crop, retaining the same face, hair and wardrobe.
<Video 1> supplies the source environment, body performance and action timing.
<Audio 1> is the synchronized soundtrack of this exact source segment, driving articulation and copied into the final output.

summary:
[reference generation + audio reuse] Rephotograph the source performance from the requested camera position while preserving its soundtrack and timing.

retention_analysis:
<Subject 1>: fully_preserved - retain the recognizable identity and wardrobe from the supplied crop without copying its framing.
<Video 1>: partially_preserved - retain the environment and physical performance, replacing camera position and framing.
<Audio 1>: fully_copy - keep the original segment waveform and timing in the final output.

detailed_description:
Natural live-action realism matching the source lighting, with stable facial anatomy and coherent background depth.
[Shot 1] Over local time 0.000-${(count / 24).toFixed(3)}s, show the same performer from <Video 1>. Replace the source camera from the very first frame. Framing command: ${shotDirective}. Movement command: ${movementDirective}, at ${segment.speed || "slow"} speed and movement amplitude ${Number(segment.strength ?? .35).toFixed(2)} on a zero-to-one scale. This is a camera-position change, not a crop of the source frame. Preserve the source action order and physical scene relationships while allowing newly revealed background geometry to remain plausible. Use the source video for performance and environment, never for its original camera position or crop. Generate mouth motion directly from <Audio 1>, matching vocal onsets, consonant closures, vowel openings, pauses and phrase endings. If source visual mouth shapes conflict with the audio, follow the audio. For side, rear or overhead views, obey the requested visibility and never rotate the face back toward the original frontal camera. Keep any visible face coherent throughout the requested move. Preserve the source cast without adding people. Use one continuous shot.

overall_soundscape:
Copy the existing speech, singing, ambience and effects in <Audio 1> at their original timing. Invent no words or sounds.

non_diegetic_music:
Keep only music already present in <Audio 1>, if any.`;
}

export function expandCameraTimelines(original) {
    const graph = copy(original);
    // API-format exports may already contain previews injected by a previous
    // submission. Remove only our generated temporary preview pairs before
    // rebuilding the branches, otherwise they look like extra final videos.
    for (const [id, generated] of Object.entries(graph)) {
        if (generated.class_type !== "H3CameraSegmentPreview") continue;
        const constructorId = link(generated.inputs?.video) ? String(generated.inputs.video[0]) : null;
        delete graph[id];
        if (constructorId && graph[constructorId]?.class_type === "CreateVideo") delete graph[constructorId];
    }
    const timelines = Object.entries(original).filter(([, n]) => n.class_type === "H3R2VCameraTimeline");
    let serial = 1 + Math.max(0, ...Object.keys(graph).map(Number).filter(Number.isFinite));
    const allocate = () => String(serial++);
    for (const [timelineId, timeline] of timelines) {
        const raw = JSON.parse(timeline.inputs.camera_plan_json);
        const segments = Array.isArray(raw) ? raw : raw.segments;
        if (!Array.isArray(segments) || !segments.length || segments.length > 64) throw new Error("카메라 구간은 1~64개로 지정하세요.");
        segments.forEach(segmentBounds);
        const preps = Object.keys(graph).filter(id => graph[id].class_type === "H3R2VCameraLipLock" && String(graph[id].inputs.images?.[0]) === timelineId);
        if (!preps.length) throw new Error("카메라 생성 분기가 없습니다. 카메라 워크플로우를 불러오세요.");
        const affected = new Set(preps);
        // Stop at the final video constructor, preserving its save/restore route.
        const constructors = new Set();
        let changed = true;
        while (changed) {
            changed = false;
            for (const [id, node] of Object.entries(graph)) {
                if (affected.has(id) || constructors.has(id)) continue;
                if (!Object.values(node.inputs).some(v => link(v) && affected.has(String(v[0])))) continue;
                if (node.class_type === "CreateVideo") constructors.add(id);
                else { affected.add(id); changed = true; }
            }
        }
        if (constructors.size !== 1) throw new Error("카메라 결과를 합치는 CreateVideo가 정확히 하나 필요합니다. 여러 저장 분기가 있는 워크플로우는 자동 변경하지 않습니다.");
        const finalId = [...constructors][0];
        let endpoint = String(graph[finalId].inputs.images?.[0]);
        while (graph[endpoint]?.class_type === "ImageBatch") endpoint = String(graph[endpoint].inputs.image1[0]);
        if (!affected.has(endpoint)) throw new Error("카메라 영상의 생성 경로를 찾을 수 없습니다.");
        const branchIds = new Set();
        function collect(id) {
            if (id === timelineId || branchIds.has(id)) return;
            const node = graph[id];
            if (!node) throw new Error(`카메라 연결 누락: ${id}`);
            branchIds.add(id);
            if (node.class_type === "H3R2VCameraLipLock") return;
            for (const [name, value] of Object.entries(node.inputs)) {
                if (link(value) && !sharedInputs.has(name)) collect(String(value[0]));
            }
        }
        collect(endpoint);
        const prepId = [...branchIds].find(id => preps.includes(id));
        if (!prepId || [...branchIds].filter(id => preps.includes(id)).length !== 1) throw new Error("구간별 카메라 템플릿을 분리할 수 없습니다.");
        const template = Object.fromEntries([...branchIds].map(id => [id, copy(graph[id])]));
        // Keep dependencies referenced from outside the replaced camera route.
        for (const id of affected) {
            const external = Object.entries(graph).some(([other, n]) => !affected.has(other) && other !== finalId && Object.values(n.inputs).some(v => link(v) && String(v[0]) === id));
            if (external) throw new Error("카메라 내부 분기를 별도 출력에서 사용 중입니다. 별도 출력을 분리한 뒤 실행하세요.");
        }
        for (const id of affected) delete graph[id];
        graph[timelineId].inputs.expected_segments = segments.length;
        const strictLipSync = timeline.inputs.lip_sync_strict !== false;
        const segmentPreview = timeline.inputs.segment_preview !== false;
        let frames, audio;
        segments.forEach((segment, index) => {
            const { start, end } = segmentBounds(segment);
            const remap = Object.fromEntries([...branchIds].map(id => [id, allocate()]));
            for (const [id, source] of Object.entries(template)) {
                const node = copy(source);
                for (const [key, value] of Object.entries(node.inputs)) if (link(value) && remap[String(value[0])]) node.inputs[key] = reference(remap[String(value[0])], value[1]);
                node._meta = { ...node._meta, title: `${source._meta?.title || source.class_type} · 구간 ${index + 1}` };
                if (id === prepId) node.inputs.segment_index = index;
                if (node.class_type === "MiniMaxH3ReferenceToVideo") {
                    node.inputs.length = 5 + Math.ceil((end - start - 5) / 17) * 17;
                    node.inputs.prompt = cameraPrompt(segment, end - start);
                }
                if (node.class_type === "BasicScheduler") {
                    node.inputs.steps = reference(timelineId, 9);
                    node.inputs.denoise = reference(timelineId, 5);
                }
                if (node.class_type === "RandomNoise" && index > 0 && typeof node.inputs.noise_seed === "number") node.inputs.noise_seed = (node.inputs.noise_seed + index) % Number.MAX_SAFE_INTEGER;
                graph[remap[id]] = node;
            }
            if (strictLipSync) {
                const condSource = [...branchIds].find(id => template[id].class_type === "MiniMaxH3ReferenceToVideo");
                const guiderSource = [...branchIds].find(id => template[id].class_type === "BasicGuider");
                const samplerSource = [...branchIds].find(id => template[id].class_type === "SamplerCustomAdvanced");
                if (condSource && guiderSource && samplerSource) {
                    const condId = remap[condSource], guiderId = remap[guiderSource], samplerId = remap[samplerSource];
                    const lockId = allocate();
                    graph[lockId] = {
                        class_type: "H3CameraExactAudioLock",
                        inputs: {
                            model: graph[guiderId].inputs.model,
                            av_latent: reference(condId, 1),
                            audio_vae: graph[condId].inputs.audio_vae,
                            audio: reference(remap[prepId], 1),
                        },
                        _meta: { title: `STRICT LIP SYNC · exact source audio · 구간 ${index + 1}` },
                    };
                    graph[guiderId].inputs.model = reference(lockId, 0);
                    graph[samplerId].inputs.latent_image = reference(lockId, 1);
                }
            }
            const nextFrames = reference(remap[endpoint]);
            const nextAudio = reference(remap[prepId], 1);
            if (segmentPreview) {
                const createPreviewId = allocate(), previewId = allocate();
                graph[createPreviewId] = {
                    class_type: "CreateVideo",
                    inputs: { images: nextFrames, audio: nextAudio, fps: reference(timelineId, 4), bit_depth: 8 },
                    _meta: { title: `구간 ${index + 1} · 프리뷰 영상 구성` },
                };
                graph[previewId] = {
                    class_type: "H3CameraSegmentPreview",
                    inputs: {
                        video: reference(createPreviewId), segment_index: index,
                        shot: String(segment.shot || "camera shot"),
                        start_seconds: start / 24, end_seconds: end / 24,
                    },
                    _meta: { title: `구간 ${index + 1} · 카메라 프리뷰` },
                };
            }
            if (index === 0) { frames = nextFrames; audio = nextAudio; }
            else {
                const imageJoin = allocate(), audioJoin = allocate();
                graph[imageJoin] = { class_type: "ImageBatch", inputs: { image1: frames, image2: nextFrames } };
                graph[audioJoin] = { class_type: "H3CameraAudioJoin", inputs: { audio1: audio, audio2: nextAudio } };
                frames = reference(imageJoin); audio = reference(audioJoin);
            }
        });
        graph[finalId].inputs.images = frames;
        graph[finalId].inputs.audio = audio;
        graph[finalId].inputs.fps = reference(timelineId, 4);
    }
    return graph;
}
