export function topdownDepthPrompt(seconds){return `subject_definitions:
<Subject 1> is the same adult performer. <Picture 1> preserves facial identity. <Picture 2> preserves the exact hair, clothing, physique, held phone and scene materials; its frontal camera perspective must be replaced. <Audio 1> is the original synchronized soundtrack.

summary:
[reference generation + audio reuse] Rephotograph the performance as a true straight-down overhead shot. The animated depth-control video defines the new camera geometry and original body motion.

retention_analysis:
<Subject 1>: fully_preserved - retain identity, hair, wardrobe, proportions and original held objects.
<Picture 2>: partially_preserved - preserve appearance and materials; completely replace its frontal viewpoint.
<Audio 1>: fully_copy - preserve waveform and original timing.

detailed_description:
[Shot 1] One continuous ${Number(seconds).toFixed(3)}-second shot. A fixed camera directly above the performer looks vertically downward at the floor. Match the animated depth control precisely. Center the top surface of the hair and the upper shoulders. The face is hidden under the top of the head; do not tilt the face up toward the camera. The torso and legs are mostly occluded directly beneath the head and shoulders, with small visible clothing and feet where physically appropriate. Do not reproduce a front-facing full-height portrait. The camera remains still throughout. Follow the source body and hand motion carried in the depth guide, with natural breathing and small secondary hair/clothing motion. The phone stays in its original hand. If the mouth is visible, articulate only to <Audio 1>. Show exactly one real performer on an opaque matte floor. No new accessories, duplicate performers, mirrored body copies, reflective floor panels, geometric folds, cuts, or frozen photographs. Keep skin, hair and cloth photorealistic.

overall_soundscape:
Copy <Audio 1> without retiming. No added speech, narration or sound.

non_diegetic_music:
Keep only music already present in <Audio 1>.`;}
