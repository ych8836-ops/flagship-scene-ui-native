# Native edition feature manual

[Korean illustrated manual](사용설명서_KO.md)

All 27 images are Korean explanatory diagrams, not screenshots. This English index explains the same native behavior.

## 01. YOUR WORKSPACE

[Korean image](images/01-workspace_ko.png)

The top input rail holds media. Settings, preview/outputs and scene map have separate panels. Use side dividers to adjust widths and the layout reset to restore placement. The scene map is a UI navigation diagram, not the Comfy execution graph.

## 02. START A PROJECT

[Korean image](images/02-new-project_ko.png)

Use the saved-project selector to reopen original outputs and context. Create a new project for another plan or geometry. Regeneration belongs to the original project. The project name is protected once the project exists.

## 03. JSON PLAN → VIDEO

[Korean image](images/03-json-import_ko.png)

Give an LLM the prompt rules, an exported settings plan, story and actual reference filenames/order. Import the resulting scenes/clips/settings/references plan into a new project, then review it. This is not a node workflow and does not embed media or weights. Whole-plan import is blocked when the project already has generated clips; import does not automatically switch projects.

## 04. NORMAL OR SEQUENCE?

[Korean image](images/04-normal-sequence_ko.png)

Normal mode carries a continuous clip chain. Sequence mode continues within each scene and starts fresh at scene boundaries by default. Keep a continuous action together; create a scene for a substantial setting/time change. Use the workspace mode toggle. See guide 18 for the native assembly path.

## 05. PLAN YOUR SCENES

[Korean image](images/05-scene-plan_ko.png)

Add a scene or split at the current clip. Put scene-local setting/light/direction in its shared prompt. continue_previous controls the first clip of a scene; clips inside a scene continue. The first project clip has no prior context. Keep a scene's clips contiguous in JSON.

## 06. EDIT CLIPS TOGETHER

[Korean image](images/06-clip-editor_ko.png)

Numbered buttons open clip settings. Multi-select/all-select displays multiple editor cards for prompts, seconds and seeds. Bulk text input differs from full JSON-plan import. Add/remove ungenerated clips as needed, save, or export the plan. Saving does not generate video.

## 07. ROUTE THE RIGHT IMAGES

[Korean image](images/07-image-routing_ko.png)

With common references enabled, @picture_N follows project reference order in normal mode and the active scene's order in sequence mode. Mention only needed images. Tags in shared/scene prompts also count, so avoid listing the entire cast globally. Selection is clip-wide, not per-shot voice routing. With common references off, use clip-local lists and <Picture N>.

## 08. VIDEO & AUDIO REFERENCES

[Korean image](images/08-media-references_ko.png)

Up to 9 images, 3 videos and 3 audio references are supported. Check a video's audio-use switch. Reference audio guides sound; it is distinct from the project lipsync track. Common videos/audio are not filtered by @picture tags. Search existing files, reorder/remove inputs and recheck their scope. Files must exist in the execution environment.

## 09. I2V START & END FRAMES

[Korean image](images/09-i2v-keyframes_ko.png)

Choose I2V, R2V or T2V per clip. I2V exposes opening and optional closing image inputs. Continued clips use incoming AV context; an opening image is not forcibly reapplied to every continuation. Distinguish independent scene starts from continued clips.

## 10. DIALOGUE & LIPSYNC AUDIO

[Korean image](images/10-lipsync_ko.png)

The common lipsync track spans the project timeline; empty means H3 generates audio from the prompt. It is not reference audio or a voice LoRA. Check actual speech, speakers and lip movement, especially in crowded dialogue. Character-specific voice-LoRA routing is not implemented.

## 11. SET OUTPUT GEOMETRY

[Korean image](images/11-resolution_ko.png)

Choose aspect ratio/MP below clip planning and inspect the actual W × H display. MP alone does not specify a fixed short edge. Existing project geometry is protected for context/assembly compatibility; create a new project to change it. Upscaling is separate from generation resolution.

## 12. MODELS & LORA STACK

[Korean image](images/12-models-loras_ko.png)

Select actual model, encoder and video/audio VAE files. Match Turbo family and sampling setup. The reference LoRA adapts reference conditioning; it is not a voice-training feature. Search additional LoRAs, set strengths/toggles and refresh after adding files. A LoRA stack is not an automatic per-character speaker mask.

## 13. OPTIMIZERS & MEMORY

[Korean image](images/13-optimizers_ko.png)

Choose supported attention/accumulation/cache/feed-forward chunk settings. Reference sizing match/max changes input cost and retained detail. Chunking is not interpolation or automatic restoration. Kernel/cache support depends on environment/branch. Change one setting at a time and compare output as well as speed/VRAM.

## 14. CHOOSE AN ACTION, GENERATE

[Korean image](images/14-generate_ko.png)

Clip generates the selected clip; All clips follows the plan; All + Assemble adds final assembly. Generate executes the selected action. Queue next helps sequential work without creating a new run each time. Stop/cancel acts on the app's work. Upscaling follows its own enabled setting, not the label alone.

## 15. RETRY ONE CLIP

[Korean image](images/15-regenerate_ko.png)

Select an existing clip in its original project, edit it and run Clip generation. Prior revisions and other stored results remain. Dependent later clips may become stale until the next independent boundary. This is not guaranteed bidirectional fitting or automatic regeneration of the whole project.

## 16. READ THE SCENE MAP

[Korean image](images/16-scene-map_ko.png)

Scene labels, clip numbers and revision branches identify the selected result. Read connection colours with status text. Completed hover previews, running live previews and failure labels have different roles. Map cards do not create Comfy execution nodes.

## 17. OUTPUTS ACROSS PROJECTS

[Korean image](images/17-gallery_ko.png)

Filter all/current projects, preview clip/export/revision results and show favorites. Use multi-selection for trash operations and Storage for file location. Refresh updates the list. Gallery upscaling expects one eligible assembled export, not arbitrary bulk clips.

## 18. HOW NATIVE ASSEMBLY WORKS

[Korean image](images/18-assembly_ko.png)

Native sequence mode stitches each scene's AV overlap with Endless, then automatically joins completed scenes via FFmpeg. Final scene video is stream-copied; audio may be aligned and AAC re-encoded. Native normal concatenates MP4 clips with FFmpeg. Keep AV archives for Endless reassembly.

## 19. UPSCALE A FINAL EXPORT

[Korean image](images/19-upscaling_ko.png)

Select one eligible assembled export for independent gallery upscaling. Set scale, memory profile, auto colour and output quality. Quality 95 can produce very large files; equal numbers across encoders do not imply equal loss/size. Install required NVIDIA runtimes separately. Compare colour, geometry and audio throughout the output.

## 20. MOTION REPAIR & INTERPOLATION

[Korean image](images/20-motion-repair_ko.png)

Selective temporal/flow repair uses neighboring frames and midpoint candidates. It does not guarantee reconstruction of detail already absent from the source. Strength/mode can introduce ghosting or occlusion errors. The starter workflow uses Off. Check runtime support, frame count, duration and sync alongside fast-action image quality.

## 21. REFRESH A DEGRADED BACKGROUND

[Korean image](images/21-background-refresh_ko.png)

Available for regeneration of an existing clip. Choose a new background image or a timed frame from the project's global Clip 1. Guidance may also affect people; it is not a background-only mask. Clip + Generate retries one. Regenerate from here queues the remainder. Apply to later completed clips copies settings only.

## 22. CLIP REFINER: USE SELECTIVELY

[Korean image](images/22-clip-refiner_ko.png)

Choose Off/On per clip, then strength and a valid earlier reference. Compare within a scene; avoid carrying unrelated texture statistics across scene changes. An independent first clip supplies measurements. It is not face restoration, speaker routing or motion repair, and prompt text does not guarantee an optimal strength.

## 23. OPEN CAMERA DIRECTION

[Korean image](images/23-camera-directing_ko.png)

R2V reference video enables camera direction. The button opens its editor; choose controls there and inspect animated hover guides. Model/sampling/resolution, results and Generate stay integrated with the main UI. Modes may use crops, generation, depth guidance or optional adapters. Large rotation success is not guaranteed.

## 24. CAMERA PATHS BY SEGMENT

[Korean image](images/24-camera-segments_ko.png)

Split source frame ranges and verify their time display. Set numeric angles, zoom/movement, speed and easing per segment. Required models/adapters depend on the mode. Hover dummy animations explain controls; they are not evidence of generated quality. Review occlusion, identity and lips against the source sound.

## 25. SETTINGS & VRAM RESET

[Korean image](images/25-settings-vram_ko.png)

Use the gear for shared model/sampling settings and UI font scale. Combine font sizing with panel widths/scrolling. VRAM reset requests model/cache release when idle; it cannot promise to free allocations held by other processes or drivers. Do not treat it as a required server restart.

## 26. INSPECT THE EXECUTION GRAPH

[Korean image](images/26-view-nodes_ko.png)

View nodes exposes the selected clip's execution graph, unlike the scene map. Inspect model/conditioning/sampling/save connections, then return to the studio. Do not assume arbitrary graph edits synchronize back into the saved plan. The examples use the studio plan as the source of truth.

## 27. INSTALL THE NATIVE EDITION

[Korean image](images/27-installation_ko.png)

Install.cmd asks for ComfyUI and copies only Flagship code. Install external custom nodes separately from their attributed sources or the explicit dependency tool. Existing packs are not overwritten. Models, Python dependencies and NVIDIA runtimes are separate. The protected image-upscaler binary is only in the Full ZIP.
