// Fullscreen presentation for the live timeline node. The same DOM tree is
// moved into the overlay and restored afterwards, matching H3One's behavior.
export function createCameraStudio(app, _panelFactory, doc = document) {
    const PANEL_WIDTH = 1200;
    const PANEL_HEIGHT = 700;
    let current = null;
    let returnButton = null;
    let returnNode = null;
    const buttonStyle = {
        height: "36px", padding: "0 14px", borderRadius: "9px",
        border: "1px solid #315d50", background: "linear-gradient(180deg,#173e31,#102b23)",
        color: "#ecfff6", cursor: "pointer", font: "700 12px Segoe UI, sans-serif",
        boxShadow: "inset 0 1px 0 #ffffff16,0 3px 10px #0005",
    };
    function element(tag, style = {}, text = "") {
        const el = doc.createElement(tag);
        Object.assign(el.style, style);
        el.textContent = text;
        return el;
    }
    function button(text, action) {
        const el = element("button", buttonStyle, text);
        el.type = "button";
        el.onclick = action;
        return el;
    }
    const inGraph = node => app.graph?._nodes?.includes(node);
    function setNodeButton(node, opened) {
        const control = node?.__h3CameraStudioButton;
        if (!control) return;
        control.textContent = opened ? "노드 화면으로 돌아가기" : "올인원 화면 열기";
        control.dataset.active = opened ? "1" : "";
    }
    function removeReturn() {
        returnButton?.remove();
        returnButton = null;
        returnNode = null;
    }
    function showReturn(node) {
        removeReturn();
        if (!inGraph(node)) return;
        returnNode = node;
        returnButton = button("카메라 올인원으로 돌아가기", () => open(node));
        Object.assign(returnButton.style, { position: "fixed", right: "24px", bottom: "28px", zIndex: "10001" });
        doc.body.append(returnButton);
    }
    function restoreRoot(state) {
        if (!state?.root) return;
        if (state.originalParent?.isConnected) {
            if (state.originalNextSibling?.parentNode === state.originalParent) state.originalParent.insertBefore(state.root, state.originalNextSibling);
            else state.originalParent.appendChild(state.root);
        }
        if (state.originalStyle == null) state.root.removeAttribute("style");
        else state.root.setAttribute("style", state.originalStyle);
    }
    function close(showNodes = false) {
        const old = current;
        current = null;
        if (old) {
            window.removeEventListener("resize", old.resize);
            restoreRoot(old);
            old.overlay.remove();
            old.node.properties ||= {};
            old.node.properties.h3CameraStudio = false;
            setNodeButton(old.node, false);
            old.node.__h3CameraTimelineUI?.reload?.();
            old.node.setDirtyCanvas?.(true, true);
            if (showNodes && inGraph(old.node)) showReturn(old.node);
        }
        if (!showNodes) removeReturn();
    }
    function open(node) {
        if (!inGraph(node) || !doc.body) return;
        if (current?.node === node) return;
        const root = node.__h3CameraTimelineUI?.root;
        if (!root?.parentNode) return;
        close();
        removeReturn();
        node.properties ||= {};
        node.properties.h3CameraStudio = true;

        const overlay = element("section", {
            position: "fixed", inset: "0", zIndex: "10000", display: "flex", flexDirection: "column",
            background: "radial-gradient(circle at 50% 0%,#193c30 0,#091510 58%,#050b09 100%)",
            color: "#eefbf4", fontFamily: "Segoe UI, sans-serif", overflow: "hidden",
        });
        overlay.setAttribute("aria-label", "H3 카메라 올인원");
        overlay.tabIndex = -1;
        const bar = element("header", {
            height: "54px", boxSizing: "border-box", display: "flex", alignItems: "center", gap: "10px",
            padding: "9px 18px", borderBottom: "1px solid #29483b", background: "#091712ed", flexShrink: "0",
        });
        const title = element("div", { flex: "1", minWidth: "180px", fontSize: "17px", fontWeight: "800" }, "H3 · CAMERA STUDIO");
        const status = element("span", { fontSize: "11px", color: "#a8c9b9", maxWidth: "360px" }, "동일 노드 화면 · 원본 음성 유지 · 결과 자동 미리보기");
        const queue = button("영상 생성", async () => {
            if (queue.disabled || !inGraph(node)) return;
            doc.activeElement?.blur?.();
            queue.disabled = true;
            queue.textContent = "요청 중…";
            try {
                if (typeof app.queuePrompt !== "function") throw new Error("ComfyUI 생성 기능을 찾을 수 없습니다.");
                await app.queuePrompt(0, 1);
                status.textContent = "실행 요청 완료 · 완료 영상은 오른쪽 결과 창에 표시됩니다.";
            } catch (error) {
                status.textContent = `실행 요청 실패 · ${error?.message || error}`;
            } finally {
                queue.disabled = false;
                queue.textContent = "영상 생성";
            }
        });
        const nodes = button("노드 보기", () => close(true));
        nodes.title = "현재 화면을 원래 ComfyUI 노드 위치로 되돌립니다.";
        bar.append(title, status, queue, nodes);

        const viewport = element("main", { flex: "1", minHeight: "0", position: "relative", overflow: "hidden" });
        const stage = element("div", {
            position: "absolute", left: "50%", top: "50%", transform: "translate(-50%,-50%)",
            transformOrigin: "center center", borderRadius: "16px", overflow: "hidden",
            boxShadow: "0 26px 72px #000b,0 0 0 1px #3a6658",
        });
        const originalParent = root.parentNode;
        const originalNextSibling = root.nextSibling;
        const originalStyle = root.getAttribute("style");
        root.style.width = `${PANEL_WIDTH}px`;
        root.style.height = `${PANEL_HEIGHT}px`;
        root.style.borderRadius = "16px";
        root.style.margin = "0";
        stage.append(root);
        viewport.append(stage);
        overlay.append(bar, viewport);
        doc.body.append(overlay);

        const resize = () => {
            const availableWidth = Math.max(320, viewport.clientWidth - 32);
            const availableHeight = Math.max(240, viewport.clientHeight - 32);
            const scale = Math.min(availableWidth / PANEL_WIDTH, availableHeight / PANEL_HEIGHT) * 0.985;
            stage.style.width = `${Math.round(PANEL_WIDTH * scale)}px`;
            stage.style.height = `${Math.round(PANEL_HEIGHT * scale)}px`;
            root.style.transformOrigin = "top left";
            root.style.transform = `scale(${scale})`;
        };
        current = { node, root, overlay, stage, originalParent, originalNextSibling, originalStyle, resize };
        setNodeButton(node, true);
        window.addEventListener("resize", resize);
        requestAnimationFrame(resize);
        overlay.addEventListener("keydown", event => {
            event.stopPropagation();
            if (event.key === "Escape") close(true);
        });
        overlay.addEventListener("keyup", event => event.stopPropagation());
        overlay.focus();
        node.__h3CameraTimelineUI?.reload?.();
    }
    function toggle(node) {
        if (current?.node === node) close(true);
        else open(node);
    }
    function sync() {
        close();
        const node = app.graph?._nodes?.find(n => n.type === "H3R2VCameraTimeline" && n.__h3CameraTimelineUI);
        if (!node) return;
        node.properties ||= {};
        // The timeline is an All-in-One-first workflow. Always enter Studio
        // after a graph is loaded; node view remains available as a deliberate
        // temporary escape through the header button.
        node.properties.h3CameraStudio = true;
        setNodeButton(node, true);
        node.__h3CameraTimelineUI?.reload?.();
        const defer = typeof requestAnimationFrame === "function" ? requestAnimationFrame : callback => callback();
        defer(() => open(node));
    }
    function remove(node) {
        if (current?.node === node) close();
        if (returnNode === node) removeReturn();
    }
    return { open, close, toggle, sync, remove };
}
