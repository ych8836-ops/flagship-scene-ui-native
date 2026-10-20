import {numericCameraPrompt} from './multiangle_math.js?v=precise_angles_20261017_v2';
// Original H3 directions, informed by cinematography and the public camera-controls catalog.
const entries=rows=>rows.map(([value,label,group,direction,kind='move'])=>({value,label,group,direction,kind}));
export const SHOTS=entries([
    ['source framing','원본 거리 유지','프레이밍','retain the source subject scale while allowing the selected viewpoint'],
    ['extreme wide shot','익스트림 와이드','프레이밍','a very distant establishing frame where the environment dominates'],
    ['wide shot','와이드','프레이밍','a wide composition showing the complete performer and surrounding space'],
    ['full body shot','전신','프레이밍','the entire performer from head to feet with breathing room'],
    ['medium wide shot','니 샷','프레이밍','a knees-up composition with readable body gestures'],
    ['medium shot','미디엄','프레이밍','a waist-up composition with natural headroom'],
    ['medium close-up','상반신','프레이밍','a chest-up composition with a clearly readable face'],
    ['close-up','클로즈업','프레이밍','a tight face-and-shoulders composition'],
    ['extreme close-up','익스트림 클로즈업','프레이밍','a tight facial detail composition without changing facial anatomy'],
    ['insert shot','디테일·인서트','프레이밍','a close detail of an existing hand-held prop or hand action in the source scene'],
    ['macro shot','매크로','프레이밍','a macro-scale view of an existing small surface or object detail'],
]);
export const ANGLES=entries([
    ['source angle','원본 시점 유지','방향','start with the source camera orientation'],
    ['eye level','눈높이 정면','방향','an eye-level frontal camera position'],
    ['front left three-quarter','좌측 45도','방향','a front-left three-quarter viewpoint about 45 degrees from frontal'],
    ['front right three-quarter','우측 45도','방향','a front-right three-quarter viewpoint about 45 degrees from frontal'],
    ['left side profile','왼쪽 측면','방향','a strict left profile about 90 degrees from frontal'],
    ['right side profile','오른쪽 측면','방향','a strict right profile about 90 degrees from frontal'],
    ['rear view','후면','방향','a camera behind the performer; keep the face naturally out of view'],
    ['over-the-shoulder','어깨 너머','방향','a viewpoint behind an existing foreground shoulder looking toward the original scene'],
    ['first-person POV','1인칭 시점','방향','the viewpoint of an existing participant looking into the same scene'],
    ['object POV','물체 시점','방향','a camera attached to an existing object looking outward into the scene'],
    ['low angle','로우 앵글','높이·기울기','a camera below eye level looking upward'],
    ['high angle','하이 앵글','높이·기울기','an elevated camera looking downward'],
    ['top-down overhead view','수직 탑뷰','높이·기울기','a vertically downward camera directly above the performer'],
    ['bird-eye view','버드아이','높이·기울기','a distant elevated oblique view revealing the scene layout'],
    ['worm-eye view','웜아이','높이·기울기','a ground-level camera looking steeply upward'],
    ['ground level','지면 시점','높이·기울기','a camera just above the floor looking along the ground plane'],
    ['dutch angle','더치 앵글','높이·기울기','a deliberately canted horizon while preserving stable subject anatomy'],
]);
export const MOVES=entries([
    ['static camera','고정','기본','hold camera translation, rotation and focal length fixed','locked'],
    ['slow pan left','팬 ←','기본','rotate the camera left about a fixed camera position'],
    ['slow pan right','팬 →','기본','rotate the camera right about a fixed camera position'],
    ['slow tilt up','틸트 ↑','기본','rotate the camera upward about a fixed camera position'],
    ['slow tilt down','틸트 ↓','기본','rotate the camera downward about a fixed camera position'],
    ['slow dolly in','돌리 인','기본','translate the camera toward the performer, producing real foreground-background parallax'],
    ['slow dolly out','돌리 아웃','기본','translate the camera away from the performer, widening the visible surroundings'],
    ['dolly left','돌리 ←','기본','translate the camera left on a lateral track while keeping its viewing direction stable'],
    ['dolly right','돌리 →','기본','translate the camera right on a lateral track while keeping its viewing direction stable'],
    ['smooth tracking shot','평행 트래킹','기본','follow the original performer motion on a smooth lateral track'],
    ['crane up','크레인 상승','상승·하강','raise the camera substantially, gradually revealing the surrounding layout'],
    ['crane down','크레인 하강','상승·하강','lower the camera from an elevated viewpoint toward the performer'],
    ['crane over the head','머리 위 크레인','상승·하강','rise above the performer and travel over the head with a continuous overhead reveal'],
    ['jib up','지브 상승','상승·하강','lift the camera on a short smooth boom arc while keeping the performer framed'],
    ['jib down','지브 하강','상승·하강','lower the camera on a short smooth boom arc while keeping the performer framed'],
    ['aerial pullback','항공 풀백','상승·하강','move backward and upward together to reveal an aerial view of the same location'],
    ['smooth orbit left','좌측 오빗','회전·아크','circle around the performer to the left at approximately constant distance'],
    ['arc left','좌측 아크','회전·아크','follow a short leftward curved path of roughly a quarter circle'],
    ['arc right','우측 아크','회전·아크','follow a short rightward curved path of roughly a quarter circle'],
    ['lazy susan','제품 중심 회전','회전·아크','circle the camera around an existing foreground object while that object stays in place'],
    ['camera roll clockwise','시계 롤 회전','회전·아크','roll the camera clockwise around the optical axis; the scene and performer do not rotate'],
    ['camera roll counterclockwise','반시계 롤 회전','회전·아크','roll the camera counterclockwise around the optical axis; the scene and performer do not rotate'],
    ['zoom in','광학 줌 인','줌','increase focal length from a stationary camera position','zoom'],
    ['zoom out','광학 줌 아웃','줌','decrease focal length from a stationary camera position','zoom'],
    ['rapid zoom in','래피드 줌 인','줌','make one brisk optical zoom inward, then settle without a cut','impulse'],
    ['rapid zoom out','래피드 줌 아웃','줌','make one brisk optical zoom outward, then settle without a cut','impulse'],
    ['crash zoom in','크래시 줌 인','줌','make one abrupt optical punch-in toward the existing performer, then hold','impulse'],
    ['crash zoom out','크래시 줌 아웃','줌','make one abrupt optical pull-out, then hold the wider frame','impulse'],
    ['dolly zoom in','돌리 줌 인','줌','move the camera forward while widening the lens, keeping subject size approximately constant as background perspective expands','dollyzoom'],
    ['dolly zoom out','돌리 줌 아웃','줌','move the camera backward while narrowing the lens, keeping subject size approximately constant as background perspective compresses','dollyzoom'],
    ['super dolly in','롱레인지 돌리 인','줌','make a long continuous physical push toward the performer with substantial parallax','complex'],
    ['super dolly out','롱레인지 돌리 아웃','줌','make a long continuous physical pullback revealing more of the same environment','complex'],
    ['yoyo zoom','요요 줌','줌','optically zoom inward in the first half and return to the initial focal length in the second half; keep camera position fixed','zoom'],
    ['subtle handheld','핸드헬드','추적·리그','add restrained irregular camera drift and small operator corrections'],
    ['head tracking','헤드 트래킹','추적·리그','follow the original head movement, keeping the head near the same screen position'],
    ['snorricam','스노리캠','추적·리그','use a body-mounted camera moving with the original performer; body position stays steady in frame while the environment reacts to the original steps','complex'],
    ['car grip','차량 고정 리그','추적·리그','mount the camera rigidly to an existing source vehicle, preserving its original motion; invent no vehicle'],
    ['car chasing','차량 추적','추적·리그','follow an existing moving source vehicle from a trailing camera, preserving its original route; invent no vehicle','complex'],
    ['robo arm','로봇암','추적·리그','execute a precisely controlled short compound arc and height change around the existing subject'],
    ['wiggle','미세 위글','추적·리그','add a small rhythmic left-right camera wobble without deforming the scene'],
    ['FPV drone','FPV 드론','공간 이동 · 실험','fly a banked camera path through existing open space toward and around the performer','complex'],
    ['flying cam transition','플라잉 카메라','공간 이동 · 실험','make one continuous flight from an overview toward a closer view within the same location','complex'],
    ['through object in','개구부 통과 인','공간 이동 · 실험','travel inward through an existing doorway or opening toward the subject; do not pass through solid material','complex'],
    ['through object out','개구부 통과 아웃','공간 이동 · 실험','travel outward through an existing doorway or opening to reveal the surrounding space; do not pass through solid material','complex'],
    ['whip pan left','휩팬 ←','공간 이동 · 실험','make one quick leftward camera pan and settle on the same scene without an edit','impulse'],
    ['whip pan right','휩팬 →','공간 이동 · 실험','make one quick rightward camera pan and settle on the same scene without an edit','impulse'],
]);
export const LENSES=entries([
    ['natural','자연 렌즈','렌즈','natural perspective appropriate to the requested framing'],
    ['14mm','14mm 초광각','렌즈','an initial 14mm-equivalent ultra-wide lens with strong near-far separation'],
    ['24mm','24mm 광각','렌즈','an initial 24mm-equivalent wide lens'],
    ['35mm','35mm','렌즈','an initial 35mm-equivalent environmental portrait lens'],
    ['50mm','50mm 표준','렌즈','an initial 50mm-equivalent normal lens'],
    ['85mm','85mm 인물','렌즈','an initial 85mm-equivalent portrait lens with compressed perspective'],
    ['135mm','135mm 망원','렌즈','an initial 135mm-equivalent telephoto lens with strongly compressed depth'],
    ['fisheye','피시아이','렌즈','an initial fisheye lens with deliberate optical barrel curvature, without anatomical deformation'],
]);
export const FOCUS=entries([
    ['source','원본 초점','초점','preserve the source focus intent'],
    ['face','인물 초점','초점','keep any visible principal face in focus; use natural focus breathing only'],
    ['deep','딥 포커스','초점','keep subject and environment legible with deep focus'],
    ['shallow','얕은 심도','초점','keep the subject sharp with optical background separation'],
    ['near to far','전경 → 후경','초점','rack focus once from an existing near subject to an existing distant subject without inventing objects'],
    ['far to near','후경 → 전경','초점','rack focus once from an existing distant subject to an existing near subject without inventing objects'],
]);
export const SPEEDS=[['very slow','아주 느리게'],['slow','느리게'],['moderate','보통'],['fast','빠르게'],['very fast','아주 빠르게']];
export const EASINGS=entries([
    ['linear','일정 속도','가감속','maintain a steady camera travel rate'],
    ['ease in','서서히 가속','가감속','start camera travel gently and accelerate'],
    ['ease out','서서히 감속','가감속','decelerate the camera into a settled ending'],
    ['ease in out','부드러운 시작·끝','가감속','ease camera travel in at the beginning and out at the end'],
    ['snap settle','빠른 이동·정착','가감속','make the main camera displacement early, then hold the final view'],
]);
export const REMOVED_MOVES=[['360 orbit clockwise','360도 시계 오빗'],['360 orbit counterclockwise','360도 반시계 오빗'],['hero cam','히어로 아크'],['smooth orbit right','우측 오빗']];
export function validateCameraSegments(segments){
    for(const [index,part] of segments.entries()){
        if(part.multi_angle?.enabled===true)continue;
        const removed=REMOVED_MOVES.find(([value])=>value===part.movement);
        if(removed)throw Error(`카메라 구간 ${index+1}: ${removed[1]}은 제거된 모드입니다. 무빙에서 다른 모드를 선택하세요.`);
    }
}
const find=(list,value)=>list.find(item=>item.value===value);
export function normalizeCameraSegment(part){
    const legacy=find(ANGLES,part.shot);
    if(legacy&&part.angle===undefined){part.angle=part.shot;part.shot='source framing';}
    part.angle??='source angle';part.lens??='natural';part.focus??='source';part.easing??='linear';
    return part;
}
export function cameraDirectionPrompt(segment,count){
    validateCameraSegments([segment]);
    if(segment.multi_angle?.enabled===true)return numericCameraPrompt(segment.multi_angle,count);
    const part=normalizeCameraSegment({...segment});
    const shot=find(SHOTS,part.shot),angle=find(ANGLES,part.angle),move=find(MOVES,part.movement),lens=find(LENSES,part.lens),focus=find(FOCUS,part.focus),ease=find(EASINGS,part.easing);
    const amount=Number(part.strength??.35);
    if(!Number.isFinite(amount)||amount<0||amount>1)throw Error('카메라 강도는 0~1이어야 합니다.');
    const locked=move?.kind==='locked'||amount===0;
    const optical=!locked&&['zoom','impulse'].includes(move?.kind)&&/zoom/.test(part.movement);
    const dollyZoom=!locked&&move?.kind==='dollyzoom';
    const rotation=!locked&&/pan|tilt|roll/.test(part.movement||'');
    const timing=move?.kind==='impulse'?`Make the named rapid movement once, then settle; the ${part.speed||'slow'} pacing setting governs the surrounding hold and settling time.`:`Camera travel pace: ${part.speed||'slow'}. ${ease?.direction||'maintain a steady camera travel rate'}.`;
    const motion=locked?'Hold camera translation, rotation and focal length fixed.':`${move?.direction||part.movement||'hold the camera fixed'}. ${timing} Movement amplitude: ${amount.toFixed(2)} on a zero-to-one scale.`;
    const geometry=locked?'Keep the camera stationary and spatial relationships stable.':optical?'Keep the optical center stationary. Change focal length for the requested zoom; do not translate the camera or warp body geometry.':dollyZoom?'Coordinate physical dolly travel and opposite optical zoom. Keep subject scale stable while changing background perspective.':rotation?'Rotate the camera around its fixed optical center. Preserve the rigid environment and natural rotational perspective.':'Generate coherent perspective, parallax and occlusion for the requested physical camera path. Do not substitute independent background sliding or an arbitrary digital crop.';
    return `subject_definitions:
<Subject 1> is the original principal performer, retaining facial identity, hair, wardrobe and body proportions.
<Video 1> defines the existing environment and exact performance timeline.
<Audio 1> is the original synchronized soundtrack and must be copied at its original timing.

summary:
[reference generation + audio reuse] Rephotograph the source performance using the following explicit camera plan.

retention_analysis:
<Subject 1>: fully_preserved - retain identity and performance.
<Video 1>: partially_preserved - retain cast, setting and action timing while applying the selected cinematography.
<Audio 1>: fully_copy - retain the original waveform and timing.

detailed_description:
[Shot 1] One continuous ${(count/24).toFixed(3)}-second shot. Begin immediately in the requested composition.
FRAMING: ${shot?.direction||part.shot||'a waist-up composition'}.
STARTING VIEWPOINT: ${angle?.direction||part.angle}. Allow the viewpoint to evolve only along the selected camera path.
LENS: ${lens?.direction||part.lens}. ${optical||dollyZoom?'Change focal length only as required by the selected zoom.':'Maintain this lens perspective throughout the shot.'}
CAMERA PATH: ${motion}
FOCUS: ${focus?.direction||part.focus}.
${geometry} Apply the requested lens behavior without morphing anatomy.
Camera speed and easing affect only the camera. Preserve source performance speed, action order, vocal timing and elapsed time. Do not freeze, loop, reverse, accelerate or slow the performer. Preserve existing cast, vehicles, props and spatial relationships; create no new participant or vehicle. Keep lighting consistent and newly revealed surfaces plausible. Follow the requested side, rear or overhead visibility instead of forcing a frontal face. If the mouth is visible, articulate directly to <Audio 1>; if occluded, keep it occluded. Avoid cuts, dissolves, duplicated bodies, independent background warping and anatomy drift.

overall_soundscape:
Copy the existing dialogue, ambience and effects from <Audio 1>. Add no speech or sounds.

non_diegetic_music:
Keep only music already present in <Audio 1>.`;
}

export function applyCameraDirections(graph,segments){
    for(const node of Object.values(graph)){
        if(node.class_type!=='MiniMaxH3ReferenceToVideo')continue;
        const prep=graph[node.inputs['ref_videos.ref_video_0']?.[0]];
        if(prep?.class_type!=='H3R2VCameraLipLock')continue;
        const index=prep.inputs.segment_index,part=segments[index];
        if(!part)throw Error(`카메라 ${index+1}구간 설정이 없습니다.`);
        const start=part.start_seconds===undefined?part.start_frame:Math.round(part.start_seconds*24);
        const end=part.end_seconds===undefined?part.end_frame:Math.round(part.end_seconds*24);
        node.inputs.prompt=cameraDirectionPrompt(part,end-start);
    }
    return graph;
}
