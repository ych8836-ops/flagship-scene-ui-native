// Associate preview frames with the exact server job; never reuse another clip's image.
export class StudioLivePreview {
    constructor(api, activeJob, update) {
        this.api = api; this.activeJob = activeJob; this.update = update;
        this.seen = new WeakSet(); this.listeners = [];
        const on = (name, handler) => { api.addEventListener(name, handler); this.listeners.push([name, handler]); };
        on('execution_start', event => { this.clear(); this.executing = event.detail?.prompt_id || null; });
        on('b_preview_with_metadata', event => {
            const {blob, jobId} = event.detail || {};
            if (blob instanceof Blob) this.seen.add(blob);
            this.accept(blob, jobId);
        });
        on('b_preview', event => {
            if (event.detail instanceof Blob && !this.seen.has(event.detail)) this.accept(event.detail, this.executing);
        });
        for (const name of ['execution_success', 'execution_error', 'execution_interrupted']) on(name, event => {
            if (event.detail?.prompt_id === this.executing || event.detail?.prompt_id === this.frame?.prompt) {
                this.executing = null; this.clear();
            }
        });
    }

    current() {
        const job = this.activeJob();
        if (!job || !['preparing', 'queued', 'running'].includes(job.state) ||
            ['assemble', 'upscale'].includes(job.action) || job.id !== this.frame?.job || job.prompt_id !== this.frame?.prompt) return null;
        return this.frame;
    }

    accept(blob, prompt) {
        const job = this.activeJob();
        if (!(blob instanceof Blob) || !blob.type.startsWith('image/') || !prompt ||
            !job?.prompt_id || job.prompt_id !== prompt || !['preparing', 'queued', 'running'].includes(job.state) ||
            ['assemble', 'upscale'].includes(job.action)) return;
        const previous = this.frame?.url;
        this.frame = {job: job.id, prompt, url: URL.createObjectURL(blob)};
        this.update(this.frame);
        if (previous) URL.revokeObjectURL(previous);
    }

    clear() {
        const previous = this.frame?.url;
        this.frame = null; this.update(null);
        if (previous) URL.revokeObjectURL(previous);
    }

    dispose() {
        for (const [name, listener] of this.listeners) this.api.removeEventListener(name, listener);
        this.listeners = []; this.clear();
    }
}
