import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
import { createCameraStudio } from "./camera_studio.js";
import { expandCameraTimelines, materializeCameraWorkflow, splitSegment, removeSegment } from "./camera_dynamic_graph.js";

const cameraStudio = createCameraStudio(app, (node, studio) => createTimelinePlanner(node, studio));

const NODE_NAME = "H3R2VCameraLipLock";
const EXTENSION_NAME = "ComfyUI.H3R2VCameraLipLock.UI";

const SHOTS = [
    ["wide shot", "WIDE"],
    ["medium shot", "MEDIUM"],
    ["medium close-up", "MCU"],
    ["close-up", "CLOSE"],
    ["extreme close-up", "ECU"],
    ["low angle", "LOW ANGLE"],
    ["high angle", "HIGH ANGLE"],
    ["over-the-shoulder", "OTS"],
    ["left side profile", "SIDE L"],
    ["right side profile", "SIDE R"],
    ["rear view", "BACK"],
    ["top-down overhead view", "TOP"],
];
const MOVES = [
    ["static camera", "STATIC"],
    ["slow pan left", "PAN L"],
    ["slow pan right", "PAN R"],
    ["slow tilt up", "TILT UP"],
    ["slow tilt down", "TILT DN"],
    ["slow dolly in", "DOLLY IN"],
    ["slow dolly out", "DOLLY OUT"],
    ["smooth tracking shot", "TRACK"],
    ["smooth orbit left", "ORBIT L"],
    ["smooth orbit right", "ORBIT R"],
    ["subtle handheld", "HANDHELD"],
];
const SPEEDS = [
    ["very slow", "VERY SLOW"],
    ["slow", "SLOW"],
    ["moderate", "MODERATE"],
    ["fast", "FAST"],
];

const DEFAULT_SEGMENTS = [
    { start_frame: 0, end_frame: 124, shot: "wide shot", movement: "slow dolly in", speed: "slow", strength: 0.35 },
    { start_frame: 124, end_frame: 248, shot: "medium shot", movement: "smooth tracking shot", speed: "moderate", strength: 0.45 },
    { start_frame: 248, end_frame: 372, shot: "close-up", movement: "static camera", speed: "very slow", strength: 0.20 },
];

const COLORS = {
    bg: "#081613",
    panel: "#0d211c",
    card: "#112a23",
    field: "#07110f",
    border: "#24483d",
    borderHot: "#3bd9ac",
    text: "#e4f7ee",
    muted: "#8ba99e",
    accent: "#39e6ad",
    blue: "#51c9ff",
};

function make(tag, styles = {}, props = {}) {
    const el = document.createElement(tag);
    Object.assign(el.style, styles);
    Object.entries(props).forEach(([key, value]) => {
        if (key === "textContent") el.textContent = value;
        else if (key === "className") el.className = value;
        else el.setAttribute(key, value);
    });
    return el;
}

function label(text, size = "9px") {
    return make("div", {
        color: COLORS.muted, fontSize: size, fontWeight: "800", letterSpacing: ".08em",
        textTransform: "uppercase", whiteSpace: "nowrap",
    }, { textContent: text });
}

function getWidget(node, name) {
    return node.widgets?.find(widget => widget.name === name);
}

function setWidget(node, name, value) {
    const widget = getWidget(node, name);
    if (!widget) return;
    widget.value = value;
    try { widget.callback?.(value); } catch (_) { /* Comfy versions differ */ }
}

function wakeNode(node) {
    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
    node.graph?.change?.();
}

function migrateResolutionWidgets(node, config) {
    // Older DOM panels wrote their display label into widgets_values. It must
    // not become the new aspect-ratio value when loading an old workflow.
    const raw = config?.widgets_values;
    if (!Array.isArray(raw) || (raw.length > 10 && raw[10] !== "R2V Timeline Director")) return;
    for (const [name,value] of [["aspect_ratio","source"],["megapixels",.5],["custom_width",960],["custom_height",544]]) {
        setWidget(node,name,value);
    }
}

function setConnectedVideoLoader(node, filename) {
    const input = node.inputs?.find(item => item.name === "images");
    if (!input || input.link == null || !node.graph) return false;
    const link = node.graph.links?.[input.link];
    const source = link ? node.graph.getNodeById?.(link.origin_id) : null;
    if (!source) return false;
    const candidates = ["video", "file"];
    const widget = candidates.map(name => getWidget(source, name)).find(Boolean);
    if (!widget) return false;
    widget.value = filename;
    try { widget.callback?.(filename); } catch (_) { /* Comfy versions differ */ }
    source.setDirtyCanvas?.(true, true);
    source.graph?.setDirtyCanvas?.(true, true);
    return true;
}

function readPlan(node) {
    const widget = getWidget(node, "camera_plan_json");
    let parsed = null;
    try { parsed = JSON.parse(widget?.value || ""); } catch (_) { parsed = null; }
    const segments = Array.isArray(parsed) ? parsed : parsed?.segments;
    if (!Array.isArray(segments) || !segments.length) return DEFAULT_SEGMENTS.map(item => ({ ...item }));
    return segments.filter(item => item && typeof item === "object").map(item => ({ ...item }));
}

function writePlan(node, segments) {
    const payload = JSON.stringify({ segments }, null, 2);
    // Keep the plan identical across the one-controller-per-segment branches.
    const controllers = node.graph?._nodes?.filter(item => item.type === NODE_NAME) || [];
    (controllers.length ? controllers : [node]).forEach(controller => {
        const widget = getWidget(controller, "camera_plan_json");
        if (widget) widget.value = payload;
        controller.setDirtyCanvas?.(true, true);
    });
    wakeNode(node);
}

function normalizeSegment(segment, index) {
    const fallback = DEFAULT_SEGMENTS[index] || {
        start_frame: index * 124, end_frame: (index + 1) * 124,
        shot: "medium shot", movement: "static camera", speed: "slow", strength: 0.35,
    };
    return {
        ...fallback, ...segment,
        start_frame: Number.isFinite(Number(segment?.start_frame)) ? Number(segment.start_frame) : fallback.start_frame,
        end_frame: Number.isFinite(Number(segment?.end_frame)) ? Number(segment.end_frame) : fallback.end_frame,
        strength: Number.isFinite(Number(segment?.strength)) ? Number(segment.strength) : fallback.strength,
    };
}

function makeButton(text, active = false, accent = COLORS.accent) {
    const button = make("button", {
        flex: "1 1 auto", minWidth: "58px", height: "26px", padding: "0 7px",
        border: `1px solid ${active ? accent : COLORS.border}`, borderRadius: "6px",
        background: active ? `${accent}20` : COLORS.field, color: active ? accent : COLORS.muted,
        fontSize: "8px", fontWeight: "800", letterSpacing: ".03em", cursor: "pointer",
        outline: "none", transition: "border-color .15s, color .15s, background .15s",
    }, { type: "button", textContent: text });
    button.onmouseenter = () => { if (!button.dataset.active) { button.style.borderColor = accent; button.style.color = COLORS.text; } };
    button.onmouseleave = () => { if (!button.dataset.active) { button.style.borderColor = COLORS.border; button.style.color = COLORS.muted; } };
    return button;
}

function setActive(button, active, accent = COLORS.accent) {
    button.dataset.active = active ? "1" : "";
    button.style.borderColor = active ? accent : COLORS.border;
    button.style.background = active ? `${accent}20` : COLORS.field;
    button.style.color = active ? accent : COLORS.muted;
}

function createController(node) {
    const root = make("div", {
        width: "100%", boxSizing: "border-box", padding: "10px", background: COLORS.bg,
        border: `1px solid ${COLORS.border}`, borderRadius: "10px", color: COLORS.text,
        fontFamily: "Inter, Segoe UI, sans-serif", userSelect: "none",
    }, { className: "h3-camera-lip-lock-ui" });

    const header = make("div", { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" });
    const title = make("div", { fontSize: "12px", fontWeight: "900", letterSpacing: ".04em", color: COLORS.text }, { textContent: "CAMERA + LIP LOCK" });
    const state = make("div", { fontSize: "8px", fontWeight: "800", color: COLORS.accent, letterSpacing: ".06em" }, { textContent: "SOURCE AUDIO LOCKED" });
    header.append(title, state);
    root.append(header);

    const sourceRow = make("div", { display: "flex", alignItems: "center", gap: "7px", padding: "7px", marginBottom: "8px", background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: "7px" });
    const sourceInput = make("input", { display: "none" }, { type: "file", accept: "video/*" });
    const sourceButton = makeButton("UPLOAD SOURCE VIDEO", false, COLORS.blue);
    sourceButton.style.flex = "0 0 auto";
    const sourceName = make("div", { minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: COLORS.muted, fontSize: "9px" }, { textContent: "영상 미리보기 없음" });
    const sourceStatus = make("div", { marginLeft: "auto", color: COLORS.muted, fontSize: "8px", whiteSpace: "nowrap" }, { textContent: "선택 대기" });
    sourceRow.append(sourceButton, sourceInput, sourceName, sourceStatus);
    sourceButton.onclick = () => { sourceInput.value = ""; sourceInput.click(); };
    root.append(sourceRow);

    const hint = make("div", { color: COLORS.muted, fontSize: "9px", lineHeight: "1.4", marginBottom: "8px" }, { textContent: "영상을 올린 뒤 재생 위치에서 시작·끝을 지정하세요. 구간 버튼은 편집 대상이고, 변경값은 모든 구간 컨트롤러에 동기화됩니다." });
    root.append(hint);

    const previewWrap = make("div", { display: "none", marginBottom: "8px", background: "#030907", border: `1px solid ${COLORS.border}`, borderRadius: "7px", overflow: "hidden" });
    const preview = make("video", { display: "block", width: "100%", maxHeight: "190px", objectFit: "contain", background: "#020605" }, { controls: "true", preload: "metadata", playsinline: "true" });
    const previewMeta = make("div", { display: "flex", justifyContent: "space-between", padding: "5px 7px", color: COLORS.muted, fontSize: "8px" });
    const currentTime = make("span", {}, { textContent: "00:00.00" });
    const durationText = make("span", {}, { textContent: "길이 확인 중" });
    previewMeta.append(currentTime, durationText); previewWrap.append(preview, previewMeta); root.append(previewWrap);

    let sourceObjectUrl = null;
    let videoDuration = 0;
    let currentVideoName = "";
    const formatTime = seconds => {
        const safe = Math.max(0, Number(seconds) || 0);
        const minutes = Math.floor(safe / 60);
        const secs = safe - minutes * 60;
        return `${String(minutes).padStart(2, "0")}:${secs.toFixed(2).padStart(5, "0")}`;
    };
    preview.addEventListener("timeupdate", () => { currentTime.textContent = formatTime(preview.currentTime); });
    preview.addEventListener("loadedmetadata", () => {
        videoDuration = Number(preview.duration) || 0;
        durationText.textContent = `전체 ${formatTime(videoDuration)}`;
        sourceStatus.textContent = videoDuration ? `${formatTime(videoDuration)} · 준비됨` : "준비됨";
        renderAll();
    });
    const uploadVideo = async file => {
        if (sourceObjectUrl) URL.revokeObjectURL(sourceObjectUrl);
        sourceObjectUrl = URL.createObjectURL(file);
        preview.src = sourceObjectUrl; previewWrap.style.display = "block"; preview.load();
        sourceName.textContent = file.name; sourceStatus.textContent = "업로드 중...";
        const body = new FormData(); body.append("file", file, file.name);
        try {
            const response = await fetch("/h3r2v_camera_lip_lock/upload", { method: "POST", body });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
            currentVideoName = data.filename;
            const linked = setConnectedVideoLoader(node, data.filename);
            sourceStatus.textContent = linked ? "로더 자동 연결됨" : "업로드 완료 · 로더 확인";
        } catch (error) {
            sourceStatus.textContent = "업로드 실패";
            console.warn("[H3 R2V Camera + Lip Lock] video upload failed", error);
        }
    };
    sourceInput.onchange = () => { if (sourceInput.files?.[0]) uploadVideo(sourceInput.files[0]); };

    const segmentBar = make("div", { display: "flex", gap: "5px", flexWrap: "wrap", marginBottom: "9px" });
    const segmentButtons = [];
    const shotButtons = [];
    const moveButtons = [];
    const speedButtons = [];
    let segments = readPlan(node).map(normalizeSegment);
    let selected = Math.max(0, Number(getWidget(node, "segment_index")?.value || 0));
    if (selected >= segments.length) selected = segments.length - 1;

    const selectedSegment = () => segments[selected] || (segments[selected] = normalizeSegment({}, selected));
    const syncTimelineSeconds = () => {
        const item = selectedSegment();
        const fps = Number(getWidget(node, "source_fps")?.value || 24) || 24;
        item.start_seconds = Math.max(0, Number(item.start_frame || 0) / fps);
        item.end_seconds = Math.max(item.start_seconds, Number(item.end_frame || 0) / fps);
        return fps;
    };
    const syncCurrentNode = () => {
        const item = selectedSegment();
        setWidget(node, "camera_shot", item.shot);
        setWidget(node, "camera_movement", item.movement);
        setWidget(node, "camera_speed", item.speed);
        setWidget(node, "camera_strength", Number(item.strength));
        writePlan(node, segments);
    };
    const renderSegmentButtons = () => {
        segmentBar.replaceChildren();
        segmentButtons.length = 0;
        segments.forEach((_, index) => {
            const button = makeButton(`SEGMENT ${index + 1}`, index === selected, COLORS.blue);
            button.style.minWidth = "86px";
            button.onclick = () => { selected = index; renderAll(); };
            segmentButtons.push(button);
            segmentBar.append(button);
        });
        const add = makeButton("+ ADD", false, COLORS.accent);
        add.style.minWidth = "60px";
        add.onclick = () => {
            const last = segments[segments.length - 1] || DEFAULT_SEGMENTS[0];
            const next = normalizeSegment({
                start_frame: Number(last.end_frame) || segments.length * 124,
                end_frame: (Number(last.end_frame) || segments.length * 124) + 124,
                shot: "medium shot", movement: "static camera", speed: "slow", strength: 0.35,
            }, segments.length);
            segments.push(next); selected = segments.length - 1; syncCurrentNode(); renderAll();
        };
        segmentBar.append(add);
    };
    root.append(segmentBar);

    const makeSection = (titleText, choices, target, accent = COLORS.accent) => {
        const wrap = make("div", { marginBottom: "8px" });
        wrap.append(label(titleText));
        const row = make("div", { display: "flex", gap: "4px", flexWrap: "wrap", marginTop: "4px" });
        choices.forEach(([value, text]) => {
            const button = makeButton(text, false, accent);
            button.onclick = () => { selectedSegment()[target] = value; syncCurrentNode(); renderAll(); };
            row.append(button); choices === SHOTS ? shotButtons.push(button) : choices === MOVES ? moveButtons.push(button) : speedButtons.push(button);
        });
        wrap.append(row); root.append(wrap); return wrap;
    };
    makeSection("SHOT / FRAMING", SHOTS, "shot", COLORS.blue);
    makeSection("CAMERA MOVEMENT", MOVES, "movement", COLORS.accent);
    makeSection("MOVEMENT SPEED", SPEEDS, "speed", "#e8c56a");

    const timeline = make("div", { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginBottom: "8px" });
    const makeNumber = (titleText, key) => {
        const wrap = make("div", { display: "flex", alignItems: "center", gap: "5px", padding: "5px 7px", background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: "6px" });
        wrap.append(label(titleText));
        const input = make("input", { minWidth: "0", width: "100%", background: "transparent", border: "0", outline: "0", color: COLORS.text, fontSize: "11px", fontWeight: "800", textAlign: "right" }, { type: "number", min: "0", step: "1" });
        input.onchange = () => { selectedSegment()[key] = Math.max(0, parseInt(input.value || "0", 10)); syncCurrentNode(); renderAll(); };
        wrap.append(input); timeline.append(wrap); return input;
    };
    const startInput = makeNumber("START", "start_frame");
    const endInput = makeNumber("END", "end_frame");
    root.append(timeline);

    const timeControls = make("div", { display: "flex", gap: "5px", flexWrap: "wrap", alignItems: "center", marginBottom: "8px" });
    const setStart = makeButton("SET START AT PLAYHEAD", false, COLORS.blue);
    const setEnd = makeButton("SET END AT PLAYHEAD", false, COLORS.blue);
    const playheadHint = make("div", { flex: "1 1 120px", color: COLORS.muted, fontSize: "8px", lineHeight: "1.3" }, { textContent: "영상 재생 위치를 움직인 뒤 버튼을 누르세요." });
    setStart.style.minWidth = "125px"; setEnd.style.minWidth = "125px";
    setStart.onclick = () => {
        if (!videoDuration) return;
        const fps = Number(getWidget(node, "source_fps")?.value || 24) || 24;
        const item = selectedSegment(); item.start_seconds = preview.currentTime; item.start_frame = Math.round(preview.currentTime * fps);
        if (item.end_frame <= item.start_frame) item.end_frame = item.start_frame + Math.round(124);
        syncCurrentNode(); renderAll();
    };
    setEnd.onclick = () => {
        if (!videoDuration) return;
        const fps = Number(getWidget(node, "source_fps")?.value || 24) || 24;
        const item = selectedSegment(); item.end_seconds = preview.currentTime; item.end_frame = Math.max(item.start_frame + 5, Math.round(preview.currentTime * fps));
        syncCurrentNode(); renderAll();
    };
    timeControls.append(setStart, setEnd, playheadHint); root.append(timeControls);

    const sliders = make("div", { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "7px", marginBottom: "9px" });
    const makeSlider = (titleText, key, min, max, step, accent) => {
        const wrap = make("div", { padding: "7px", background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: "6px" });
        const top = make("div", { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" });
        const value = make("span", { color: accent, fontSize: "10px", fontWeight: "900" });
        top.append(label(titleText), value); wrap.append(top);
        const input = make("input", { width: "100%", accentColor: accent, cursor: "pointer" }, { type: "range", min, max, step });
        input.oninput = () => {
            const next = Number(input.value);
            if (key === "lip_lock_strength") setWidget(node, "lip_lock_strength", next);
            else selectedSegment()[key] = next;
            value.textContent = next.toFixed(2);
            if (key !== "lip_lock_strength") syncCurrentNode();
            else { writePlan(node, segments); wakeNode(node); }
        };
        wrap.append(input); sliders.append(wrap); return { input, value };
    };
    const motionSlider = makeSlider("MOTION STRENGTH", "strength", "0", "1", "0.05", COLORS.accent);
    const lipSlider = makeSlider("LEGACY · NOT A LIP TRACKER", "lip_lock_strength", "0", "1", "0.01", COLORS.blue);
    lipSlider.input.disabled = true;
    root.append(sliders);

    const footer = make("div", { display: "flex", gap: "6px", alignItems: "center" });
    const reset = makeButton("RESET 3 SEGMENTS", false, "#e88d7e");
    reset.style.flex = "0 0 auto";
    reset.onclick = () => { segments = DEFAULT_SEGMENTS.map(item => ({ ...item })); selected = 0; syncCurrentNode(); renderAll(); };
    const status = make("div", { flex: "1", color: COLORS.muted, fontSize: "8px", textAlign: "right", lineHeight: "1.3" });
    footer.append(reset, status); root.append(footer);

    function renderAll() {
        const item = selectedSegment();
        segments = segments.map((segment, index) => normalizeSegment(segment, index));
        syncTimelineSeconds();
        setActiveButtons(shotButtons, SHOTS, item.shot, COLORS.blue);
        setActiveButtons(moveButtons, MOVES, item.movement, COLORS.accent);
        setActiveButtons(speedButtons, SPEEDS, item.speed, "#e8c56a");
        segmentButtons.forEach((button, index) => setActive(button, index === selected, COLORS.blue));
        startInput.value = item.start_frame; endInput.value = item.end_frame;
        motionSlider.input.value = Number(item.strength); motionSlider.value.textContent = Number(item.strength).toFixed(2);
        const lip = Number(getWidget(node, "lip_lock_strength")?.value ?? 0.98);
        lipSlider.input.value = lip; lipSlider.value.textContent = lip.toFixed(2);
        status.textContent = `SEGMENT ${selected + 1}  ·  ${item.start_frame}–${item.end_frame} FRAMES  ·  ${item.shot} / ${item.movement}`;
        if (videoDuration) {
            playheadHint.textContent = `SEGMENT ${selected + 1}: ${formatTime(item.start_seconds)} → ${formatTime(item.end_seconds)}  ·  ${Math.max(0, item.end_seconds - item.start_seconds).toFixed(2)}s`;
        }
    }
    function setActiveButtons(buttons, choices, value, accent) {
        buttons.forEach((button, index) => setActive(button, choices[index][0] === value, accent));
    }

    renderSegmentButtons(); renderAll();
    return { root, dispose() { if (sourceObjectUrl) URL.revokeObjectURL(sourceObjectUrl); } };
}

function createTimelinePlanner(node, studio = false) {
    const hasEnforcedCamera = () => !!(node.graph || app.graph)?._nodes?.some(n => n.type === "H3CameraReframe");
    const directMode = () => node.properties?.h3Camera2D === true;
    const hybridMode = () => !directMode() && hasEnforcedCamera();
    const directShots = ["wide shot", "medium shot", "medium close-up", "close-up", "extreme close-up"];
    const directMoves = ["static camera", "slow pan left", "slow pan right", "slow tilt up", "slow tilt down", "slow dolly in", "slow dolly out", "smooth tracking shot"];
    const defaults = () => DEFAULT_SEGMENTS.map(item => ({...item, ...((directMode()||hybridMode()) && !directMoves.includes(item.movement) ? {movement:"slow pan right"} : {})}));
    const root = make("div", {
        width: "100%", boxSizing: "border-box", padding: "12px", background: COLORS.bg, display: "flex", flexDirection: "column",
        border: `1px solid ${COLORS.border}`, borderRadius: "10px", color: COLORS.text,
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", userSelect: "none", height: "700px", minWidth: "0", overflow: "hidden",
    }, { className: "h3-r2v-timeline-ui" });
    const header = make("div", { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", flexWrap: "wrap", marginBottom: "8px" });
    const headerActions = make("div", { display: "flex", alignItems: "center", justifyContent: "flex-end", gap: "6px", flexWrap: "wrap" });
    headerActions.append(make("div", { fontSize: "8px", fontWeight: "800", color: COLORS.accent, letterSpacing: ".08em" }, { textContent: "CAMERA · SOURCE AUDIO" }));
    if (!studio) {
        const studioButton = makeButton("올인원 화면 열기", false, COLORS.accent);
        studioButton.style.padding = "7px 11px";
        studioButton.style.fontSize = "10px";
        studioButton.title = "카메라 타임라인을 전체화면 올인원 UI로 엽니다.";
        studioButton.onclick = () => cameraStudio.toggle(node);
        node.__h3CameraStudioButton = studioButton;
        headerActions.append(studioButton);
    }
    header.append(
        make("div", { flex: "1 1 240px", minWidth: "0", fontSize: "14px", fontWeight: "900", letterSpacing: ".04em" }, { textContent: "H3 R2V CAMERA · ALL IN ONE" }),
        headerActions,
    );
    root.append(header);
    const modelPanel = make("div", {padding:"9px",marginBottom:"9px",border:`1px solid ${COLORS.borderHot}`,borderRadius:"8px",background:"#101d1b"});
    modelPanel.append(label("메인 모델 선택 · DIFFUSION MODEL"));
    const modelSelect = make("select", {width:"100%",background:COLORS.field,color:COLORS.text,marginTop:"6px",padding:"8px",border:`1px solid ${COLORS.borderHot}`,borderRadius:"6px",fontWeight:"700"});
    const modelWidget = getWidget(node,"unet_name");
    const modelChoices = modelWidget?.options?.values;
    for (const name of (Array.isArray(modelChoices) ? modelChoices : [])) modelSelect.append(make("option", {}, {value:name,textContent:name}));
    if (!modelSelect.options.length) modelSelect.append(make("option", {}, {value:"",textContent:"설치된 H3 모델을 찾지 못했습니다"}));
    modelSelect.onchange = () => { setWidget(node,"unet_name",modelSelect.value); wakeNode(node); };
    modelPanel.append(modelSelect, make("div", {fontSize:"9px",color:COLORS.muted,marginTop:"5px"}, {textContent:"선택한 모델이 생성 시 내부 UNET Loader에 자동 적용됩니다."}));
    root.append(modelPanel);
    const modeNotice = make("div", {padding:"10px",marginBottom:"8px",fontSize:"12px",lineHeight:"1.5",color:"#ffe0a3",background:"#2c2719",borderRadius:"6px"});
    root.append(modeNotice);
    const workflowHint = make("div", { color: COLORS.muted, fontSize: "11px", lineHeight: "1.45", marginBottom: "9px" }, { textContent: "영상에서 구간을 선택하고 추가·삭제하세요. 1~64개 구간의 생성과 원본 오디오 합치기가 자동 연결됩니다. 각 구간 최대 15초." });
    root.append(workflowHint);
    const optimizerPanel = make("div", {padding:"8px",marginBottom:"9px",border:`1px solid ${COLORS.border}`,borderRadius:"7px"});
    optimizerPanel.append(label("R2V MODEL · LoRA / OPTIMIZERS"));
    const loraSelect=make("select", {width:"100%",background:COLORS.field,color:COLORS.text,marginTop:"6px",padding:"6px",border:`1px solid ${COLORS.border}`});
    const loraWidget=getWidget(node,"lora_name");
    const loraChoices=loraWidget?.options?.values;
    for(const name of (Array.isArray(loraChoices)?loraChoices:["None"])) loraSelect.append(make("option",{}, {value:name,textContent:name}));
    loraSelect.onchange=()=>setWidget(node,"lora_name",loraSelect.value);
    optimizerPanel.append(loraSelect);
    const optimizerRow=make("div",{display:"flex",gap:"5px",flexWrap:"wrap",marginTop:"6px"});
    const toggles={};
    for(const [key,title] of [["sage_enabled","SAGE"],["spectrum_enabled","SPECTRUM"],["lip_sync_strict","립싱크 엄격"]]){
        const b=makeButton(title,false,key==="lip_sync_strict"?COLORS.blue:COLORS.accent);b.onclick=()=>{
            const next=!getWidget(node,key)?.value;setWidget(node,key,next);
            if(key==="lip_sync_strict"&&next)setWidget(node,"spectrum_enabled",false);
            syncOptimizers();
        };
        toggles[key]={b,title};optimizerRow.append(b);
    }
    const numericControls={};
    for(const [key,title,min,max,step] of [["steps","STEPS",1,100,1],["lora_strength","LoRA",0,2,.05]]){
        const wrap=make("label",{fontSize:"9px",color:COLORS.muted},{textContent:title+" "});
        const input=make("input",{width:"60px",background:COLORS.field,color:COLORS.text,border:`1px solid ${COLORS.border}`},{type:"number",min:String(min),max:String(max),step:String(step)});
        input.onchange=()=>{setWidget(node,key,Math.max(min,Math.min(max,Number(input.value)||min)));syncOptimizers();};
        numericControls[key]=input;wrap.append(input);optimizerRow.append(wrap);
    }
    optimizerPanel.append(optimizerRow);root.append(optimizerPanel);
    function syncOptimizers(){
        modelSelect.value=String(getWidget(node,"unet_name")?.value||"");
        loraSelect.value=String(getWidget(node,"lora_name")?.value||"None");
        for(const [key,{b,title}] of Object.entries(toggles)){const on=!!getWidget(node,key)?.value;b.textContent=`${title} · ${on?"ON":"OFF"}`;setActive(b,on,COLORS.accent);}
        const strict=!!getWidget(node,"lip_sync_strict")?.value;
        if(strict&&getWidget(node,"spectrum_enabled")?.value)setWidget(node,"spectrum_enabled",false);
        if(toggles.spectrum_enabled){toggles.spectrum_enabled.b.disabled=strict;toggles.spectrum_enabled.b.textContent=strict?"SPECTRUM · 립싱크로 OFF":`SPECTRUM · ${getWidget(node,"spectrum_enabled")?.value?"ON":"OFF"}`;toggles.spectrum_enabled.b.title=strict?"정확한 음성 시간축을 위해 자동 비활성화됩니다.":"";}
        for(const [key,input] of Object.entries(numericControls)) input.value=getWidget(node,key)?.value??(key==="steps"?8:1);
    }
    syncOptimizers();
    const resolutionPanel=make("div",{padding:"8px",marginBottom:"9px",border:`1px solid ${COLORS.border}`,borderRadius:"7px"});
    resolutionPanel.append(label("출력 해상도 · 종횡비 / 메가픽셀"));
    const resolutionRow=make("div",{display:"flex",gap:"6px",marginTop:"6px",alignItems:"center"});
    const aspectSelect=make("select",{flex:"1",background:COLORS.field,color:COLORS.text,padding:"6px",border:`1px solid ${COLORS.border}`});
    for(const value of ["source","16:9","9:16","1:1","4:3","3:4","21:9","9:21","3:2","2:3","4:5","5:4","1:2","2:1","custom"]){
        aspectSelect.append(make("option",{}, {value,textContent:value==="source"?"원본 비율 유지":value==="custom"?"직접 입력 (Custom)":value}));
    }
    const mpInput=make("input",{width:"72px",background:COLORS.field,color:COLORS.text,border:`1px solid ${COLORS.border}`},{type:"number",min:"0.1",max:"4",step:"0.05",title:"메가픽셀 (MP)"});
    resolutionRow.append(aspectSelect,mpInput,make("span",{fontSize:"10px"},{textContent:"MP"}));resolutionPanel.append(resolutionRow);
    const customRow=make("div",{display:"none",gap:"6px",marginTop:"6px"});
    const dimensions={};
    for(const [key,title] of [["custom_width","가로"],["custom_height","세로"]]){
        const lab=make("label",{fontSize:"10px"},{textContent:title+" "});
        const input=make("input",{width:"85px",background:COLORS.field,color:COLORS.text},{type:"number",min:"32",max:"4096",step:"32"});
        input.onchange=()=>{setWidget(node,key,Math.max(32,Math.min(4096,Math.round(Number(input.value)/32)*32)));syncResolution();};
        dimensions[key]=input;lab.append(input);customRow.append(lab);
    }
    resolutionPanel.append(customRow);
    const resolutionBadge=make("div",{color:COLORS.accent,fontSize:"11px",fontWeight:"800",marginTop:"7px"});
    resolutionPanel.append(resolutionBadge,make("div",{fontSize:"9px",color:COLORS.muted,marginTop:"4px"},{textContent:"32배수 자동 정렬 · 비율 변경 시 중앙 크롭 · 높은 해상도는 VRAM/시간 증가"}));root.append(resolutionPanel);
    let sourceDimensions=null;
    aspectSelect.onchange=()=>{setWidget(node,"aspect_ratio",aspectSelect.value);syncResolution();};
    mpInput.oninput=()=>{
        const value=Number(mpInput.value);
        if(mpInput.value!==""&&Number.isFinite(value)&&value>=.1&&value<=4){
            setWidget(node,"megapixels",value);wakeNode(node);syncResolution();
        }
    };
    mpInput.onchange=()=>{
        const value=Number(mpInput.value);
        if(mpInput.value!==""&&Number.isFinite(value)) setWidget(node,"megapixels",Math.max(.1,Math.min(4,value)));
        wakeNode(node);syncResolution();
    };
    function syncResolution(){
        const ready=["aspect_ratio","megapixels","custom_width","custom_height"].every(name=>!!getWidget(node,name));
        aspectSelect.disabled=!ready;
        if(!ready){
            mpInput.disabled=true;mpInput.value="";mpInput.placeholder="재시작 필요";
            customRow.style.display="none";
            resolutionBadge.style.color="#f3b562";
            resolutionBadge.textContent="이전 노드가 실행 중입니다. 워크플로우 저장 → ComfyUI 재시작 → Ctrl+F5 후 다시 불러오세요. 현재 해상도 선택은 적용되지 않습니다.";
            return;
        }
        const aspect=String(getWidget(node,"aspect_ratio")?.value||"source");
        const mp=Number(getWidget(node,"megapixels")?.value??.5);
        aspectSelect.value=aspect;if(document.activeElement!==mpInput) mpInput.value=mp;mpInput.disabled=aspect==="custom";
        customRow.style.display=aspect==="custom"?"flex":"none";
        for(const [key,input] of Object.entries(dimensions)) input.value=getWidget(node,key)?.value??(key==="custom_width"?960:544);
        const snap=v=>Math.max(32,Math.round(v/32)*32);
        let width,height;
        if(aspect==="custom"){width=snap(Number(dimensions.custom_width.value));height=snap(Number(dimensions.custom_height.value));}
        else{
            if(aspect==="source"&&!sourceDimensions){resolutionBadge.textContent=`원본 영상 업로드 후 계산 · ${mp.toFixed(2)} MP`;return;}
            const ratio=aspect==="source"?sourceDimensions[0]/sourceDimensions[1]:aspect.split(":").reduce((a,b)=>Number(a)/Number(b));
            width=snap(Math.sqrt(mp*1e6*ratio));height=snap(Math.sqrt(mp*1e6/ratio));
        }
        const warning=Math.max(width,height)>1344||Math.min(width,height)>768;
        resolutionBadge.style.color=warning?"#f3b562":COLORS.accent;
        resolutionBadge.textContent=`${width} × ${height} · ${(width*height/1e6).toFixed(3)} MP${warning?" · 고해상도 주의":""}`;
    }
    syncResolution();

    const sourceRow = make("div", { display: "flex", alignItems: "center", gap: "7px", flexWrap: "wrap", padding: "7px", marginBottom: "8px", background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: "7px" });
    const fileInput = make("input", { display: "none" }, { type: "file", accept: "video/*" });
    const upload = makeButton("UPLOAD SOURCE VIDEO", false, COLORS.blue); upload.style.flex = "0 0 auto";
    const fileLabel = make("div", { minWidth: "120px", flex: "1 1 180px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: COLORS.muted, fontSize: "9px" }, { textContent: "영상 파일을 선택하세요" });
    const fileState = make("div", { color: COLORS.muted, fontSize: "8px", whiteSpace: "nowrap" }, { textContent: "WAITING" });
    sourceRow.append(upload, fileInput, fileLabel, fileState); root.append(sourceRow);

    const previewWrap = make("div", { display: "none", marginBottom: "9px", background: "#030907", border: `1px solid ${COLORS.border}`, borderRadius: "7px", overflow: "hidden" });
    const preview = make("video", { display: "block", width: "100%", maxHeight: "220px", objectFit: "contain", background: "#020605" }, { controls: "true", preload: "metadata", playsinline: "true" });
    const meta = make("div", { display: "flex", justifyContent: "space-between", padding: "6px 8px", color: COLORS.muted, fontSize: "8px" });
    const playhead = make("span", {}, { textContent: "PLAYHEAD 00:00.00" });
    const duration = make("span", {}, { textContent: "DURATION --:--" });
    meta.append(playhead, duration); previewWrap.append(preview, meta); root.append(previewWrap);
    const resultSection = make("section", { display: "flex", flexDirection: "column", minHeight: "250px", marginBottom: "10px", padding: "8px", background: COLORS.card, border: `1px solid ${COLORS.borderHot}`, borderRadius: "8px", minWidth: "0" });
    const resultHeader = make("div", { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", flexWrap: "wrap", marginBottom: "6px" });
    const resultStatus = make("span", { color: COLORS.accent, fontSize: "9px", fontWeight: "800" }, { textContent: "생성 완료" });
    resultHeader.append(label("생성 결과 · OUTPUT PREVIEW"), resultStatus);
    const resultPlaceholder = make("div", { display: "flex", flex: "1", minHeight: "210px", alignItems: "center", justifyContent: "center", padding: "18px", boxSizing: "border-box", textAlign: "center", color: COLORS.muted, fontSize: "11px", lineHeight: "1.55", background: "#020605", borderRadius: "6px" }, { textContent: "생성이 완료되면 최종 영상이 여기에 자동으로 표시됩니다." });
    const resultPreview = make("video", { display: "none", width: "100%", flex: "1", minHeight: "210px", maxHeight: "410px", objectFit: "contain", background: "#020605", borderRadius: "6px" }, { controls: "true", preload: "metadata", playsinline: "true" });
    resultSection.append(resultHeader, resultPlaceholder, resultPreview); root.append(resultSection);
    const upscalePanel = make("section", { marginBottom:"10px", padding:"9px", background:"#071410", border:`1px solid ${COLORS.borderHot}`, borderRadius:"8px", minWidth:"0" });
    const upscaleHeader = make("div", {display:"flex",alignItems:"center",justifyContent:"space-between",gap:"8px"});
    const upscaleToggle = makeButton("업스케일 · OFF", false, COLORS.accent);
    upscaleHeader.append(label("최종 영상 · SRFPTyp 업스케일/복원"), upscaleToggle);
    const upscaleBody = make("div", {display:"grid",gridTemplateColumns:"repeat(2,minmax(0,1fr))",gap:"6px",marginTop:"8px"});
    const upscaleControls = {};
    const addUpscaleSelect = (key,title,choices) => {
        const wrap=make("label",{display:"grid",gap:"3px",fontSize:"8px",color:COLORS.muted},{textContent:title});
        const select=make("select",{minWidth:"0",width:"100%",padding:"6px",background:COLORS.field,color:COLORS.text,border:`1px solid ${COLORS.border}`,borderRadius:"5px"});
        for(const value of choices) select.append(make("option",{},{value,textContent:value}));
        select.onchange=()=>{setWidget(node,key,select.value);wakeNode(node);};
        upscaleControls[key]=select;wrap.append(select);upscaleBody.append(wrap);
    };
    const scaleWrap=make("label",{display:"grid",gap:"3px",fontSize:"8px",color:COLORS.muted},{textContent:"확대 배수"});
    const scaleInput=make("input",{width:"100%",boxSizing:"border-box",padding:"6px",background:COLORS.field,color:COLORS.text,border:`1px solid ${COLORS.border}`,borderRadius:"5px"},{type:"number",min:"1",max:"4",step:"0.05"});
    scaleInput.onchange=()=>{setWidget(node,"upscale_scale",Math.max(1,Math.min(4,Number(scaleInput.value)||2)));syncUpscale();wakeNode(node);};
    upscaleControls.upscale_scale=scaleInput;scaleWrap.append(scaleInput);upscaleBody.append(scaleWrap);
    const qualityWrap=make("label",{display:"grid",gap:"3px",fontSize:"8px",color:COLORS.muted},{textContent:"저장 품질 (80–99)"});
    const qualityInput=make("input",{width:"100%",boxSizing:"border-box",padding:"6px",background:COLORS.field,color:COLORS.text,border:`1px solid ${COLORS.border}`,borderRadius:"5px"},{type:"number",min:"80",max:"99",step:"1"});
    qualityInput.onchange=()=>{setWidget(node,"upscale_output_quality",Math.max(80,Math.min(99,Math.round(Number(qualityInput.value)||95))));syncUpscale();wakeNode(node);};
    upscaleControls.upscale_output_quality=qualityInput;qualityWrap.append(qualityInput);upscaleBody.append(qualityWrap);
    addUpscaleSelect("upscale_quality","확대 엔진",["Ultra","High","High-Bitrate Ultra","High-Bitrate High"]);
    addUpscaleSelect("upscale_restore_mode","복원 모드",["Auto Scan (Clean/Chain90)","Deblur Low","Deblur Medium","Denoise Low","Denoise Low + Deblur Low","Chain Late Recovery 90"]);
    addUpscaleSelect("upscale_temporal_mode","시간축 안정화",["Auto Temporal","Face Lock","Action Stable","Off"]);
    addUpscaleSelect("upscale_subject_recovery","인물 복원",["Auto","Full Shot Strong","Off"]);
    addUpscaleSelect("upscale_quality_target","마스터링",["100% Restore","105% Master","110% Master"]);
    addUpscaleSelect("upscale_color_treatment","색감 보정",["Off","Auto Natural","Auto Bright"]);
    addUpscaleSelect("upscale_encode_preset","인코딩",["medium","slow","slower"]);
    addUpscaleSelect("upscale_output_mode","출력 색상",["SDR","SDR 10bit","HDR"]);
    upscalePanel.append(upscaleHeader,upscaleBody,make("div",{fontSize:"8px",color:COLORS.muted,marginTop:"6px"},{textContent:"ON: 최종 조립 영상 → 업스케일/복원 → 저장 · OFF: 원본 조립 영상을 바로 저장"}));
    function syncUpscale(){
        const enabled=getWidget(node,"upscale_enabled")?.value===true;
        upscaleToggle.textContent=`업스케일 · ${enabled?"ON":"OFF"}`;setActive(upscaleToggle,enabled,COLORS.accent);
        upscaleBody.style.opacity=enabled?"1":".42";
        for(const [key,control] of Object.entries(upscaleControls)){control.disabled=!enabled;control.value=String(getWidget(node,key)?.value??(key==="upscale_scale"?2:key==="upscale_output_quality"?95:""));}
    }
    upscaleToggle.onclick=()=>{setWidget(node,"upscale_enabled",!(getWidget(node,"upscale_enabled")?.value===true));syncUpscale();wakeNode(node);};
    syncUpscale();
    const segmentPreviewSection = make("section", { marginBottom: "10px", padding: "8px", background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: "8px", minWidth: "0" });
    const segmentPreviewHeader = make("div", { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "7px", marginBottom: "7px" });
    const segmentPreviewToggle = makeButton("구간 프리뷰 · ON", true, COLORS.blue);
    Object.assign(segmentPreviewToggle.style, { flex: "0 0 auto", minWidth: "108px" });
    segmentPreviewHeader.append(label("카메라 구간별 프리뷰"), segmentPreviewToggle);
    const segmentPreviewGrid = make("div", { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "6px", maxHeight: "330px", overflowY: "auto", paddingRight: "2px", scrollbarWidth: "thin" });
    segmentPreviewSection.append(segmentPreviewHeader, segmentPreviewGrid); root.append(segmentPreviewSection);
    const segmentPreviewItems = new Map();
    const renderSegmentPreviews = () => {
        segmentPreviewGrid.replaceChildren();
        segments.forEach((segment, index) => {
            const item = segmentPreviewItems.get(index);
            const card = make("div", { minWidth: "0", padding: "5px", borderRadius: "7px", background: COLORS.field, border: `1px solid ${index === selected ? COLORS.blue : COLORS.border}`, cursor: "pointer" });
            const title = make("div", { color: index === selected ? COLORS.blue : COLORS.text, fontSize: "8px", fontWeight: "900", marginBottom: "4px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, { textContent: `SEGMENT ${index + 1} · ${segment.shot || "SHOT"}` });
            if (item?.filename) {
                const video = make("video", { display: "block", width: "100%", aspectRatio: "16 / 9", objectFit: "contain", background: "#020605", borderRadius: "5px" }, { controls: "true", preload: "metadata", playsinline: "true" });
                video.src = api.apiURL(`/view?filename=${encodeURIComponent(item.filename)}&type=${encodeURIComponent(item.type || "temp")}&subfolder=${encodeURIComponent(item.subfolder || "")}&t=${Date.now()}`);
                video.onclick = event => event.stopPropagation();
                card.append(title, video);
            } else {
                const waiting = make("div", { display: "flex", aspectRatio: "16 / 9", alignItems: "center", justifyContent: "center", padding: "7px", boxSizing: "border-box", textAlign: "center", color: COLORS.muted, fontSize: "8px", background: "#020605", borderRadius: "5px" }, { textContent: pipelineState === "running" ? "생성 대기 / 처리 중" : "다음 생성 후 표시" });
                card.append(title, waiting);
            }
            card.onclick = () => { selected = index; render(); refreshMode(); };
            segmentPreviewGrid.append(card);
        });
    };
    segmentPreviewToggle.onclick = () => {
        const next = !(getWidget(node, "segment_preview")?.value !== false);
        setWidget(node, "segment_preview", next);
        setActive(segmentPreviewToggle, next, COLORS.blue);
        segmentPreviewToggle.textContent = `구간 프리뷰 · ${next ? "ON" : "OFF"}`;
        segmentPreviewGrid.style.display = next ? "grid" : "none";
        wakeNode(node);
    };
    const syncSegmentPreviewToggle = () => {
        const enabled = getWidget(node, "segment_preview")?.value !== false;
        setActive(segmentPreviewToggle, enabled, COLORS.blue);
        segmentPreviewToggle.textContent = `구간 프리뷰 · ${enabled ? "ON" : "OFF"}`;
        segmentPreviewGrid.style.display = enabled ? "grid" : "none";
    };
    const graphSection = make("section", { marginBottom: "10px", padding: "8px", background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: "8px", minWidth: "0" }, { className: "h3-camera-generation-graph" });
    const graphHeader = make("div", { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", marginBottom: "7px" });
    const graphState = make("span", { color: COLORS.muted, fontSize: "8px", fontWeight: "900", letterSpacing: ".06em" }, { textContent: "READY" });
    const rpmGauge = make("div", {
        position: "relative", width: "58px", height: "58px", flex: "0 0 58px", borderRadius: "50%",
        background: "conic-gradient(from 225deg, #1c342d 0deg 270deg, transparent 270deg)",
        boxShadow: `inset 0 0 0 1px ${COLORS.borderHot}, 0 0 12px #0008`,
    }, { className: "h3-camera-rpm-gauge", title: "현재 생성 단계의 실제 진행률" });
    const rpmFace = make("div", { position: "absolute", inset: "6px", borderRadius: "50%", background: "#04100c", border: `1px solid ${COLORS.border}` });
    const rpmNeedle = make("div", {
        position: "absolute", left: "7px", top: "28px", width: "22px", height: "2px", borderRadius: "2px",
        background: COLORS.accent, transformOrigin: "100% 50%", transform: "rotate(-135deg)",
        transition: "transform 220ms cubic-bezier(.18,.75,.2,1), background .2s", boxShadow: `0 0 7px ${COLORS.accent}`,
    });
    const rpmHub = make("div", { position: "absolute", left: "25px", top: "25px", width: "8px", height: "8px", borderRadius: "50%", background: "#eafff5", boxShadow: "0 0 5px #fff8" });
    const rpmValue = make("div", { position: "absolute", left: "0", right: "0", bottom: "7px", textAlign: "center", color: COLORS.text, fontSize: "8px", fontWeight: "900" }, { textContent: "0%" });
    const rpmLabel = make("div", { position: "absolute", left: "0", right: "0", top: "6px", textAlign: "center", color: COLORS.muted, fontSize: "6px", fontWeight: "900", letterSpacing: ".08em" }, { textContent: "RENDER" });
    rpmGauge.append(rpmFace, rpmNeedle, rpmHub, rpmValue, rpmLabel);
    const graphMeters = make("div", { display: "flex", alignItems: "center", gap: "8px" });
    graphMeters.append(graphState, rpmGauge);
    graphHeader.append(label("생성 그래프 · LIVE PIPELINE"), graphMeters);
    const graphCanvas = make("div", { display: "grid", gap: "6px", maxHeight: "230px", overflowY: "auto", paddingRight: "2px", scrollbarWidth: "thin" });
    graphSection.append(graphHeader, graphCanvas); root.append(graphSection);
    let pipelineState = "ready";
    let stopGenerationButton = null;
    let pipelineProgress = 0;
    const pipelineColors = { ready: COLORS.muted, queued: "#e8c56a", running: COLORS.blue, done: COLORS.accent, error: "#ff8f82" };
    const pipelineLabels = { ready: "READY", queued: "QUEUED", running: "GENERATING", done: "COMPLETE", error: "ERROR" };
    const setPipelineState = state => {
        pipelineState = state in pipelineLabels ? state : "ready";
        graphState.textContent = pipelineLabels[pipelineState];
        graphState.style.color = pipelineColors[pipelineState];
        if (pipelineState === "queued" || pipelineState === "error") pipelineProgress = 0;
        if (pipelineState === "done") pipelineProgress = 1;
        const ratio = Math.max(0, Math.min(1, Number(pipelineProgress) || 0));
        const gaugeColor = pipelineState === "error" ? "#ff655d" : ratio > .82 ? "#ffb34d" : pipelineState === "done" ? COLORS.accent : COLORS.blue;
        rpmNeedle.style.transform = `rotate(${-135 + ratio * 270}deg)`;
        rpmNeedle.style.background = gaugeColor;
        rpmNeedle.style.boxShadow = `0 0 8px ${gaugeColor}`;
        rpmValue.textContent = `${Math.round(ratio * 100)}%`;
        rpmValue.style.color = gaugeColor;
        rpmGauge.style.background = `conic-gradient(from 225deg, ${gaugeColor} 0deg ${ratio * 270}deg, #1c342d ${ratio * 270}deg 270deg, transparent 270deg)`;
        if (stopGenerationButton) {
            const stoppable = pipelineState === "queued" || pipelineState === "running";
            stopGenerationButton.disabled = !stoppable;
            stopGenerationButton.style.opacity = stoppable ? "1" : ".45";
        }
        renderGenerationGraph?.();
    };
    const graphNode = (title, detail, accent = COLORS.blue, active = false) => {
        const card = make("div", {
            minWidth: "0", padding: "7px 8px", borderRadius: "7px", boxSizing: "border-box",
            background: active ? `${accent}20` : COLORS.field, border: `1px solid ${active ? accent : COLORS.border}`,
            boxShadow: active ? `0 0 0 1px ${accent}35 inset` : "none",
        });
        card.append(
            make("div", { color: active ? "#f4fff9" : COLORS.text, fontSize: "9px", fontWeight: "900", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, { textContent: title }),
            make("div", { color: COLORS.muted, fontSize: "8px", marginTop: "2px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, { textContent: detail }),
        );
        return card;
    };
    const arrow = text => make("div", { color: COLORS.muted, fontSize: "8px", textAlign: "center", lineHeight: "10px" }, { textContent: text || "↓" });
    let renderGenerationGraph = () => {};
    let activePromptId = null;
    const showResult = item => {
        if (!item?.filename) return;
        const type = item.type || "output";
        const subfolder = item.subfolder || "";
        const url = api.apiURL(`/view?filename=${encodeURIComponent(item.filename)}&type=${encodeURIComponent(type)}&subfolder=${encodeURIComponent(subfolder)}&t=${Date.now()}`);
        node.__h3CameraLastOutput = { filename: item.filename, type, subfolder };
        resultPreview.src = url;
        resultPlaceholder.style.display = "none";
        resultPreview.style.display = "block";
        resultPreview.load();
        resultStatus.textContent = item.filename;
        resultPreview.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    };
    const onExecuted = event => {
        const detail = event.detail || {};
        if (activePromptId && detail.prompt_id && detail.prompt_id !== activePromptId) return;
        const output = detail.output || {};
        const segmentItems = output.h3_camera_preview;
        if (Array.isArray(segmentItems) && segmentItems.length) {
            for (const item of segmentItems) {
                const index = Number(item?.segment_index);
                if (Number.isInteger(index) && index >= 0) segmentPreviewItems.set(index, item);
            }
            renderSegmentPreviews();
            return;
        }
        const videos = output.videos || output.gifs;
        if (Array.isArray(videos) && videos.length) showResult(videos[videos.length - 1]);
        else if (Array.isArray(output.images) && output.images.length && Array.isArray(output.animated) && output.animated.length) showResult(output.images[output.images.length - 1]);
    };
    const finishPrompt = event => {
        const promptId = event.detail?.prompt_id;
        if (!activePromptId || !promptId || promptId === activePromptId) {
            setPipelineState(event.type === "execution_error" ? "error" : "done");
            activePromptId = null;
        }
    };
    const interruptedPrompt = event => {
        const promptId = event.detail?.prompt_id;
        if (!activePromptId || !promptId || promptId === activePromptId) {
            pipelineProgress = 0;
            setPipelineState("ready");
            activePromptId = null;
            resultStatus.textContent = "생성 중단됨";
        }
    };
    const startPrompt = event => {
        const promptId = event.detail?.prompt_id;
        if (!activePromptId || !promptId || promptId === activePromptId) setPipelineState("running");
    };
    const progressPrompt = event => {
        const detail = event.detail || {};
        const promptId = detail.prompt_id;
        if (activePromptId && promptId && promptId !== activePromptId) return;
        const value = Number(detail.value);
        const max = Number(detail.max);
        if (Number.isFinite(value) && Number.isFinite(max) && max > 0) pipelineProgress = value / max;
        setPipelineState("running");
    };
    api.addEventListener("executed", onExecuted);
    api.addEventListener("execution_start", startPrompt);
    api.addEventListener("executing", startPrompt);
    api.addEventListener("progress", progressPrompt);
    api.addEventListener("execution_success", finishPrompt);
    api.addEventListener("execution_error", finishPrompt);
    api.addEventListener("execution_interrupted", interruptedPrompt);
    if (node.__h3CameraLastOutput) showResult(node.__h3CameraLastOutput);
    let objectUrl = null; let durationSeconds = 0; let resetOnMetadata = false; let uploadSerial = 0;
    const fmt = value => { const n = Math.max(0, Number(value) || 0); return `${String(Math.floor(n / 60)).padStart(2, "0")}:${(n % 60).toFixed(2).padStart(5, "0")}`; };
    preview.addEventListener("timeupdate", () => { playhead.textContent = `PLAYHEAD ${fmt(preview.currentTime)}`; });
    preview.addEventListener("loadedmetadata", () => {
        if(preview.videoWidth>0&&preview.videoHeight>0){sourceDimensions=[preview.videoWidth,preview.videoHeight];syncResolution();}
        durationSeconds = Number(preview.duration) || 0; duration.textContent = `DURATION ${fmt(durationSeconds)}`;
        if (resetOnMetadata && durationSeconds > 0) {
            resetOnMetadata = false;
            const total = Math.round(durationSeconds * 24);
            const count = Math.max(Math.ceil(total / 360), Math.min(segments.length || 3, Math.floor(total / 5)));
            if (count > 64 || total < 5) {
                fileState.textContent = "5프레임 이상, 최대 16분 영상을 사용하세요.";
                setWidget(node, "source_video", "");
                return;
            }
            segments = Array.from({length:count}, (_,index) => normalizeSegment({
                ...defaults()[index % DEFAULT_SEGMENTS.length],
                start_frame:Math.round(total*index/count), end_frame:Math.round(total*(index+1)/count),
                start_seconds:Math.round(total*index/count)/24, end_seconds:Math.round(total*(index+1)/count)/24,
            }, index));
            selected=0; writePlanner(); renderTabs();
        }
        render();
    });
    upload.onclick = () => { fileInput.value = ""; fileInput.click(); };
    fileInput.onchange = async () => {
        const file = fileInput.files?.[0]; if (!file) return;
        const serial = ++uploadSerial;
        setWidget(node, "source_video", ""); // Failed upload must not generate from the old file.
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        resetOnMetadata = true;
        objectUrl = URL.createObjectURL(file); preview.src = objectUrl; previewWrap.style.display = "block"; preview.load();
        fileLabel.textContent = file.name; fileState.textContent = "UPLOADING";
        const body = new FormData(); body.append("file", file, file.name);
        try {
            const response = await fetch("/h3r2v_camera_lip_lock/upload", { method: "POST", body });
            const result = await response.json(); if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
            if (serial !== uploadSerial) return;
            setWidget(node, "source_video", result.path || result.filename);
            node.setDirtyCanvas?.(true, true); node.graph?.setDirtyCanvas?.(true, true);
            fileState.textContent = "SOURCE READY";
        } catch (error) { if (serial !== uploadSerial) return; fileState.textContent = "UPLOAD FAILED"; console.warn("[H3 R2V Timeline]", error); }
    };

    let segments = readPlan(node).map(normalizeSegment);
    let selected = 0;
    const segmentArea = make("div", { display: "grid", gap: "6px", marginBottom: "10px", minWidth: "0" });
    const segmentTabs = make("div", { display: "flex", gap: "5px", minWidth: "0", overflowX: "auto", overflowY: "hidden", paddingBottom: "3px", scrollbarWidth: "thin" });
    const segmentControls = make("div", { display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "5px" });
    segmentArea.append(segmentTabs, segmentControls); root.append(segmentArea);
    const tabButtons = [];
    const selectedSegment = () => segments[selected] || (segments[selected] = normalizeSegment({}, selected));
    const fps = () => 24; // H3 references are decoded at native 24fps.
    renderGenerationGraph = () => {
        graphCanvas.replaceChildren();
        const sourceReady = !!String(getWidget(node, "source_video")?.value || "").trim();
        graphCanvas.append(graphNode("01 · SOURCE VIDEO", sourceReady ? "원본 영상 + 원본 오디오 준비" : "소스 영상을 먼저 업로드하세요", sourceReady ? COLORS.accent : COLORS.muted, sourceReady));
        graphCanvas.append(arrow("↓  구간별 독립 생성 분기"));
        const branchGrid = make("div", { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "5px" });
        segments.forEach((segment, index) => {
            const start = Number(segment.start_seconds ?? Number(segment.start_frame || 0) / fps());
            const end = Number(segment.end_seconds ?? Number(segment.end_frame || 0) / fps());
            const card = graphNode(
                `${String(index + 1).padStart(2, "0")} · ${segment.shot || "SHOT"}`,
                `${fmt(start)}–${fmt(end)} · ${segment.movement || "static"}`,
                index === selected ? COLORS.blue : COLORS.accent,
                index === selected || pipelineState === "running",
            );
            card.title = `구간 ${index + 1} 편집으로 이동`;
            card.style.cursor = "pointer";
            card.onclick = () => { selected = index; render(); refreshMode(); };
            branchGrid.append(card);
        });
        graphCanvas.append(branchGrid, arrow("↓  프레임 순서 결합 + 오디오 타임라인 유지"));
        const finalGrid = make("div", { display: "grid", gridTemplateColumns: "1fr auto 1fr auto 1fr", gap: "4px", alignItems: "center" });
        finalGrid.append(
            graphNode("FRAME JOIN", `${segments.length}개 구간`, COLORS.blue, pipelineState === "running"),
            arrow("→"),
            graphNode("LIP + AUDIO LOCK", getWidget(node,"lip_sync_strict")?.value?"정확 음성 조건 + 원본 재결합":"원본 음성 재결합", "#e8c56a", pipelineState === "running"),
            arrow("→"),
            graphNode("FINAL VIDEO", pipelineState === "done" ? "출력 완료" : "영상 + 오디오", COLORS.accent, pipelineState === "done"),
        );
        graphCanvas.append(finalGrid);
        renderSegmentPreviews();
    };
    const writePlanner = () => {
        segmentPreviewItems.clear();
        const payload = JSON.stringify({ segments }, null, 2);
        const widget = getWidget(node, "camera_plan_json"); if (widget) widget.value = payload;
        setWidget(node, "expected_segments", 0);
        node.setDirtyCanvas?.(true, true); node.graph?.setDirtyCanvas?.(true, true);
    };
    const apply = () => { writePlanner(); render(); };
    const renderTabs = () => {
        segmentTabs.replaceChildren(); segmentControls.replaceChildren(); tabButtons.length = 0;
        segments.forEach((_, index) => {
            const b = makeButton(`SEGMENT ${index + 1}`, index === selected, COLORS.blue); b.style.minWidth = "92px";
            b.style.flex = "0 0 auto";
            b.onclick = () => { selected = index; render(); refreshMode(); }; tabButtons.push(b); segmentTabs.append(b);
        });
        const add = makeButton("+ 구간 추가", false, COLORS.accent);
        add.title = "선택한 구간을 둘로 나눕니다. 전체 영상 길이는 유지됩니다.";
        add.disabled = segments.length >= 64;
        add.onclick = () => {
            try { segments = splitSegment(segments, selected); selected += 1; apply(); renderTabs(); refreshMode(); }
            catch (error) { status.textContent = error.message; }
        };
        const remove = makeButton("선택 구간 삭제", false, "#e88d7e");
        remove.title = "선택 구간의 영상과 오디오를 함께 제외합니다. 다른 구간의 시간은 유지됩니다.";
        remove.disabled = segments.length <= 1;
        remove.onclick = () => {
            segments = removeSegment(segments, selected);
            selected = Math.min(selected, segments.length - 1); apply(); renderTabs(); refreshMode();
        };
        const reset = makeButton("균등 분할", false, "#e88d7e");
        reset.title = "현재 구간 수와 카메라 선택을 유지하고 원본 전체 길이에 균등 배치합니다.";
        reset.onclick = () => {
            if (!durationSeconds) { status.textContent = "먼저 소스 영상이 로드되어야 합니다."; return; }
            const total = Math.round(durationSeconds * 24), count = segments.length;
            if (total < count * 5 || Math.ceil(total / count) > 360) { status.textContent = "구간 수를 조절하세요. 구간별 5프레임~15초가 필요합니다."; return; }
            segments = segments.map((s, i) => { const a = Math.round(total * i / count), b = Math.round(total * (i + 1) / count); return { ...s, start_frame: a, end_frame: b, start_seconds: a / 24, end_seconds: b / 24 }; });
            apply(); renderTabs();
        };
        add.style.width = "100%"; remove.style.width = "100%"; reset.style.width = "100%";
        segmentControls.append(add, remove, reset);
    };
    const section = (titleText, choices, key, accent) => {
        const wrap = make("div", { marginBottom: "9px" }); wrap.append(label(titleText));
        const row = make("div", { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(92px, 1fr))", gap: "4px", marginTop: "4px" });
        choices.forEach(([value, text]) => { const b = makeButton(text, false, accent); b.style.minWidth = "0"; b.onclick = () => { selectedSegment()[key] = value; apply(); }; row.append(b); });
        wrap.append(row); root.append(wrap); return row;
    };
    const shotRow = section("SHOT / FRAMING", SHOTS, "shot", COLORS.blue);
    const moveRow = section("CAMERA MOVEMENT", MOVES, "movement", COLORS.accent);
    const speedRow = section("MOVEMENT SPEED", SPEEDS, "speed", "#e8c56a");
    const timeRow = make("div", { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "6px", marginBottom: "8px" });
    const timeInput = (titleText, key) => { const wrap = make("div", { padding: "7px", background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: "6px" }); wrap.append(label(titleText)); const input = make("input", { width: "100%", marginTop: "4px", boxSizing: "border-box", background: COLORS.field, border: `1px solid ${COLORS.border}`, borderRadius: "5px", color: COLORS.text, padding: "5px", outline: "none", fontSize: "11px", fontWeight: "800" }, { type: "number", min: "0", step: "0.01" }); input.onchange = () => { const value = Math.max(0, Number(input.value) || 0); const item = selectedSegment(); item[key] = value; item.start_frame = Math.round(Number(item.start_seconds || 0) * fps()); item.end_frame = Math.max(item.start_frame + 5, Math.round(Number(item.end_seconds || 0) * fps())); apply(); }; wrap.append(input); timeRow.append(wrap); return input; };
    const startSeconds = timeInput("START SECOND", "start_seconds");
    const endSeconds = timeInput("END SECOND", "end_seconds"); root.append(timeRow);
    const markRow = make("div", { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "5px", marginBottom: "9px" });
    const markStart = makeButton("SET START AT PLAYHEAD", false, COLORS.blue); const markEnd = makeButton("SET END AT PLAYHEAD", false, COLORS.blue); markStart.style.width = "100%"; markEnd.style.width = "100%";
    markStart.onclick = () => { if (!durationSeconds) return; const item = selectedSegment(); item.start_seconds = preview.currentTime; item.start_frame = Math.round(item.start_seconds * fps()); if (Number(item.end_seconds || 0) <= item.start_seconds) { item.end_seconds = Math.min(durationSeconds, item.start_seconds + 5); item.end_frame = Math.round(item.end_seconds * fps()); } apply(); };
    markEnd.onclick = () => { if (!durationSeconds) return; const item = selectedSegment(); item.end_seconds = Math.max(item.start_seconds || 0, preview.currentTime); item.end_frame = Math.max(item.start_frame + 5, Math.round(item.end_seconds * fps())); apply(); };
    markRow.append(markStart, markEnd); root.append(markRow);
    const sliderRow = make("div", { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "7px", marginBottom: "9px" });
    const slider = (titleText, key, min, max, step, accent) => { const wrap = make("div", { padding: "7px", background: COLORS.card, border: `1px solid ${COLORS.border}`, borderRadius: "6px" }); const top = make("div", { display: "flex", justifyContent: "space-between" }); const value = make("span", { color: accent, fontSize: "10px", fontWeight: "900" }); top.append(label(titleText), value); const input = make("input", { width: "100%", marginTop: "4px", accentColor: accent }, { type: "range", min, max, step }); input.oninput = () => { const next = Number(input.value); if (key === "edit_strength") setWidget(node, key, next); else selectedSegment()[key] = next; value.textContent = next.toFixed(2); writePlanner(); }; wrap.append(top, input); sliderRow.append(wrap); return { input, value }; };
    const motion = slider("MOTION STRENGTH", "strength", "0", "1", "0.05", COLORS.accent);
    const lip = slider("카메라 재생성 강도 · 권장 0.95", "edit_strength", "0.70", "1.00", "0.05", COLORS.blue); root.append(sliderRow);
    const centers = make("div", {display:"none",gap:"8px",marginBottom:"10px"});
    const centerInputs = {};
    for (const [key,title] of [["center_x","크롭 위치 · 좌 ↔ 우"],["center_y","크롭 위치 · 상 ↔ 하"]]) {
        const box=make("label",{flex:"1",fontSize:"11px"},{textContent:title});
        const input=make("input",{width:"100%"},{type:"range",min:"0",max:"1",step:"0.01",title});
        input.oninput=()=>{selectedSegment()[key]=Number(input.value);apply();};
        centerInputs[key]=input;box.append(input);centers.append(box);
    }
    root.append(centers);
    const usageHint = make("div", {color:COLORS.muted,fontSize:"9px",marginBottom:"8px"}, {textContent:"원본 기반 편집 · 시작값 0.35. 카메라 변화/입모양 일치를 보장하지 않습니다. 각 구간 최대 15초, 원본 오디오 유지."});
    root.append(usageHint);
    const generateStatus = make("div", { color: COLORS.muted, fontSize: "9px", minHeight: "15px", margin: "7px 0 5px", textAlign: "center" });
    const generate = makeButton("영상 생성", false, COLORS.accent);
    Object.assign(generate.style, { width: "100%", height: "40px", padding: "10px", fontSize: "13px", fontWeight: "900", letterSpacing: ".04em" });
    generate.onclick = async () => {
        if (generate.disabled) return;
        document.activeElement?.blur?.();
        writePlanner();
        if (!String(getWidget(node, "source_video")?.value || "").trim()) {
            generateStatus.textContent = "먼저 소스 영상을 업로드하세요.";
            return;
        }
        generate.disabled = true;
        generate.textContent = "생성 요청 중…";
        try {
            if (typeof app.queuePrompt !== "function") throw new Error("ComfyUI 생성 기능을 찾을 수 없습니다.");
            const queued = await app.queuePrompt(0, 1);
            activePromptId = queued?.prompt_id || queued?.promptId || activePromptId;
            pipelineProgress = 0;
            setPipelineState("queued");
            generateStatus.textContent = "생성 요청 완료 · 진행 상태는 ComfyUI 큐에서 확인하세요.";
        } catch (error) {
            setPipelineState("error");
            generateStatus.textContent = `생성 요청 실패 · ${error?.message || error}`;
        } finally {
            generate.disabled = false;
            generate.textContent = "영상 생성";
        }
    };
    stopGenerationButton = makeButton("생성 중단", false, "#ff655d");
    Object.assign(stopGenerationButton.style, { width: "100%", height: "40px", padding: "10px", fontSize: "12px", fontWeight: "900", letterSpacing: ".04em", opacity: ".45" });
    stopGenerationButton.disabled = true;
    stopGenerationButton.onclick = async () => {
        if (stopGenerationButton.disabled) return;
        stopGenerationButton.disabled = true;
        stopGenerationButton.textContent = "중단 요청 중…";
        try {
            if (typeof api.clearItems === "function") await api.clearItems("queue");
            if (typeof api.interrupt === "function") await api.interrupt(activePromptId || undefined);
            else await api.fetchApi("/interrupt", { method: "POST" });
            generateStatus.textContent = "현재 생성 중단 요청 완료 · 남은 예약 큐도 정리했습니다.";
        } catch (error) {
            generateStatus.textContent = `생성 중단 실패 · ${error?.message || error}`;
        } finally {
            stopGenerationButton.textContent = "생성 중단";
        }
    };
    const generationActions = make("div", { display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(110px, .8fr)", gap: "6px", marginBottom: "2px" });
    generationActions.append(generate, stopGenerationButton);
    root.append(generateStatus, generationActions);
    const footer = make("div", { display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap", marginTop: "7px" }); const status = make("div", { flex: "1 1 260px", minWidth: "0", color: COLORS.muted, fontSize: "10px", textAlign: "right", lineHeight: "1.35", overflowWrap: "anywhere" });
    footer.append(status); root.append(footer);
    const contentGrid = make("div", { display: "grid", gridTemplateColumns: "minmax(280px, .86fr) minmax(420px, 1.38fr) minmax(300px, 1fr)", gap: "10px", flex: "1", minHeight: "0", overflow: "hidden" });
    const makeColumn = () => make("section", { minWidth: "0", minHeight: "0", overflowX: "hidden", overflowY: "auto", paddingRight: "3px", scrollbarWidth: "thin", scrollbarColor: `${COLORS.borderHot} transparent` });
    const sourceColumn = makeColumn();
    const cameraColumn = makeColumn();
    const outputColumn = makeColumn();
    sourceColumn.append(modelPanel, modeNotice, workflowHint, optimizerPanel, resolutionPanel, sourceRow, previewWrap);
    cameraColumn.append(segmentArea, shotRow.parentElement, moveRow.parentElement, speedRow.parentElement, timeRow, markRow, sliderRow, centers, usageHint);
    outputColumn.append(upscalePanel, resultSection, graphSection, segmentPreviewSection, generateStatus, generationActions, footer);
    contentGrid.append(sourceColumn, cameraColumn, outputColumn);
    root.append(contentGrid);
    function active(row, choices, value, accent) { [...row.children].forEach((button, index) => setActive(button, choices[index][0] === value, accent)); }
    function render() { segments = segments.map((segment, index) => normalizeSegment(segment, index)); const item = selectedSegment(); tabButtons.forEach((b, index) => setActive(b, index === selected, COLORS.blue)); active(shotRow, SHOTS, item.shot, COLORS.blue); active(moveRow, MOVES, item.movement, COLORS.accent); active(speedRow, SPEEDS, item.speed, "#e8c56a"); startSeconds.value = Number(item.start_seconds ?? item.start_frame / fps()).toFixed(2); endSeconds.value = Number(item.end_seconds ?? item.end_frame / fps()).toFixed(2); motion.input.value = Number(item.strength); motion.value.textContent = Number(item.strength).toFixed(2); const lock = Number(getWidget(node, "edit_strength")?.value ?? 0.95); lip.input.value = lock; lip.value.textContent = lock.toFixed(2); status.textContent = `EDITING SEGMENT ${selected + 1}  ·  ${fmt(item.start_seconds ?? item.start_frame/24)} → ${fmt(item.end_seconds ?? item.end_frame/24)}  ·  ${item.shot} / ${item.movement}`; syncSegmentPreviewToggle(); renderGenerationGraph(); }
    function reload() {
        refreshMode();
        syncOptimizers();
        syncResolution();
        syncUpscale();
        segments=readPlan(node).map(normalizeSegment); selected=Math.min(selected,segments.length-1);
        const edit=getWidget(node,"edit_strength");
        if(edit) edit.value=Number.isFinite(Number(edit.value))?Math.max(.70,Math.min(1.0,Number(edit.value))):.95;
        const source=String(getWidget(node,"source_video")?.value||"");
        if(source&&!objectUrl){
            const name=source.split(/[\\/]/).at(-1);fileLabel.textContent=name;
            preview.src=`/view?filename=${encodeURIComponent(name)}&type=input`;
            previewWrap.style.display="block";fileState.textContent="SOURCE SAVED";
        }
        renderTabs();render();
    }
    function refreshMode() {
        const direct = directMode();
        const hybrid = hybridMode();
        const enforced = direct || hybrid;
        optimizerPanel.style.display = direct ? "none" : "block";
        lip.input.disabled = direct;
        if(lip.input.parentElement) lip.input.parentElement.style.display=direct?"none":"block";
        modeNotice.textContent = direct
            ? "실제 2D 재구도 · 원본 프레임 줌/팬/상하 이동. AI 재생성 없음. 새 시점/오빗은 미지원."
            : hybrid
                ? "AI 생성 + 강제 카메라 · H3 생성 뒤 줌/팬/틸트/트래킹을 실제 픽셀 경로로 적용합니다. 오빗·상하 시점·후면 시점은 2D로 만들 수 없어 숨깁니다."
                : "실험적 AI 재생성 모드 · 카메라 지시는 프롬프트 요청이며 실제 이동/입모양 일치는 보장하지 않습니다.";
        centers.style.display = enforced ? "flex" : "none";
        for(const [row,choices,allowed] of [[shotRow,SHOTS,directShots],[moveRow,MOVES,directMoves]]) {
            [...row.children].forEach((b,i)=>{
                b.disabled=enforced&&!allowed.includes(choices[i][0]);
                b.style.display=b.disabled?"none":"";
                b.title=b.disabled?"새 시점 생성/인물 추적 미지원 — 다른 동작을 선택하세요":"";
                b.style.opacity=b.disabled?".3":"1";
                if(enforced&&choices[i][0]==="slow dolly in")b.textContent="ZOOM IN";
                if(enforced&&choices[i][0]==="slow dolly out")b.textContent="ZOOM OUT";
            });
        }
        for(const [key,input] of Object.entries(centerInputs))input.value=Number(selectedSegment()[key]??.5);
    }
    renderTabs(); render(); refreshMode(); return { root, reload, dispose() { ++uploadSerial; api.removeEventListener("executed", onExecuted); api.removeEventListener("execution_start", startPrompt); api.removeEventListener("executing", startPrompt); api.removeEventListener("progress", progressPrompt); api.removeEventListener("execution_success", finishPrompt); api.removeEventListener("execution_error", finishPrompt); api.removeEventListener("execution_interrupted", interruptedPrompt); preview.pause(); preview.removeAttribute?.("src"); preview.load(); resultPreview.pause(); resultPreview.removeAttribute?.("src"); resultPreview.load(); if (objectUrl) URL.revokeObjectURL(objectUrl); } };
}

app.registerExtension({
    name: EXTENSION_NAME,
    setup() {
        if (app.__h3CameraDynamicGraph) return;
        const original = app.graphToPrompt;
        if (typeof original !== "function") throw new Error("카메라 구간 자동 연결: ComfyUI graphToPrompt를 찾을 수 없습니다.");
        app.graphToPrompt = async function (...args) {
            const result = await original.apply(this, args);
            if (!Object.values(result.output || {}).some(n => n.class_type === "H3R2VCameraTimeline")) return result;
            const runtime = await materializeCameraWorkflow(result.output);
            return { ...result, output: expandCameraTimelines(runtime) };
        };
        app.__h3CameraDynamicGraph = true;
    },
    async afterConfigureGraph() {
        // Repair only the broken scheduler combo in our camera graph. Preserve
        // the user's LoRA, steps, denoise, ranges and any valid scheduler choice.
        const graph=app.graph;
        if(!graph?._nodes?.some(n=>n.type==="H3R2VCameraTimeline")) { cameraStudio.close(); return; }
        const loader=graph.getNodeById?.(3);
        const base=String(getWidget(loader||{},"unet_name")?.value||"").split(/[\\/]/).at(-1);
        if(base==="minimax_h3_fl2va_pruned_int8_convrot.safetensors"){
            for(const timeline of graph._nodes.filter(n=>n.type==="H3R2VCameraTimeline")){
                const lw=getWidget(timeline,"lora_name");
                const old=String(lw?.value||"").split(/[\\/]/).at(-1);
                if(!["MiniMax-H3-Ref2VA-Acc-8Step_pruned_comfy.safetensors","MiniMax-H3-FL2VA-Acc-8Step_pruned_comfy.safetensors"].includes(old)) continue;
                const choices=lw?.options?.values;
                const match=Array.isArray(choices)?choices.find(v=>String(v).split(/[\\/]/).at(-1)==="minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"):null;
                if(match){setWidget(timeline,"lora_name",match);timeline.__h3CameraTimelineUI?.reload?.();wakeNode(timeline);}
            }
        }
        for(const n of graph._nodes){
            if(n.type!=="BasicScheduler") continue;
            const stepsInput=n.inputs?.find(i=>i.name==="steps");
            const link=graph.links?.[stepsInput?.link];
            const origin=link && graph.getNodeById?.(link.origin_id);
            if(origin?.type!=="H3R2VCameraTimeline") continue;
            const scheduler=getWidget(n,"scheduler");
            if(scheduler && (typeof scheduler.value!=="string" || !scheduler.value || /^\d+(\.\d+)?$/.test(scheduler.value))){
                setWidget(n,"scheduler","simple");
                wakeNode(n);
                console.info(`[H3 Camera] Repaired malformed scheduler widget on node ${n.id}; kept user settings.`);
            }
        }
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (![NODE_NAME, "H3R2VCameraTimeline"].includes(nodeData.name)) return;
        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            if (this.__h3CameraLipLockUI || this.__h3CameraTimelineUI) return result;

            if (nodeData.name === "H3R2VCameraTimeline") {
                ["source_video", "camera_plan_json", "source_fps", "edit_strength", "expected_segments", "lora_name", "lora_strength", "sage_enabled", "spectrum_enabled", "steps", "aspect_ratio", "megapixels", "custom_width", "custom_height", "lip_sync_strict", "segment_preview", "unet_name", "upscale_enabled", "upscale_scale", "upscale_quality", "upscale_restore_mode", "upscale_quality_target", "upscale_color_treatment", "upscale_output_quality", "upscale_encode_preset", "upscale_temporal_mode", "upscale_subject_recovery", "upscale_output_mode"].forEach(name => {
                    const widget = getWidget(this, name);
                    if (widget) { widget.computeSize = () => [0, -4]; widget.draw = () => {}; widget.hidden = true; }
                });
                const panel = createTimelinePlanner(this);
                this.__h3CameraTimelineUI = panel;
                this.addDOMWidget("camera_timeline_ui", "div", panel.root, { serialize: false, hideOnZoom: false, getValue: () => "R2V Timeline Director", setValue: () => {}, computeSize: () => [1180, 700] });
                this.setSize([1200, 760]);
                this.setDirtyCanvas?.(true, true);
                return result;
            }

            // Keep raw values in the graph for compatibility, but let the button
            // panel be the primary control surface, like the H3 All-in-One node.
            ["camera_plan_json", "camera_shot", "camera_movement", "camera_speed", "camera_strength"].forEach(name => {
                const widget = getWidget(this, name);
                if (!widget) return;
                widget.computeSize = () => [0, -4];
                widget.draw = () => {};
                widget.hidden = true;
            });

            const panel = createController(this);
            this.__h3CameraLipLockUI = panel;
            this.addDOMWidget("camera_lip_lock_ui", "div", panel.root, {
                serialize: false,
                hideOnZoom: false,
                getValue: () => "Camera + Lip Lock UI",
                setValue: () => {},
                computeSize: () => [560, 480],
            });
            this.setSize([580, 560]);
            this.setDirtyCanvas?.(true, true);
            return result;
        };
        const originalConfigure=nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure=function(){
            const result=originalConfigure?.apply(this,arguments);
            if(nodeData.name==="H3R2VCameraTimeline") {
                migrateResolutionWidgets(this,arguments[0]);
                requestAnimationFrame(() => { this.setSize([1200, 760]); this.setDirtyCanvas?.(true, true); });
            }
            this.__h3CameraTimelineUI?.reload?.();
            return result;
        };
        const originalRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            cameraStudio.remove(this);
            this.__h3CameraTimelineUI?.dispose?.();
            this.__h3CameraLipLockUI?.dispose?.();
            return originalRemoved?.apply(this, arguments);
        };
    },
});

app.registerExtension({
    name: "ComfyUI.H3R2VCameraLipLock.Studio",
    afterConfigureGraph() { cameraStudio.sync(); },
});
