# MiniMax H3 R2V Camera + Lip Lock Prompt Rules

These rules are generated into every segment prompt. Keep them intact when
adding a scene-specific camera instruction.

## Reference labels

For each controller segment, the paired references are presented to H3 as:

- `<Audio 1>`: the exact source-audio segment used for mouth timing
- `<Video 1>`: the matching source-video frames used for identity and motion

Use those labels exactly. Do not introduce `<Picture 1>` unless an actual still
image is connected to the R2V node.

## Camera control rules

1. Assign one camera shot and one camera movement per segment.
2. State movement speed and strength explicitly.
3. Keep the segment as one continuous shot; prohibit unrequested cuts,
   sudden zooms, lens warping, and reframing.
4. Camera changes are allowed between segments, but identity, wardrobe, scene
   geometry, lighting, and performance continuity must remain fixed.
5. Use local segment time. Never write accumulated chain time in a segment
   prompt.

## Lip-sync hard-lock rules

Insert this block in every segment:

```text
Lip-sync hard lock: reproduce the visible speaker's exact mouth-opening and
closing rhythm, jaw movement, articulation timing, pauses, and expression
transitions from <Video 1> and <Audio 1>. Do not invent new phonemes, speech
timing, lyrics, mouth poses, or silent intervals. Keep the same speaking or
singing cadence frame by frame.
```

The source video is the visual mouth reference. The source audio is the timing
and phonetic reference. The final soundtrack is still copied from the original
source audio outside the diffusion generation step.

## Continuity rules

```text
Use <Video 1> as the exact identity, scene, temporal, and performance anchor.
Only the requested camera framing and movement may change. Preserve the same
face proportions, hairstyle, wardrobe, body proportions, lighting, and scene
geometry. Do not add a new speaker or change the speaker's vocal timing.
```

## Audio rules

```text
Use <Audio 1> to drive the generated mouth motion, but do not generate or
replace the final soundtrack. The final video must mux the untouched original
source audio returned by the controller node.
```

## Forbidden prompt patterns

- Do not say `new music`, `new dialogue`, `new voice`, or `generate a soundtrack`.
- Do not ask H3 to improvise lyrics, phonemes, pauses, or speech timing.
- Do not describe a future segment's camera move inside the current segment.
- Do not change camera and wardrobe in the same segment unless explicitly
  requested.
- Do not use the generated H3 audio decode as the final audio when source
  audio must be exact.

## Recommended per-segment template

```text
R2V segment N, source frames START-END, DURATION seconds at FPS fps.
Reference order: <Audio 1> is the synchronized source-audio segment;
<Video 1> is the matching source-video segment.

Use <Video 1> as the exact identity, scene, temporal, and performance anchor.
Camera instruction: SHOT; MOVEMENT; SPEED speed; controlled movement strength STRENGTH.
Keep one continuous shot and avoid cuts, lens warping, sudden zooms, or
unmotivated reframing.

Lip-sync hard lock: reproduce the visible speaker's exact mouth-opening and
closing rhythm, jaw movement, articulation timing, pauses, and expression
transitions from <Video 1> and <Audio 1>. Do not invent new phonemes, speech
timing, lyrics, mouth poses, or silent intervals. Keep the same speaking or
singing cadence frame by frame.

Audio policy: use <Audio 1> to drive the generated mouth motion, but do not
generate or replace the final soundtrack. The final video must mux the
untouched original source audio.
```
