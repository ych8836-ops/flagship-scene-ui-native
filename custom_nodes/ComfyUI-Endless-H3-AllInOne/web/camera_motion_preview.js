import {CameraStageRenderer} from './camera_character_renderer.js?v=lowpoly_20261017';
import {SHOTS,ANGLES,MOVES,LENSES,FOCUS,SPEEDS,EASINGS} from './camera_controls.js?v=pruned_camera_20261017_v1';

// These procedural illustrations explain controls; they never touch the source or queue.
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
const mix=(a,b,t)=>a+(b-a)*t;
const V=(x,y,z)=>({x,y,z});
const sub=(a,b)=>V(a.x-b.x,a.y-b.y,a.z-b.z);
const dot=(a,b)=>a.x*b.x+a.y*b.y+a.z*b.z;
const cross=(a,b)=>V(a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x);
const unit=a=>{const n=Math.hypot(a.x,a.y,a.z)||1;return V(a.x/n,a.y/n,a.z/n);};
const catalogs={shot:SHOTS,angle:ANGLES,movement:MOVES,lens:LENSES,focus:FOCUS,speed:SPEEDS.map(([value,label])=>({value,label})),easing:EASINGS};
const explanations={
    shot:[
        '원본 영상의 인물 크기를 기준으로 구도를 유지합니다.',
        '인물을 아주 작게 담아 장소와 공간의 규모를 보여줍니다.',
        '인물 전체와 주변 공간을 함께 담습니다.',
        '머리부터 발끝까지 전신을 담습니다.',
        '무릎 위부터 담아 몸짓과 표정을 함께 보여줍니다.',
        '허리 위를 담아 대화와 상체 연기를 보여줍니다.',
        '가슴 위를 담아 표정에 집중합니다.',
        '얼굴과 어깨를 크게 담습니다.',
        '눈과 같은 얼굴의 세부를 아주 크게 담습니다.',
        '장면 안에 있는 손이나 소품의 세부를 강조합니다.',
        '기존 소품의 표면처럼 아주 작은 부분을 확대합니다.',
    ],
    angle:[
        '원본 영상의 카메라 방향을 기준으로 유지합니다.',
        '인물 눈높이에서 정면을 바라봅니다.',
        '인물의 왼쪽 앞 45도에서 바라봅니다.',
        '인물의 오른쪽 앞 45도에서 바라봅니다.',
        '인물의 왼쪽 옆모습을 바라봅니다.',
        '인물의 오른쪽 옆모습을 바라봅니다.',
        '인물 뒤에서 바라보므로 얼굴은 자연스럽게 가려집니다.',
        '앞 인물의 어깨 너머로 상대나 장면을 바라봅니다.',
        '인물이 직접 바라보는 듯한 1인칭 구도입니다.',
        '장면 속 물체에 카메라를 붙인 듯한 시점입니다.',
        '낮은 위치에서 위를 올려다봐 인물을 강조합니다.',
        '높은 위치에서 아래를 내려다봅니다.',
        '인물 바로 위에서 수직으로 내려다봅니다.',
        '높고 먼 사선 위에서 장소 전체를 조망합니다.',
        '바닥 가까이에서 가파르게 올려다봅니다.',
        '바닥 높이에서 지면을 따라 바라봅니다.',
        '카메라를 옆으로 기울여 수평선을 비스듬하게 만듭니다.',
    ],
    movement:[
        '카메라의 위치·방향·줌을 고정합니다.',
        '카메라는 제자리에 두고 왼쪽으로 고개를 돌립니다.',
        '카메라는 제자리에 두고 오른쪽으로 고개를 돌립니다.',
        '카메라는 제자리에 두고 위로 올려다봅니다.',
        '카메라는 제자리에 두고 아래로 내려다봅니다.',
        '카메라가 인물에게 다가갑니다. 앞뒤 물체의 원근도 함께 변합니다.',
        '카메라가 뒤로 물러납니다. 주변 공간이 점차 넓게 드러납니다.',
        '카메라가 왼쪽으로 평행 이동합니다. 가까운 물체가 더 크게 움직입니다.',
        '카메라가 오른쪽으로 평행 이동합니다. 가까운 물체가 더 크게 움직입니다.',
        '움직이는 인물을 따라 옆으로 나란히 이동합니다.',
        '카메라가 높이 올라가며 주변 배치를 드러냅니다.',
        '높은 곳에서 인물을 향해 카메라가 내려옵니다.',
        '카메라가 인물 머리 위를 넘어 반대편으로 이동합니다.',
        '짧은 붐의 곡선을 따라 부드럽게 올라갑니다.',
        '짧은 붐의 곡선을 따라 부드럽게 내려옵니다.',
        '뒤로 멀어지면서 동시에 상승해 넓은 공간을 보여줍니다.',
        '인물과의 거리를 유지하며 왼쪽으로 돌아갑니다.',
        '인물과의 거리를 유지하며 오른쪽으로 돌아갑니다.',
        '인물 중심으로 왼쪽의 짧은 곡선 경로를 이동합니다.',
        '인물 중심으로 오른쪽의 짧은 곡선 경로를 이동합니다.',
        '인물을 중심으로 시계 방향으로 한 바퀴 돕니다.',
        '인물을 중심으로 반시계 방향으로 한 바퀴 돕니다.',
        '낮은 앵글에서 인물 주위를 돌며 조금 상승합니다.',
        '기존 소품은 그대로 두고 카메라가 그 주변을 돕니다.',
        '카메라 광축을 기준으로 시계 방향으로 기울입니다.',
        '카메라 광축을 기준으로 반시계 방향으로 기울입니다.',
        '카메라는 제자리에서 렌즈 초점거리를 늘려 확대합니다.',
        '카메라는 제자리에서 렌즈 초점거리를 줄여 축소합니다.',
        '제자리에서 빠르게 확대하고 멈춥니다.',
        '제자리에서 빠르게 축소하고 멈춥니다.',
        '아주 짧고 급격하게 확대해 시선을 집중시킵니다.',
        '아주 짧고 급격하게 축소해 주변을 드러냅니다.',
        '다가가면서 줌 아웃합니다. 인물 크기를 유지하며 배경 원근이 벌어집니다.',
        '물러나면서 줌 인합니다. 인물 크기를 유지하며 배경 원근이 압축됩니다.',
        '먼 거리에서 인물 가까이까지 크게 전진합니다.',
        '인물 가까이에서 먼 거리까지 크게 후퇴합니다.',
        '제자리에서 확대했다가 원래 배율로 돌아옵니다.',
        '손으로 든 카메라처럼 작고 불규칙한 흔들림을 더합니다.',
        '원본의 머리 움직임을 따라가 얼굴을 화면에 유지합니다.',
        '몸에 장착한 카메라처럼 인물은 안정되고 배경이 움직입니다.',
        '기존 차량에 고정한 카메라처럼 차량과 함께 이동합니다.',
        '기존 차량의 뒤를 따라가며 이동합니다.',
        '정밀한 로봇암처럼 회전과 높이 변화를 함께 수행합니다.',
        '좌우로 작고 규칙적인 카메라 흔들림을 더합니다.',
        '드론처럼 기울어지며 공간 안으로 날아갑니다.',
        '높은 전경에서 인물 가까이까지 연속 비행합니다.',
        '기존 문이나 열린 틈을 지나 안쪽으로 전진합니다.',
        '기존 문이나 열린 틈을 지나 바깥쪽으로 후퇴합니다.',
        '제자리에서 왼쪽으로 급히 돌린 뒤 멈춥니다.',
        '제자리에서 오른쪽으로 급히 돌린 뒤 멈춥니다.',
    ],
    lens:[
        '장면과 구도에 맞는 자연스러운 원근을 사용합니다.',
        '아주 넓은 화각으로 가까운 것과 먼 것의 거리 차를 강조합니다.',
        '넓은 화각으로 인물과 주변 환경을 함께 담습니다.',
        '적당히 넓은 화각으로 인물과 장소의 관계를 보여줍니다.',
        '과한 원근 없이 자연스러운 표준 화각을 사용합니다.',
        '인물에 집중하며 배경이 더 가까워 보이게 합니다.',
        '먼 거리에서 당겨 담아 배경 원근을 강하게 압축합니다.',
        '가장자리 직선이 휘어 보이는 어안 렌즈 효과입니다.',
    ],
    focus:[
        '원본 영상의 초점 의도를 유지합니다.',
        '주요 인물의 얼굴이 선명하게 보이도록 초점을 유지합니다.',
        '인물과 가까운 소품, 먼 배경을 함께 선명하게 보여줍니다.',
        '인물은 선명하게 두고 배경을 부드럽게 흐립니다.',
        '가까운 소품에서 먼 배경으로 선명한 영역을 옮깁니다.',
        '먼 배경에서 가까운 소품으로 선명한 영역을 옮깁니다.',
    ],
    speed:[
        '같은 경로를 아주 천천히 이동합니다. 인물·대사 속도는 바꾸지 않습니다.',
        '같은 경로를 느리게 이동합니다. 인물·대사 속도는 바꾸지 않습니다.',
        '같은 경로를 보통 속도로 이동합니다. 인물·대사 속도는 바꾸지 않습니다.',
        '같은 경로를 빠르게 이동하고 멈춥니다. 인물·대사 속도는 바꾸지 않습니다.',
        '같은 경로를 아주 빠르게 이동하고 멈춥니다. 인물·대사 속도는 바꾸지 않습니다.',
    ],
    easing:[
        '처음부터 끝까지 일정한 속도로 이동합니다.',
        '처음에는 천천히 출발하고 점차 빨라집니다.',
        '빠르게 출발한 뒤 끝에 가까워질수록 느려집니다.',
        '천천히 출발하고 중간에 빨라졌다가 부드럽게 멈춥니다.',
        '빠르게 목표 구도에 도달한 뒤 안정적으로 멈춥니다.',
    ],
};
export function cameraGuide(key,value){
    if(key==='strength')return {label:`모션 강도 · ${Number(value).toFixed(2)}`,value:String(value),description:'값이 커질수록 카메라 이동·회전의 폭이 커집니다. 0이면 카메라를 고정합니다. 360도 오빗은 한 바퀴 회전을 유지합니다.'};
    const index=catalogs[key]?.findIndex(item=>item.value===value)??-1,item=catalogs[key]?.[index];
    if(!item)return null;
    return {...item,description:explanations[key][index],complex:item.kind==='complex'};
}

export function cameraDemoState(key,value,time){
    let p=clamp(time/.82);const s={position:V(0,1.7,6),target:V(0,1,0),focal:1,roll:0,actor:V(0,0,0),focus:'deep',focusProgress:p,gate:false,vehicle:false};
    const orbit=(a,r=6,c=V(0,1,0))=>{s.position=V(c.x+Math.sin(a)*r,s.position.y,c.z+Math.cos(a)*r);s.target=c;};
    if(key==='speed'){p=clamp(p*({'very slow':.45,slow:.7,moderate:1,fast:1.8,'very fast':3}[value]||1));s.position.z=6-3*p;}
    if(key==='easing'){p=value==='ease in'?p*p:value==='ease out'?1-(1-p)**2:value==='ease in out'?p*p*(3-2*p):value==='snap settle'?clamp(p*4):p;s.position.z=6-3*p;}
    if(key==='strength')s.position.z=6-3*p*clamp(Number(value));
    if(key==='shot'){
        const index=SHOTS.findIndex(item=>item.value===value),distances=[6,17,10,6,4.8,3.7,2.7,1.8,.85,2.5,1.35];
        s.position.z=distances[index]||6;s.target.y=index>=6&&index<9?1.68:index>=9?.8:index===5?1.35:1;
        if(index>=9){s.target.x=1.15;s.target.z=.4;s.position.x=1.15;}
    }
    if(key==='angle'){
        const az={'front left three-quarter':-.785,'front right three-quarter':.785,'left side profile':-Math.PI/2,'right side profile':Math.PI/2,'rear view':Math.PI};
        if(value in az)orbit(az[value]);
        if(value==='eye level'){s.position.y=1.75;s.target.y=1.75;}
        if(value==='over-the-shoulder'){s.position=V(-1,1.8,4);s.target=V(0,1,0);}
        if(value==='first-person POV'){s.position=V(0,1.75,0);s.target=V(0,1.5,-5);}
        if(value==='object POV'){s.position=V(1.2,.8,.5);s.target=V(0,1.6,0);}
        if(value==='low angle'){s.position=V(0,.25,3);s.target.y=1.4;}
        if(value==='high angle')s.position=V(0,6,4);
        if(value==='top-down overhead view')s.position=V(0,8,.001);
        if(value==='bird-eye view')s.position=V(4,11,10);
        if(value==='worm-eye view'){s.position=V(0,.05,1);s.target.y=1.6;}
        if(value==='ground level'){s.position.y=.08;s.target.y=.1;}
        if(value==='dutch angle')s.roll=.35;
    }
    if(key==='lens'){
        const mm=Number.parseInt(value),f=Number.isFinite(mm)?mm/50:1;s.focal=f;s.position.z=6*f;s.position.y=1+(.7*f);
        if(value==='fisheye'){s.focal=.55;s.fisheye=true;}
    }
    if(key==='focus'){s.focus=value;s.focusProgress=p;}
    if(key==='movement'){
        const left=/left|counterclockwise/.test(value)?-1:1;
        if(/pan/.test(value))s.target.x=left*4*(value.startsWith('whip')?clamp(p*5):p);
        else if(/tilt/.test(value))s.target.y=1+(/up/.test(value)?2:-2)*p;
        else if(value==='slow dolly in')s.position.z=6-3*p;
        else if(value==='slow dolly out')s.position.z=6+6*p;
        else if(/^dolly (left|right)$/.test(value)){s.position.x=left*3*p;s.target.x=s.position.x;}
        else if(value==='smooth tracking shot'){s.actor.x=3*p;s.position.x=s.actor.x;s.target.x=s.actor.x;}
        else if(/^crane (up|down)$/.test(value))s.position.y=1.7+5*(value.endsWith('up')?p:1-p);
        else if(value==='crane over the head'){s.position=V(0,1.7+6*Math.sin(Math.PI*p),6*Math.cos(Math.PI*p));}
        else if(/^jib/.test(value)){const q=value.endsWith('up')?p:1-p;s.position.y=1.7+2*q;s.position.z=6-Math.sin(q*Math.PI/2);}
        else if(value==='aerial pullback'){s.position.y=1.7+6*p;s.position.z=6+8*p;}
        else if(/orbit|^arc/.test(value))orbit(left*p*(value.startsWith('arc')?Math.PI/4:Math.PI*2/3));
        else if(value==='lazy susan')orbit(p*Math.PI*2,3,V(1.15,.8,.4));
        else if(value.startsWith('camera roll'))s.roll=left*p*Math.PI/2;
        else if(value.startsWith('dolly zoom')){s.position.z=6+(value.endsWith('in')?-3:5)*p;s.position.y=1+.7*s.position.z/6;s.focal=s.position.z/6;}
        else if(value.startsWith('super dolly'))s.position.z=value.endsWith('in')?12-10*p:2+10*p;
        else if(value==='yoyo zoom')s.focal=1+1.2*Math.sin(Math.PI*p);
        else if(/zoom/.test(value)){const q=clamp(p*(value.startsWith('crash')?6:value.startsWith('rapid')?2.5:1));s.focal=mix(1,value.endsWith('in')?2.4:.45,q);}
        else if(value==='subtle handheld'||value==='wiggle'){s.position.x=.13*Math.sin(p*24)+ (value==='wiggle'?0:.05*Math.sin(p*53));s.position.y+=.07*Math.sin(p*31);s.roll=.025*Math.sin(p*20);}
        else if(value==='head tracking'){s.actor.x=.7*Math.sin(p*7);s.actor.y=.16*Math.sin(p*11);s.target=V(s.actor.x,1.65+s.actor.y,0);s.position.z=3;}
        else if(value==='snorricam'){s.actor=V(2*p,.06*Math.sin(p*25),-3*p);s.position=V(s.actor.x,1.5+s.actor.y,s.actor.z+2.7);s.target=V(s.actor.x,1.3+s.actor.y,s.actor.z);s.roll=.04*Math.sin(p*23);}
        else if(value==='car grip'||value==='car chasing'){s.vehicle=true;s.actor=V(2*p,0,-4*p);s.target=V(s.actor.x,.6,s.actor.z);s.position=V(s.actor.x+(value==='car grip'?1.7:0),1.4,s.actor.z+(value==='car grip'?1.6:5));}
        else if(value==='robo arm'){orbit(p*1.8,4);s.position.y=.5+3*p;}
        else if(value==='FPV drone'){s.position=V(2*Math.sin(p*5),2+Math.sin(p*4),10-8*p);s.roll=.3*Math.sin(p*6);}
        else if(value==='flying cam transition')s.position=V(4*(1-p),8-6.3*p,12-9*p);
        else if(value.startsWith('through object')){s.gate=true;s.position.z=value.endsWith('in')?8-6*p:2+6*p;}
    }
    // Reveal a chosen composition from the baseline, then hold it for comparison.
    if(['shot','angle','lens'].includes(key)){
        const q=p*p*(3-2*p),end=s.position;
        if(key==='angle'&&/three-quarter|profile|rear view/.test(value)){
            const azimuth=Math.atan2(end.x,end.z),radius=Math.hypot(end.x,end.z);
            s.position=V(Math.sin(azimuth*q)*radius,mix(1.7,end.y,q),Math.cos(azimuth*q)*radius);
        }else s.position=V(mix(0,end.x,q),mix(1.7,end.y,q),mix(6,end.z,q));
        s.target=V(mix(0,s.target.x,q),mix(1,s.target.y,q),mix(0,s.target.z,q));s.focal=mix(1,s.focal,q);s.roll*=q;
    }
    return s;
}

export function projectDemoPoint(point,state){
    const forward=unit(sub(state.target,state.position)),right=unit(cross(forward,V(0,1,0))),up=cross(right,forward),relative=sub(point,state.position),z=dot(relative,forward);
    if(z<=.04)return null;
    let x=dot(relative,right)/z*state.focal,y=-dot(relative,up)/z*state.focal;
    if(state.fisheye){const scale=1/(1+.45*(x*x+y*y));x*=scale;y*=scale;}
    return {x:x*Math.cos(state.roll)-y*Math.sin(state.roll),y:x*Math.sin(state.roll)+y*Math.cos(state.roll),depth:z};
}

function drawCameraPath(ctx,key,value,time){
    const state=cameraDemoState(key,value,time),map=p=>({x:58+p.x*3,y:32+p.z*2});
    ctx.clearRect(0,0,116,72);ctx.lineWidth=1;ctx.strokeStyle='#ffffff12';
    for(let x=10;x<116;x+=16){ctx.beginPath();ctx.moveTo(x,8);ctx.lineTo(x,64);ctx.stroke();}
    ctx.setLineDash([2,3]);ctx.strokeStyle='#a1ddcb80';ctx.beginPath();
    for(let i=0;i<=48;i++){const p=map(cameraDemoState(key,value,i/48*.82).position);i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);}ctx.stroke();ctx.setLineDash([]);
    const p=map(state.position),target=map(state.target),actor=map(state.actor),a=Math.atan2(target.y-p.y,target.x-p.x);
    ctx.fillStyle='#dfba94';ctx.beginPath();ctx.arc(actor.x,actor.y,3,0,2*Math.PI);ctx.fill();
    ctx.strokeStyle='#b8f0da';ctx.beginPath();ctx.moveTo(p.x+Math.cos(a-.4)*13,p.y+Math.sin(a-.4)*13);ctx.lineTo(p.x,p.y);ctx.lineTo(p.x+Math.cos(a+.4)*13,p.y+Math.sin(a+.4)*13);ctx.stroke();
    ctx.save();ctx.translate(p.x,p.y);ctx.rotate(a);ctx.fillStyle='#b8f0da';ctx.fillRect(-3,-2.5,6,5);ctx.restore();
}

let guideId=0;
export class CameraMotionPreview {
    constructor(owner,host){
        this.owner=owner;this.host=host;this.bindings=[];this.motion=window.matchMedia?.('(prefers-reduced-motion: reduce)');
        const listen=(node,type,handler,options)=>{node.addEventListener(type,handler,options);this.bindings.push(()=>node.removeEventListener(type,handler,options));};
        const control=e=>{const target=e.target?.closest?.('[data-camera-choice]');return target&&owner.contains(target)?target:null;};
        listen(owner,'pointerover',e=>{const target=control(e);if(target&&!target.contains(e.relatedTarget))this.schedule(target);});
        listen(owner,'pointerout',e=>{const target=control(e);if(target&&!target.contains(e.relatedTarget))this.hide();});
        listen(owner,'focusin',e=>{const target=control(e);if(target)this.show(target);});
        listen(owner,'focusout',e=>{if(control(e))this.hide();});
        listen(owner,'input',e=>{if(control(e)===this.target)this.show(this.target,this.fromPointer);});
        listen(owner,'keydown',e=>{if(e.key==='Escape'&&(this.target||this.timer)){this.hide();e.preventDefault();e.stopImmediatePropagation();}},true);
        listen(owner,'scroll',()=>this.hide(),true);listen(window,'resize',()=>this.hide());
        listen(document,'visibilitychange',()=>{if(document.hidden)this.hide();});
        this.motionChanged=()=>{if(this.target)this.show(this.target,this.fromPointer);};this.motion?.addEventListener?.('change',this.motionChanged);
    }
    schedule(target){this.hide();this.timer=setTimeout(()=>{this.timer=null;this.show(target,true);},120);}
    create(){
        if(this.root)return;
        const el=(tag,cls,text)=>{const node=document.createElement(tag);node.className=cls;if(text)node.textContent=text;return node;};
        this.root=el('aside','eh3-camera-motion-guide eh3-guide-inline');this.root.hidden=true;this.root.id=`eh3-camera-guide-${++guideId}`;this.root.setAttribute('role','group');this.root.setAttribute('aria-label','카메라 동작 안내');
        const header=el('div','eh3-guide-header'),identity=el('div','eh3-guide-identity');
        this.heading=el('strong','eh3-guide-title');this.english=el('span','eh3-guide-english');identity.append(this.heading,this.english);
        header.append(identity,el('span','eh3-guide-label','CAMERA LAB'));
        this.visual=el('div','eh3-guide-visual');this.canvas=el('canvas','eh3-guide-scene');this.canvas.width=480;this.canvas.height=600;this.canvas.setAttribute('aria-hidden','true');
        const badge=el('span','eh3-guide-badge','3D 모션 미리보기'),path=el('div','eh3-guide-path');this.pathCanvas=el('canvas','');this.pathCanvas.width=232;this.pathCanvas.height=144;this.pathCanvas.setAttribute('aria-hidden','true');path.append(this.pathCanvas,el('span','','카메라 경로'));
        this.unavailable=el('div','eh3-guide-unavailable','3D 미리보기를 표시할 수 없습니다. 브라우저 하드웨어 가속을 확인해 주세요.');this.unavailable.hidden=true;
        this.visual.append(this.canvas,badge,path,this.unavailable);
        this.description=el('p','eh3-guide-description');this.note=el('small','eh3-guide-note','동작 이해를 위한 가상 세트 · 실제 생성 결과와 다를 수 있습니다.');
        const progress=el('div','eh3-guide-progress');this.progress=el('span','');progress.append(this.progress);
        this.root.append(header,this.visual,progress,this.description,this.note);this.host.replaceChildren(this.root);
        this.pathContext=this.pathCanvas.getContext('2d');this.pathContext?.scale(2,2);
        try{this.renderer=new CameraStageRenderer(this.canvas);}catch(error){this.unavailable.hidden=false;console.warn('[Camera preview]',error.message);}
        this.canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();this.hide();this.renderer?.dispose(false);this.renderer=null;});
        this.canvas.addEventListener('webglcontextrestored',()=>{if(this.disposed)return;try{this.renderer=new CameraStageRenderer(this.canvas);this.unavailable.hidden=true;}catch{this.unavailable.hidden=false;}});
    }
    draw(key,value,time){
        this.renderer?.draw(cameraDemoState(key,value,time),key,value);
        if(this.pathContext)drawCameraPath(this.pathContext,key,value,time);
        this.progress.style.width=`${clamp(time)*100}%`;
    }

    show(target,fromPointer=false){
        this.hide();if(!target||this.owner.hidden||document.hidden)return;
        const key=target.dataset.cameraChoice,value=key==='strength'?target.value:target.dataset.value,guide=cameraGuide(key,value);if(!guide)return;
        this.create();this.target=target;this.fromPointer=fromPointer;this.heading.textContent=guide.label;this.english.textContent=key==='strength'?'MOTION AMPLITUDE':String(guide.value).toUpperCase();this.description.textContent=guide.description+(guide.complex?' 큰 시점 변화는 원본에 따라 재현 차이가 있습니다.':'');
        this.originalDescription=target.getAttribute('aria-describedby');target.setAttribute('aria-describedby',[this.originalDescription,this.root.id].filter(Boolean).join(' '));
        this.root.style.setProperty('--guide-font-scale',this.owner.style.getPropertyValue?.('--font-scale')||this.owner.style['--font-scale']||'1.5');
        this.root.hidden=false;this.root.classList.add('is-playing');

        const reduced=this.motion?.matches&&!fromPointer;this.lastFrame=-Infinity;this.started=performance.now();
        this.draw(key,value,reduced?.41:0);
        if(reduced)return;
        const tick=now=>{if(!this.target)return;if(now-this.lastFrame>=1000/24){this.draw(key,value,((now-this.started)%5000)/5000);this.lastFrame=now;}this.frame=requestAnimationFrame(tick);};
        this.frame=requestAnimationFrame(tick);
    }
    hide(){
        clearTimeout(this.timer);this.timer=null;if(this.frame!==undefined){cancelAnimationFrame(this.frame);this.frame=undefined;}
        if(this.target){if(this.originalDescription)this.target.setAttribute('aria-describedby',this.originalDescription);else this.target.removeAttribute('aria-describedby');this.target=null;}
        this.root?.classList.remove('is-playing');
    }
    dispose(){this.disposed=true;this.hide();for(const remove of this.bindings)remove();this.motion?.removeEventListener?.('change',this.motionChanged);this.renderer?.dispose();this.root?.remove();}
}
