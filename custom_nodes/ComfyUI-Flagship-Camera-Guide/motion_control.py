"""Source eligibility and prompts for image-conditioned camera movement."""
import json
import numpy as np
import torch
from .orbit_control import quiet_orbit_policy
from .speech_prompt import source_speech
from .foreground_motion import foreground_change


def wide_policy(targets,face_transform,images):
    n=targets['frames'];counts=np.asarray(targets.get('people_count',[]))
    if n!=124:return False,'wide plate tested on 124 source frames only',None
    if len(counts)!=n or np.mean(counts==1)<.98 or np.any(counts>1):return False,'ambiguous source performer',None
    if not face_transform['detected'][0] or not np.isfinite(targets['person_boxes'][0]).all():return False,'opening performer position unavailable',None
    joints=np.asarray(targets.get('joints',[]),float)
    if joints.shape!=(n,17,3) or np.min(joints[0,[9,10,11,12,13,14,15,16],2])<.4:
        return False,'wide source must show the complete performer; no invented missing limbs',None
    frames=images[::max(1,n//16),...,:3].float();b=max(2,round(min(frames.shape[1:3])*.02));k=len(frames)
    border=torch.cat([frames[:,:b].reshape(k,-1,3),frames[:,-b:].reshape(k,-1,3),
                      frames[:,b:-b,:b].reshape(k,-1,3),frames[:,b:-b,-b:].reshape(k,-1,3)],dim=1)
    delta=float((border-border.median(dim=0).values[None]).abs().mean())
    if delta>.035:return False,'moving source background; keep original camera route',delta
    return True,'static source border; retain original live foreground in a generated wide plate',delta


DIRECTIONS={
    'aerial pullback':'Start at the source image. Continuously crane upward and physically pull back with large amplitude, revealing substantially more of the same room and floor. Finish at a high downward-looking aerial view with the performer about one quarter of frame height. This is camera translation with a natural lens, not a cut or a zoom in.',
    'hero cam':'Start from the source image and smoothly descend to a low heroic viewpoint while traveling horizontally around the stationary performer toward the left side, completing about a 70-degree arc. Keep physical world orientation fixed. Reveal the other wall and changing room parallax; never replace camera travel with the performer turning in place.',
    'extreme wide shot':'Start at the source image and physically pull the camera straight backward by a large distance. Reveal a coherent extreme-wide establishing view of the same connected room, walls, doorway, ceiling and substantial floor. End with the performer about one quarter of frame height. Keep a fixed natural lens and level horizon; do not recenter or scale the performer back up.',
}


def motion_prompt(mode,speech,refine=False):
    if speech:
        text=' '.join(speech['text'].split()).replace('<','〈').replace('>','〉')
        line=f"Say exactly once to <Audio 1>: <d>[{speech['language_name']}] {text}</d>. Match visible lips to the waveform and retain natural occlusion."
    else:line='Keep the performer quiet with no invented dialogue.'
    closing='<Picture 2> is the exact closing camera view of [Shot 1], in the same coherent room.\n' if refine else ''
    timing='Follow the ordered camera-view anchors at 1.292, 2.583 and 3.875 seconds, then arrive exactly at <Picture 2> at 5.167 seconds. Do not continue beyond that final viewpoint. The camera guide alone is redistributed; source speech keeps its original clock.' if refine else ''
    return f'''camera motion,
subject_definitions:
<Subject 1> (S1) is the same adult performer in <Picture 1>, retaining exact identity, hair, clothing, physique, held props and quiet pose.
<Picture 1> is the exact opening frame of [Shot 1], defining the original room and lighting.
{closing.rstrip()}
<Audio 1> is the original soundtrack at its original timing.

summary:
[keyframe completion + audio reuse] One continuous cinematic camera move around the same performer following the path below.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - identity, clothing, held props and world orientation.
<Picture 1> ([Shot 1] opening frame): fully_preserved - exact opening view and room structure.
<Audio 1>: fully_copy - original waveform and timing.

detailed_description:
Photorealistic room with coherent rigid geometry, fixed light, stable body proportions and upright walls.
[Shot 1] During 0.0–5.167 seconds: {DIRECTIONS[mode]} Begin camera travel immediately, without an opening hold. {timing} Keep small natural gestures and blinking. {line} No new speaker, body spin, paper-card rotation, abrupt perspective jump, rolling horizon, morphing, cuts or unrelated room. Camera travel does not change the soundtrack clock.

overall_soundscape:
Copy only <Audio 1>; add no sound.

non_diegetic_music:
N/A'''


class FlagshipCameraMotionEligibility:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'targets':('FLAGSHIP_CAMERA_TARGETS',),'face_transform':('H3FACEXFORM',),'images':('IMAGE',),
            'audio':('AUDIO',),'mode':(list(DIRECTIONS),)}}
    RETURN_TYPES=('BOOLEAN','STRING','STRING','STRING')
    RETURN_NAMES=('use_motion','report','prompt','refine_prompt')
    FUNCTION='check'
    CATEGORY='Flagship/Camera'

    def check(self,targets,face_transform,images,audio,mode):
        if targets['frames']!=len(images) or face_transform['frames']!=len(images) or tuple(targets['src_size'])!=(images.shape[2],images.shape[1]) or tuple(face_transform['src_size'])!=tuple(targets['src_size']):
            raise ValueError('Motion measurements must describe the same source frames')
        speech=None;foreground=None
        if mode=='extreme wide shot':enabled,reason,value=wide_policy(targets,face_transform,images)
        else:
            enabled,reason,value=quiet_orbit_policy(targets,face_transform['detected'])
            if enabled:
                foreground=foreground_change(images,targets)
                if foreground>.12:enabled,reason=False,'fast foreground/hair motion; keep original camera route'
            if enabled and float(audio['waveform'].float().square().mean().sqrt())>=10**(-45/20):
                speech,error=source_speech(audio)
                if speech is None:enabled,reason=False,error
        report=json.dumps({'use_motion':enabled,'mode':mode,'reason':reason,'source_metric':value,
                           'foreground':'original source pixels' if mode=='extreme wide shot' else 'quiet performer resynthesis','foreground_change':foreground},ensure_ascii=False)
        print('[Flagship Camera Motion] '+report)
        return enabled,report,motion_prompt(mode,speech) if enabled else '',motion_prompt(mode,speech,refine=True) if enabled and mode!='extreme wide shot' else ''
