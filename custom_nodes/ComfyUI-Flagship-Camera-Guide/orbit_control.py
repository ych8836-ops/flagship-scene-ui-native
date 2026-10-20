"""Keep a frozen-subject orbit adapter away from action and ambiguous performers."""
import json
import numpy as np
from .speech_prompt import source_speech
from .foreground_motion import foreground_change


def quiet_orbit_policy(targets, detected):
    n=targets['frames']
    if n!=124:return False,'orbit adapter tested on 124 frames only',None
    if len(detected)!=n or np.mean(detected)<.9:return False,'source face not continuously visible',None
    counts=np.asarray(targets.get('people_count',[]))
    if len(counts)!=n or np.mean(counts==1)<.98 or np.any(counts>1):return False,'source performer is ambiguous',None
    joints=np.asarray(targets['joints'],float);boxes=np.asarray(targets['person_boxes'],float)
    if joints.shape!=(n,17,3) or boxes.shape!=(n,4):return False,'incomplete source pose',None
    good=np.isfinite(boxes).all(1)
    if good.mean()<.9:return False,'insufficient source body coverage',None
    height=float(np.median((boxes[:,3]-boxes[:,1])[good]))
    if height<=0:return False,'invalid source body scale',None
    root=(joints[:,11,:2]+joints[:,12,:2])/2
    root_ok=np.isfinite(root).all(1)&(joints[:,11,2]>=.4)&(joints[:,12,2]>=.4)
    if root_ok.mean()<.85:return False,'source hips are not reliably visible',None
    ranges=[]
    for k in range(5,17):
        ok=root_ok&np.isfinite(joints[:,k]).all(1)&(joints[:,k,2]>=.4)
        if ok.mean()<.85:return False,'source limbs are not reliably visible',None
        p=(joints[ok,k,:2]-root[ok])/height
        ranges.append(float(np.linalg.norm(np.quantile(p,.98,axis=0)-np.quantile(p,.02,axis=0))))
        valid=np.flatnonzero(ok);delta=np.linalg.norm(np.diff(p,axis=0),axis=1)
        if np.any(delta[np.diff(valid)==1]>.06):return False,'fast source gesture; keep original camera route',max(ranges)
    center=(boxes[good,:2]+boxes[good,2:])/2/height
    travel=float(np.linalg.norm(np.quantile(center,.98,axis=0)-np.quantile(center,.02,axis=0)))
    motion=max(ranges+[travel])
    if motion>.08:return False,'source body motion exceeds quiet-orbit limit',motion
    return True,'single quiet performer; conditional orbit route',motion


def orbit_prompt(speech):
    if speech:
        text=' '.join(speech['text'].split()).replace('<','〈').replace('>','〉')
        delivery=f"Speak exactly once to <Audio 1>, <d>[{speech['language_name']}] {text}</d>. Articulate visible lips directly to the original waveform."
    else:delivery='Keep the scene silent; no invented dialogue or random mouth motion.'
    return f'''subject_definitions:
<Subject 1> (S1) is the same adult performer in <Picture 1>, retaining exact facial identity, hair, outfit, body proportions and held props.
<Picture 1> defines the opening and closing views of [Shot 1] and the original room.
<Audio 1> is the original soundtrack, copied with its exact timing.

summary:
[reference generation + audio reuse] ORB360_CW. One continuous clockwise 360-degree camera circuit around the same quiet performer with natural synchronized speech.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - identity, outfit, world orientation and held props.
<Picture 1> ([Shot 1] opening and closing view): fully_preserved - original camera view and surroundings.
<Audio 1>: fully_copy - original waveform and timing.

detailed_description:
Photorealistic scene with stable light and coherent rigid geometry.
[Shot 1] Begin at <Picture 1>. During 0.0–5.167 seconds the camera makes exactly one clockwise circuit at constant height and distance, keeping its lens and horizon level. Reach about 120 degrees at 1.708 seconds, 240 degrees at 3.417 seconds, then return to the opening front view at the final frame. Keep the performer's stance, hand grip and world orientation stable; camera travel produces the changing parallax and occlusion. {delivery} A hidden mouth stays naturally hidden. Keep the back of the head intact when seen from behind, without forcing a frontal face. Any existing mirror reflection belongs to this same performer and follows the same speech. No independent new person, rolling photograph, body spin, shape morphing, cuts or added objects.

overall_soundscape:
Copy only <Audio 1> with no additional sound.

non_diegetic_music:
N/A'''


class FlagshipCameraOrbitEligibility:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'targets':('FLAGSHIP_CAMERA_TARGETS',),'face_transform':('H3FACEXFORM',),'audio':('AUDIO',)},'optional':{'images':('IMAGE',)}}
    RETURN_TYPES=('BOOLEAN','STRING','STRING')
    RETURN_NAMES=('use_orbit','report','prompt')
    FUNCTION='check'
    CATEGORY='Flagship/Camera'

    def check(self,targets,face_transform,audio,images=None):
        if face_transform['frames']!=targets['frames'] or tuple(face_transform['src_size'])!=tuple(targets['src_size']):
            raise ValueError('Orbit measurements and face tracking must describe the same source')
        enabled,reason,motion=quiet_orbit_policy(targets,face_transform['detected'])
        foreground=None
        if enabled and images is not None:
            if len(images)!=targets['frames'] or tuple(images.shape[1:3])!=tuple(reversed(targets['src_size'])):raise ValueError('Source foreground motion frames do not match the body measurements')
            foreground=foreground_change(images,targets)
            if foreground>.12:enabled,reason=False,'fast foreground/hair motion; keep original camera route'
        speech=None
        if enabled and float(audio['waveform'].float().square().mean().sqrt())>=10**(-45/20):
            speech,error=source_speech(audio)
            if speech is None:enabled,reason=False,error
        report=json.dumps({'use_orbit':enabled,'reason':reason,'source_body_motion':motion,'body_motion_limit':.08,
                           'frames':targets['frames'],'foreground_change':foreground,'foreground_change_limit':.12,'adapter_steps':12 if enabled else None},ensure_ascii=False)
        print('[Flagship Camera Orbit] '+report)
        return enabled,report,orbit_prompt(speech) if enabled else ''
