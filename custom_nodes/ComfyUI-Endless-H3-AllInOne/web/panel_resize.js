const storageKey = 'endless_h3_panel_layout';
const defaults = {controls_x: .32, controls_y: .3, preview_x: .45, preview_y: .5, outputs_y: .7};

export function panelFraction(start, delta, span, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, start + (span > 0 ? delta / span : 0)));
}

function loadLayout(value) {
    const sizes = {};
    for (const key of Object.keys(defaults)) {
        if (Number.isFinite(value?.[key]) && value[key] > 0 && value[key] < 1) sizes[key] = value[key];
    }
    return sizes;
}

export class StudioPanelResize {
    constructor(root, properties, save) {
        this.root = root;
        this.properties = properties;
        this.save = save;
        this.bindings = [];
        this.drag = null;
        let stored = {};
        try { stored = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch { /* Browser storage can be disabled. */ }
        this.sizes = loadLayout(properties.endless_panel_layout || stored);
        properties.endless_panel_layout = this.sizes;
        this.apply();
    }

    apply() {
        for (const key of Object.keys(defaults)) {
            const [name, axis] = key.split('_');
            this.root.style.setProperty(`--${name}-${axis}`, `${(this.sizes[key] ?? defaults[key]) * 100}%`);
        }
    }

    commit() {
        try { localStorage.setItem(storageKey, JSON.stringify(this.sizes)); } catch { /* Node properties still retain the layout. */ }
        this.save();
    }

    bind(container, first, second, name, label) {
        const handle = document.createElement('div');
        handle.className = 'eh3-panel-resizer';
        handle.tabIndex = 0;
        handle.setAttribute('role', 'separator');
        handle.setAttribute('aria-label', label);
        handle.title = `${label} · 드래그 또는 방향키로 조절 · 두 번 클릭하면 기본 크기`;
        container.insertBefore(handle, second);
        const binding = {container, first, handle, name};
        this.bindings.push(binding);
        const measure = () => {
            const style = getComputedStyle(container);
            const axis = style.getPropertyValue('--panel-axis').trim() || 'x';
            const rect = container.getBoundingClientRect();
            const span = axis === 'x' ? rect.width : rect.height;
            const cssSpan = axis === 'x' ? container.clientWidth : container.clientHeight;
            const divider = axis === 'x' ? handle.offsetWidth : handle.offsetHeight;
            const firstMin = parseFloat(style.getPropertyValue('--panel-first-min'));
            const lastMin = parseFloat(style.getPropertyValue('--panel-last-min'));
            const minimum = Math.min(.9, firstMin / Math.max(cssSpan, 1));
            const maximum = Math.max(minimum, 1 - (lastMin + divider) / Math.max(cssSpan, 1));
            const firstRect = first.getBoundingClientRect();
            const fraction = span > 0 ? (axis === 'x' ? firstRect.width : firstRect.height) / span : defaults[`${name}_${axis}`];
            return {axis, span, minimum, maximum, fraction, key: `${name}_${axis}`};
        };
        const update = () => {
            const m = measure();
            handle.dataset.axis = m.axis;
            handle.setAttribute('aria-orientation', m.axis === 'x' ? 'vertical' : 'horizontal');
            handle.setAttribute('aria-valuemin', String(Math.round(m.minimum * 100)));
            handle.setAttribute('aria-valuemax', String(Math.round(m.maximum * 100)));
            handle.setAttribute('aria-valuenow', String(Math.round(m.fraction * 100)));
        };
        const set = (m, fraction) => {
            this.sizes[m.key] = fraction;
            this.apply(); update();
        };
        const finish = event => {
            if (!this.drag || this.drag.handle !== handle || (event && event.pointerId !== this.drag.id)) return;
            const id = this.drag.id;
            this.drag = null;
            handle.classList.remove('dragging');
            if (handle.hasPointerCapture(id)) handle.releasePointerCapture(id);
            this.commit();
        };
        handle.addEventListener('pointerdown', event => {
            if (event.button !== 0) return;
            event.preventDefault(); event.stopPropagation();
            const m = measure();
            this.drag = {handle, id: event.pointerId, m, start: m.axis === 'x' ? event.clientX : event.clientY};
            handle.setPointerCapture(event.pointerId);
            handle.classList.add('dragging');
        });
        handle.addEventListener('pointermove', event => {
            const drag = this.drag;
            if (!drag || drag.handle !== handle || drag.id !== event.pointerId) return;
            event.preventDefault(); event.stopPropagation();
            const coordinate = drag.m.axis === 'x' ? event.clientX : event.clientY;
            set(drag.m, panelFraction(drag.m.fraction, coordinate - drag.start, drag.m.span, drag.m.minimum, drag.m.maximum));
        });
        handle.addEventListener('pointerup', finish);
        handle.addEventListener('pointercancel', finish);
        handle.addEventListener('lostpointercapture', finish);
        handle.addEventListener('dblclick', event => {
            event.preventDefault(); event.stopPropagation();
            delete this.sizes[measure().key];
            this.apply(); update(); this.commit();
        });
        handle.addEventListener('keydown', event => {
            const m = measure();
            const decrease = m.axis === 'x' ? 'ArrowLeft' : 'ArrowUp';
            const increase = m.axis === 'x' ? 'ArrowRight' : 'ArrowDown';
            if (![decrease, increase, 'Home', 'End'].includes(event.key)) return;
            event.preventDefault(); event.stopPropagation();
            const step = event.shiftKey ? .05 : .02;
            const fraction = event.key === 'Home' ? m.minimum : event.key === 'End' ? m.maximum :
                panelFraction(m.fraction, event.key === decrease ? -step : step, 1, m.minimum, m.maximum);
            set(m, fraction); this.commit();
        });
        binding.observer = new ResizeObserver(update);
        binding.observer.observe(container);
        update();
    }

    dispose() {
        if (this.drag) {
            const {handle, id} = this.drag;
            this.drag = null;
            if (handle.hasPointerCapture(id)) handle.releasePointerCapture(id);
            this.commit();
        }
        for (const binding of this.bindings) { binding.observer.disconnect(); binding.handle.remove(); }
        this.bindings = [];
    }
}
