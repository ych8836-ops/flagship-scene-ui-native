# ComfyUI H3 R2V Camera + Lip Lock

> **2026-09-05 update:** Use `workflows/H3_R2V_Camera_SourceEdit_8Step.json`.
> See [current update guide](SOURCE_EDIT_UPDATE_KO.md) for the new source-latent
> route, actual denoise control, 8-step R2V LoRA and Sage/Spectrum switches.
> The older guide/workflow below is historical: flat reference inputs and full
> source-audio mux are superseded. Lip tracking/enforcement is not implemented.

Standalone video-only controller for MiniMax H3 Reference-to-Video workflows.

This node does not replace the H3 sampler. It prepares one synchronized source
video segment at a time and supplies:

- segment video frames for `MiniMaxH3ReferenceToVideo.ref_video_0`
- the matching source-audio segment for `ref_video_audio_0`
- the complete untouched source audio for the final video mux
- a per-segment camera and lip-sync prompt
- a JSON camera plan for logging or downstream controller nodes

## Install

Copy this folder into:

```text
YOUR_COMFYUI\custom_nodes\ComfyUI-H3-R2V-CameraLipLock
```

Restart ComfyUI and search for **H3 R2V Camera + Lip Lock**.

No model files are included and no additional Python package is required.

## Button UI

The supplied workflow now presents one visible **H3 R2V Camera Timeline
(All-in-One UI)** node. The three per-segment controller nodes remain in the
graph as hidden execution branches, so the user does not need to open or edit
them during normal use.

The node opens with an All-in-One-style **CAMERA + LIP LOCK** panel. Use the
buttons inside each controller node to choose `SEGMENT 1`, `SEGMENT 2`, and so
on, then choose the shot, camera movement, speed, motion strength, and lip-lock
strength. The selected values are written back to the node's saved graph values
and to `camera_plan_json`, so the workflow remains portable and reproducible.

The panel also has **UPLOAD SOURCE VIDEO**. After choosing a video, use the
preview player to move the playhead and press **SET START AT PLAYHEAD** or
**SET END AT PLAYHEAD**. The selected seconds are converted to the exact source
frame range automatically. The All-in-One timeline node loads the uploaded
source internally; no separate source-video, IMAGE, or AUDIO connection is
required for the timeline node.

Because the supplied workflow has one controller branch per generated segment,
editing the plan in any controller panel synchronizes the plan to all matching
`H3 R2V Camera + Lip Lock` controllers. Leave their execution segment indices
as `0`, `1`, `2`, ...; the `SEGMENT` buttons select which plan row is being
edited and do not change those execution indices.

`+ ADD` adds another segment to the plan. `RESET 3 SEGMENTS` restores the safe
three-segment starting layout. The raw JSON and fallback widgets are retained
internally for compatibility, but do not need to be edited by hand.

## Important audio rule

Connect `source_audio` from the first controller node directly to the final
`CreateVideo` or `VHS_VideoCombine` audio input. The per-segment `segment_audio`
output is only for H3's audio-conditioned R2V generation. The generated audio
must never be used as the final soundtrack when exact source-audio continuity
is required.

## Camera plan

The node accepts either a JSON plan or the visible fallback camera controls.
Use frame indices for deterministic timing. H3 reference-video lengths should
normally be `17n + 5`; `124` frames is the recommended approximately 5.17-second
segment at 24 fps.

```json
{
  "segments": [
    {
      "start_frame": 0,
      "end_frame": 124,
      "shot": "wide shot",
      "movement": "slow dolly in",
      "speed": "slow",
      "strength": 0.35
    },
    {
      "start_frame": 124,
      "end_frame": 248,
      "shot": "medium shot",
      "movement": "smooth tracking shot",
      "speed": "moderate",
      "strength": 0.45
    }
  ]
}
```

Create one controller node per R2V segment and change only `segment_index`.
Each controller must receive the same full source-video frames, source audio,
and video info. Connect each segment's frames/audio to its matching R2V
reference inputs. Concatenate the generated image batches in timeline order.

## Per-segment camera previews

`Camera segment preview` is enabled by default in the All-in-One timeline.
Each completed camera branch is encoded as a temporary MP4 and appears in its
matching segment card with synchronized source audio. These clips are kept out
of the normal output gallery; only the final assembled video is saved there.
Turn the preview button off when running many segments and the extra temporary
encodes are not needed.

## Limitation

The stock H3 R2V node exposes video and audio references but not a per-frame
lip-landmark tensor. This node therefore enforces lip timing through matching
video/audio references, an explicit prompt lock, and exact segment timing. It
does not claim pixel-perfect mouth landmark enforcement. A later hard-control
extension can add face/lip landmark verification and reject/retry logic without
changing the source-audio path.
