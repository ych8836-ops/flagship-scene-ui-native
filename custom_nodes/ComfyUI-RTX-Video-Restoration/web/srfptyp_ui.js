import { app } from "../../scripts/app.js";

const NODE_NAME = "RTXVideoVSRRestore";
const WIDTH = 560;
const HEIGHT = 1260;

const C = {
  bg: "#070b0a",
  panel: "#0d1412",
  panel2: "#111d19",
  line: "#233a32",
  text: "#f4fff9",
  muted: "#8ea69c",
  green: "#76e600",
  mint: "#39e6ad",
  cyan: "#4ad7ff",
  amber: "#ffc766",
};

function el(tag, style = {}, text = "") {
  const node = document.createElement(tag);
  Object.assign(node.style, style);
  if (text) node.textContent = text;
  return node;
}

function stopEvent(event) {
  event.preventDefault();
  event.stopPropagation();
}

function hideNativeWidget(widget) {
  if (!widget) return;
  if (!widget.__srfptypHidden) {
    widget.__srfptypHidden = true;
    widget.__srfptypOriginalType = widget.type;
  }
  widget.hidden = true;
  widget.type = "converted-widget";
  widget.computeSize = () => [0, -4];
  if (widget.element) widget.element.style.display = "none";
}

function widgetMap(node) {
  const result = {};
  for (const widget of node.widgets || []) {
    if (widget?.name) result[widget.name] = widget;
  }
  return result;
}

function migrateLegacyWidgetValues(node, config = null) {
  const controls = widgetMap(node);
  const presets = ["medium", "slow", "slower"];
  const colors = ["Off", "Auto Natural", "Auto Bright"];
  const engines = ["Ultra", "High", "High-Bitrate Ultra", "High-Bitrate High"];
  const restores = [
    "Auto Scan (Clean/Chain90)", "Deblur Low", "Deblur Medium",
    "Denoise Low", "Denoise Low + Deblur Low", "Chain Late Recovery 90",
  ];
  const masters = ["100% Restore", "105% Master", "110% Master"];
  const temporalModes = ["Auto Temporal", "Face Lock", "Action Stable", "Off"];
  const subjectModes = ["Auto", "Full Shot Strong", "Off"];
  const motionRepairModes = ["Auto", "Action Strong", "NVIDIA 가변 프레임 보간", "Off"];
  const quality = controls.output_quality;
  const preset = controls.encode_preset;
  const color = controls.color_treatment;
  if (!quality || !preset || !color) return false;

  // The first public build placed enabled before scale. Keep those workflows
  // compatible after enabled moved to the end of the schema.
  const raw = Array.isArray(config?.widgets_values) ? config.widgets_values : null;
  // New controls are appended, never inserted into legacy positional values.
  if (controls.hdr_enabled && raw) {
    controls.hdr_enabled.value = typeof raw[10] === "boolean" ? raw[10] : false;
  }
  if (controls.output_mode && raw) {
    controls.output_mode.value = ["SDR", "SDR 10bit", "HDR"].includes(raw[11])
      ? raw[11] : (controls.hdr_enabled?.value === true ? "HDR" : "SDR");
  }
  const enabledFirst = raw
    && typeof raw[0] === "boolean"
    && Number.isFinite(Number(raw[1]))
    && engines.includes(String(raw[2]));
  if (enabledFirst) {
    if (controls.enabled) controls.enabled.value = raw[0];
    if (controls.scale) controls.scale.value = Math.max(1, Math.min(4, Number(raw[1]) || 2));
    if (controls.upscale_quality) controls.upscale_quality.value = String(raw[2]);
    if (controls.restore_mode) controls.restore_mode.value = restores.includes(String(raw[3])) ? String(raw[3]) : "Auto Scan (Clean/Chain90)";
    if (controls.quality_target) controls.quality_target.value = masters.includes(String(raw[4])) ? String(raw[4]) : "110% Master";
    color.value = colors.includes(String(raw[5])) ? String(raw[5]) : "Auto Natural";
    const enabledFirstQuality = Number(raw[6]);
    quality.value = Number.isFinite(enabledFirstQuality) && enabledFirstQuality >= 80 && enabledFirstQuality <= 99 ? Math.round(enabledFirstQuality) : 95;
    preset.value = presets.includes(String(raw[7])) ? String(raw[7]) : "slow";
    if (controls.temporal_mode) controls.temporal_mode.value = temporalModes.includes(String(raw[8])) ? String(raw[8]) : "Auto Temporal";
    if (controls.subject_recovery) controls.subject_recovery.value = subjectModes.includes(String(raw[9])) ? String(raw[9]) : "Auto";
    console.info("[SRFPTyp UI] migrated enabled-first workflow schema");
    return true;
  }

  // Workflows saved before the enabled widget was added start with the numeric
  // scale followed by the VSR engine. Loading them against the new schema shifts
  // every value one position to the right and can leave "Ultra" in the scale
  // widget, which makes the node appear to run without actually upscaling.
  const scaleFirst = raw
    && typeof raw[0] === "number"
    && engines.includes(String(raw[1]));
  if (scaleFirst) {
    const hasColor = colors.includes(String(raw[4]));
    const legacyColor = hasColor ? String(raw[4]) : "Auto Natural";
    const legacyQuality = Number(raw[hasColor ? 5 : 4]);
    const legacyPreset = String(raw[hasColor ? 6 : 5] ?? "slow");
    const legacyTemporal = String(raw[hasColor ? 7 : 6] ?? "Auto Temporal");
    const legacySubject = String(raw[hasColor ? 8 : 7] ?? "Auto");

    if (controls.enabled) controls.enabled.value = typeof raw[9] === "boolean" ? raw[9] : true;
    if (controls.scale) controls.scale.value = Math.max(1, Math.min(4, Number(raw[0]) || 2));
    if (controls.upscale_quality) controls.upscale_quality.value = engines.includes(String(raw[1])) ? String(raw[1]) : "Ultra";
    if (controls.restore_mode) controls.restore_mode.value = restores.includes(String(raw[2])) ? String(raw[2]) : "Auto Scan (Clean/Chain90)";
    if (controls.quality_target) controls.quality_target.value = masters.includes(String(raw[3])) ? String(raw[3]) : "110% Master";
    color.value = legacyColor;
    quality.value = Number.isFinite(legacyQuality) && legacyQuality >= 80 && legacyQuality <= 99 ? Math.round(legacyQuality) : 95;
    preset.value = presets.includes(legacyPreset) ? legacyPreset : "slow";
    if (controls.temporal_mode) controls.temporal_mode.value = temporalModes.includes(legacyTemporal) ? legacyTemporal : "Auto Temporal";
    if (controls.subject_recovery) controls.subject_recovery.value = subjectModes.includes(legacySubject) ? legacySubject : "Auto";
    console.info("[SRFPTyp UI] normalized scale-first workflow schema");
    return true;
  }

  // Workflows saved before AUTO COLOR have six values. ComfyUI restores those
  // positionally, so 95 lands in color, "slow" lands in quality, and preset is
  // left empty. Repair that exact legacy shape before prompt serialization.
  if (presets.includes(String(quality.value)) && !presets.includes(String(preset.value))) {
    const legacyQuality = Number(color.value);
    preset.value = String(quality.value);
    quality.value = Number.isFinite(legacyQuality) && legacyQuality >= 80 && legacyQuality <= 99
      ? Math.round(legacyQuality)
      : 95;
    color.value = "Auto Natural";
    console.info("[SRFPTyp UI] migrated legacy workflow values to AUTO COLOR schema");
    return true;
  }

  // Also sanitize partially restored values from interrupted/older UI builds.
  if (!colors.includes(String(color.value))) color.value = "Auto Natural";
  const numericQuality = Number(quality.value);
  quality.value = Number.isFinite(numericQuality) && numericQuality >= 80 && numericQuality <= 99
    ? Math.round(numericQuality)
    : 95;
  if (!presets.includes(String(preset.value))) preset.value = "slow";
  if (controls.temporal_mode && !temporalModes.includes(String(controls.temporal_mode.value))) {
    controls.temporal_mode.value = "Auto Temporal";
  }
  if (controls.subject_recovery && !subjectModes.includes(String(controls.subject_recovery.value))) {
    controls.subject_recovery.value = "Auto";
  }
  if (controls.motion_repair && !motionRepairModes.includes(String(controls.motion_repair.value))) {
    controls.motion_repair.value = "Auto";
  }
  if (controls.motion_repair_strength) {
    const strength = Number(controls.motion_repair_strength.value);
    controls.motion_repair_strength.value = Number.isFinite(strength)
      ? Math.max(10, Math.min(50, Math.round(strength / 5) * 5))
      : 30;
  }
  return false;
}

function installPanel(node) {
  if (node.__srfptypPanelInstalled) return;
  node.__srfptypPanelInstalled = true;

  const controls = widgetMap(node);
  const fieldNames = [
    "scale",
    "upscale_quality",
    "restore_mode",
    "quality_target",
    "color_treatment",
    "output_quality",
    "encode_preset",
    "temporal_mode",
    "subject_recovery",
    "hdr_enabled",
    "output_mode",
    "motion_repair",
    "motion_repair_strength",
  ];
  const hideControls = () => fieldNames.forEach((name) => hideNativeWidget(controls[name]));
  hideControls();
  node.__srfptypHideNative = hideControls;

  node.color = "#13231d";
  node.bgcolor = C.bg;
  node.resizable = false;

  const root = el("div", {
    width: "100%",
    height: `${HEIGHT}px`,
    boxSizing: "border-box",
    padding: "14px",
    color: C.text,
    background:
      "radial-gradient(circle at 88% 0%, rgba(57,230,173,.13), transparent 34%), linear-gradient(155deg,#070b0a 0%,#0a100e 58%,#07100d 100%)",
    border: `1px solid ${C.line}`,
    borderRadius: "14px",
    fontFamily: "Inter, Segoe UI, sans-serif",
    userSelect: "none",
    overflow: "hidden",
    pointerEvents: "auto",
  });

  const header = el("div", {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "10px",
  });
  const brand = el("div", { display: "flex", alignItems: "center", gap: "9px" });
  const logo = el("div", {
    padding: "5px 9px",
    borderRadius: "8px",
    background: `linear-gradient(135deg,${C.green},${C.mint})`,
    color: "#071008",
    fontWeight: "950",
    fontSize: "12px",
    letterSpacing: ".08em",
    boxShadow: "0 0 18px rgba(118,230,0,.18)",
  }, "SRF");
  const titles = el("div");
  titles.append(
    el("div", { fontWeight: "850", fontSize: "15px", letterSpacing: ".02em" }, "SRFPTyp 업스케일러"),
    el("div", { color: C.muted, fontSize: "9px", marginTop: "2px", letterSpacing: ".10em" }, "PRIVATE VIDEO RESTORATION PIPELINE")
  );
  brand.append(logo, titles);
  const ready = el("div", {
    padding: "5px 8px",
    borderRadius: "999px",
    border: "1px solid rgba(57,230,173,.35)",
    background: "rgba(57,230,173,.08)",
    color: C.mint,
    fontSize: "9px",
    fontWeight: "800",
  }, "● READY");
  header.append(brand, ready);
  root.append(header);

  const summary = el("div", {
    minHeight: "40px",
    padding: "9px 11px",
    marginBottom: "10px",
    borderRadius: "10px",
    border: `1px solid ${C.line}`,
    background: "linear-gradient(90deg,rgba(57,230,173,.08),rgba(74,215,255,.04))",
    boxSizing: "border-box",
  });
  const summaryTitle = el("div", { color: C.muted, fontSize: "8px", fontWeight: "800", letterSpacing: ".14em" }, "ACTIVE PIPELINE");
  const summaryValue = el("div", { marginTop: "4px", fontSize: "11px", fontWeight: "750", color: C.text });
  summary.append(summaryTitle, summaryValue);
  root.append(summary);

  const groups = [];
  const refreshers = [];

  function section(title, subtitle = "") {
    const box = el("div", {
      padding: "10px",
      marginBottom: "8px",
      borderRadius: "11px",
      border: `1px solid ${C.line}`,
      background: "linear-gradient(145deg,rgba(17,29,25,.96),rgba(11,18,16,.96))",
    });
    const head = el("div", { display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "7px" });
    head.append(
      el("div", { fontSize: "9px", fontWeight: "850", letterSpacing: ".12em", color: C.text }, title),
      el("div", { fontSize: "8px", color: C.muted }, subtitle)
    );
    box.append(head);
    root.append(box);
    return box;
  }

  function setValue(name, value) {
    const widget = controls[name];
    if (!widget) return;
    widget.value = value;
    try { widget.callback?.(value, app.canvas, node, [0, 0], null); } catch (_) {}
    refresh();
    node.setDirtyCanvas?.(true, true);
    node.graph?.change?.();
  }

  function buttonGroup(container, name, options, columns = options.length) {
    const grid = el("div", {
      display: "grid",
      gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
      gap: "6px",
    });
    const entries = [];
    for (const option of options) {
      const value = typeof option === "string" ? option : option.value;
      const label = typeof option === "string" ? option : option.label;
      const hint = typeof option === "string" ? "" : option.hint || "";
      const button = el("button", {
        minHeight: hint ? "42px" : "30px",
        padding: hint ? "6px 5px" : "5px 4px",
        borderRadius: "8px",
        border: `1px solid ${C.line}`,
        background: "#0a100e",
        color: C.muted,
        cursor: "pointer",
        fontSize: "9px",
        fontWeight: "800",
        outline: "none",
        transition: "all .14s ease",
      });
      button.type = "button";
      button.append(el("div", { fontSize: "9px", fontWeight: "850" }, label));
      if (hint) button.append(el("div", { marginTop: "3px", color: "#6f897e", fontSize: "7px", fontWeight: "650" }, hint));
      button.onpointerdown = stopEvent;
      button.onclick = (event) => { stopEvent(event); setValue(name, value); };
      entries.push({ button, value });
      grid.append(button);
    }
    const update = () => {
      const current = controls[name]?.value;
      for (const entry of entries) {
        const active = String(current) === String(entry.value);
        Object.assign(entry.button.style, active ? {
          borderColor: C.mint,
          color: C.text,
          background: "linear-gradient(135deg,rgba(57,230,173,.22),rgba(74,215,255,.10))",
          boxShadow: "inset 0 0 0 1px rgba(57,230,173,.10),0 0 14px rgba(57,230,173,.08)",
        } : {
          borderColor: C.line,
          color: C.muted,
          background: "#0a100e",
          boxShadow: "none",
        });
      }
    };
    refreshers.push(update);
    container.append(grid);
    groups.push(entries);
  }

  const scaleBox = section("01 · OUTPUT SCALE", "2× recommended");
  buttonGroup(scaleBox, "scale", [
    { value: 1.5, label: "1.5×" },
    { value: 2.0, label: "2×" },
    { value: 3.0, label: "3×" },
    { value: 4.0, label: "4×" },
  ], 4);

  const engineBox = section("02 · UPSCALE ENGINE", "quality-first upscale");
  buttonGroup(engineBox, "upscale_quality", [
    { value: "Ultra", label: "ULTRA", hint: "best general" },
    { value: "High", label: "HIGH", hint: "faster" },
    { value: "High-Bitrate Ultra", label: "HB ULTRA", hint: "clean source" },
    { value: "High-Bitrate High", label: "HB HIGH", hint: "clean + fast" },
  ], 4);

  const restoreBox = section("03 · DETAIL RESTORATION", "choose by source condition");
  buttonGroup(restoreBox, "restore_mode", [
    { value: "Auto Scan (Clean/Chain90)", label: "AUTO SAFE", hint: "motion guarded" },
    { value: "Deblur Low", label: "CLEAN", hint: "first clip" },
    { value: "Deblur Medium", label: "DETAIL", hint: "soft image" },
    { value: "Denoise Low", label: "DENOISE", hint: "grain / blocks" },
    { value: "Chain Late Recovery 90", label: "CHAIN 90", hint: "late-chain rescue" },
  ], 5);

  const temporalBox = section("04 · TEMPORAL DETAIL LOCK", "bidirectional flow + occlusion guard");
  buttonGroup(temporalBox, "temporal_mode", [
    { value: "Auto Temporal", label: "AUTO", hint: "recommended" },
    { value: "Face Lock", label: "FACE LOCK", hint: "slow portraits" },
    { value: "Action Stable", label: "ACTION", hint: "minimum ghosting" },
    { value: "Off", label: "OFF", hint: "single-frame only" },
  ], 4);

  const motionRepairBox = section("05 · MOTION REPAIR", "NVOFA · prev / current / next local repair");
  buttonGroup(motionRepairBox, "motion_repair", [
    { value: "Auto", label: "AUTO", hint: "recommended" },
    { value: "Action Strong", label: "ACTION+", hint: "fast motion" },
    { value: "NVIDIA 가변 프레임 보간", label: "NVIDIA VFI", hint: "variable repair" },
    { value: "Off", label: "OFF", hint: "bypass repair" },
  ], 4);
  motionRepairBox.append(el("div", {
    marginTop: "8px", marginBottom: "6px", color: C.muted, fontSize: "8px", fontWeight: "750",
  }, "LOCAL REPAIR STRENGTH · damaged regions only"));
  buttonGroup(motionRepairBox, "motion_repair_strength", [
    { value: 20, label: "LOW", hint: "20%" },
    { value: 30, label: "STANDARD", hint: "30%" },
    { value: 40, label: "STRONG", hint: "40%" },
  ], 3);

  const subjectBox = section("06 · SUBJECT RECOVERY", "small-person ROI restoration");
  buttonGroup(subjectBox, "subject_recovery", [
    { value: "Auto", label: "AUTO FULL-SHOT", hint: "shot size auto-switch" },
    { value: "Full Shot Strong", label: "FULL SHOT", hint: "strong person recovery" },
    { value: "Off", label: "OFF", hint: "whole frame only" },
  ], 3);

  const masterBox = section("07 · MASTERING", "bounded luminance detail");
  buttonGroup(masterBox, "quality_target", [
    { value: "100% Restore", label: "100%", hint: "natural" },
    { value: "105% Master", label: "105%", hint: "stable detail" },
    { value: "110% Master", label: "110%", hint: "maximum" },
  ], 3);

  const colorBox = section("08 · AUTO COLOR", "temporal clean-tone correction");
  buttonGroup(colorBox, "color_treatment", [
    { value: "Off", label: "OFF", hint: "original tone" },
    { value: "Auto Natural", label: "NATURAL", hint: "recommended" },
    { value: "Auto Bright", label: "BRIGHT", hint: "strong lift" },
  ], 3);

  const qualityBox = section("09 · OUTPUT QUALITY", "80–99 · recommended 95");
  const qualityTop = el("div", { display: "flex", gap: "6px", alignItems: "center" });
  const qualityButtons = el("div", { display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: "5px", flex: "1" });
  const qEntries = [];
  for (const value of [80, 85, 90, 95, 99]) {
    const button = el("button", {
      height: "27px", borderRadius: "7px", border: `1px solid ${C.line}`,
      background: "#0a100e", color: C.muted, fontSize: "9px", fontWeight: "850", cursor: "pointer",
    }, String(value));
    button.type = "button";
    button.onpointerdown = stopEvent;
    button.onclick = (event) => { stopEvent(event); setValue("output_quality", value); };
    qEntries.push({ button, value });
    qualityButtons.append(button);
  }
  const qualityReadout = el("div", {
    width: "46px", textAlign: "center", fontSize: "14px", fontWeight: "900", color: C.mint,
  });
  qualityTop.append(qualityButtons, qualityReadout);
  const slider = el("input", { width: "100%", marginTop: "7px", accentColor: C.green, cursor: "pointer" });
  slider.type = "range";
  slider.min = "80";
  slider.max = "99";
  slider.step = "1";
  slider.onpointerdown = (event) => event.stopPropagation();
  slider.oninput = () => setValue("output_quality", Number(slider.value));
  qualityBox.append(qualityTop, slider);
  refreshers.push(() => {
    const value = Number(controls.output_quality?.value ?? 95);
    slider.value = String(value);
    qualityReadout.textContent = `Q${value}`;
    for (const entry of qEntries) {
      const active = value === entry.value;
      entry.button.style.borderColor = active ? C.mint : C.line;
      entry.button.style.color = active ? C.text : C.muted;
      entry.button.style.background = active ? "rgba(57,230,173,.18)" : "#0a100e";
    }
  });

  const encodeBox = section("10 · ENCODE PROFILE", "speed vs compression");
  buttonGroup(encodeBox, "encode_preset", [
    { value: "medium", label: "BALANCED" },
    { value: "slow", label: "PRO" },
    { value: "slower", label: "MAX" },
  ], 3);

  const hdrBox = section("11 · 출력 색상 / 비트 깊이", "SDR · SDR 10bit · HDR");
  buttonGroup(hdrBox, "output_mode", [
    { value: "SDR", label: "SDR", hint: "H.264 · 8bit" },
    { value: "SDR 10bit", label: "SDR 10bit", hint: "HEVC · Rec.709" },
    { value: "HDR", label: "HDR", hint: "HEVC · BT.2020 / PQ" },
  ], 3);
  hdrBox.append(el("div", { color: C.muted, fontSize: "9px", marginTop: "7px", lineHeight: "1.5" },
    "10bit는 저장 정밀도입니다. HDR은 SDR → PQ 변환(백색 203nit)이며 원본 HDR 복원은 아닙니다. Save Video: format / codec = auto."));

  const queue = el("button", {
    width: "100%",
    height: "38px",
    border: "0",
    borderRadius: "10px",
    background: `linear-gradient(100deg,${C.green},${C.mint} 60%,${C.cyan})`,
    color: "#06100b",
    fontSize: "10px",
    fontWeight: "950",
    letterSpacing: ".12em",
    cursor: "pointer",
    boxShadow: "0 8px 22px rgba(57,230,173,.16)",
  }, "QUEUE RESTORATION");
  queue.type = "button";
  queue.onpointerdown = stopEvent;
  queue.onclick = async (event) => {
    stopEvent(event);
    if (queue.disabled) return;
    queue.disabled = true;
    queue.textContent = "QUEUED · PROCESSING";
    queue.style.opacity = ".65";
    try { await app.queuePrompt(0, 1); }
    catch (error) { console.error("[SRFPTyp UI] queue failed", error); }
    setTimeout(() => {
      queue.disabled = false;
      queue.textContent = "QUEUE RESTORATION";
      queue.style.opacity = "1";
    }, 1800);
  };
  root.append(queue);

  function refresh() {
    refreshers.forEach((fn) => fn());
    const scale = Number(controls.scale?.value ?? 2).toFixed(2).replace(/\.00$/, "");
    const engine = controls.upscale_quality?.value ?? "Ultra";
    const restore = controls.restore_mode?.value ?? "Auto Scan (Clean/Chain90)";
    const master = controls.quality_target?.value ?? "110% Master";
    const color = controls.color_treatment?.value ?? "Auto Natural";
    const temporal = controls.temporal_mode?.value ?? "Auto Temporal";
    const motionRepair = controls.motion_repair?.value ?? "Auto";
    const motionStrength = controls.motion_repair_strength?.value ?? 30;
    const subject = controls.subject_recovery?.value ?? "Auto";
    const quality = controls.output_quality?.value ?? 95;
    const hdr = controls.output_mode?.value ?? (controls.hdr_enabled?.value === true ? "HDR" : "SDR");
    summaryValue.textContent = `${scale}×  ›  ${engine}  ›  ${restore}  ›  ${temporal}  ›  Motion ${motionRepair} ${motionStrength}%  ›  Subject ${subject}  ›  ${master}  ›  ${color}  ›  Q${quality}  ›  ${hdr}`;
    summary.style.borderColor = restore === "Chain Late Recovery 90" ? "rgba(255,199,102,.55)" : C.line;
    summaryTitle.style.color = restore === "Chain Late Recovery 90" ? C.amber : C.muted;
  }

  const domWidget = node.addDOMWidget("srfptyp_studio", "div", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => HEIGHT,
    getMaxHeight: () => HEIGHT,
    getValue: () => null,
    setValue: () => {},
  });
  domWidget.computeSize = () => [WIDTH, HEIGHT];
  node.__srfptypRefresh = refresh;
  node.setSize([WIDTH, HEIGHT + 66]);
  refresh();
  setTimeout(hideControls, 0);
  setTimeout(hideControls, 120);
}

app.registerExtension({
  name: "Flagship.SRFPTypUpscalerUI",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_NAME) return;

    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = originalCreated?.apply(this, arguments);
      try { installPanel(this); }
      catch (error) { console.error("[SRFPTyp UI] build failed", error); }
      return result;
    };

    const originalConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const result = originalConfigure?.apply(this, arguments);
      migrateLegacyWidgetValues(this, arguments[0]);
      const settle = () => {
        this.__srfptypHideNative?.();
        this.__srfptypRefresh?.();
        this.setSize?.([WIDTH, HEIGHT + 66]);
        this.setDirtyCanvas?.(true, true);
      };
      setTimeout(settle, 0);
      setTimeout(settle, 120);
      setTimeout(settle, 350);
      return result;
    };

    nodeType.prototype.onResize = function () {
      this.size = [WIDTH, HEIGHT + 66];
    };
  },
});
