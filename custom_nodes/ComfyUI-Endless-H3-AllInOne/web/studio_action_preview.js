import * as THREE from './vendor/build/three.module.js';
import {CameraStageRenderer} from './camera_character_renderer.js?v=lowpoly_20261017';
import {StudioActionActor} from './studio_action_actor.js?v=hoverloop_20261017';

const guides={
    generate:['생성','슬레이트를 내리고 선택한 생성 작업을 시작합니다.'],
    schedule:['다음 예약 생성','현재 생성이 끝나면 다음 클립 한 개를 생성하도록 예약합니다.'],
    stop:['생성 중지','진행 중인 작업 또는 자동 생성 예약을 중지합니다.'],
    upscale:['업스케일','선택한 영상의 해상도를 높입니다.'],
    merge:['영상 합치기','생성한 클립을 순서대로 하나의 영상으로 합칩니다.'],
    save:['저장 · 파일','계획을 저장하거나 파일을 불러오고 내보냅니다.'],
    refresh:['새로고침','목록이나 현재 작업 상태를 다시 확인합니다.'],
    settings:['설정','모델·옵티마이저·UI 등 공통 설정을 조절합니다.'],
    camera:['카메라 디렉팅','참고 영상의 카메라 구도와 움직임을 계획합니다.'],
    favorite:['즐겨찾기','출력 영상을 즐겨찾기로 표시하거나 모아 봅니다.'],
    delete:['삭제 · 휴지통','선택한 항목을 삭제하거나 휴지통을 확인합니다.'],
    clips:['씬 · 클립 계획','작업·씬·클립을 추가하거나 선택해 계획을 편집합니다.'],
    layout:['화면 · 미리보기','패널 배치와 미리보기 화면을 조절합니다.'],
};

export function studioActionFor(button){
    if(button.classList.contains('eh3-generate'))return 'generate';
    if(button.matches('[data-camera-choice]')||button.classList.contains('eh3-reference-remove')||button.classList.contains('eh3-gallery-card'))return null;
    const label=(button.getAttribute('aria-label')||button.textContent||'').trim();
    if(/카메라 디렉팅/.test(label))return 'camera';
    if(/예약/.test(label))return 'schedule';
    if(/중지/.test(label))return 'stop';
    if(/업스케일/.test(label))return 'upscale';
    if(/합치기|전체 합본/.test(label))return 'merge';
    if(/즐겨찾기/.test(label))return 'favorite';
    if(/삭제|휴지통|제거/.test(label))return 'delete';
    if(/새로고침|VRAM 리셋/.test(label)||label==='↻')return 'refresh';
    if(/저장|JSON|불러오기|내보내기|업로드|파일 선택/.test(label))return 'save';
    if(/공통 설정|LoRA|옵티마이저/.test(label))return 'settings';
    if(/새 작업|씬 추가|씬 분리|클립 추가|일괄 입력|선택 초기화|전체 선택|다중 선택/.test(label))return 'clips';
    if(/노드 보기|배치|확대|단독 보기|접기|펼치기|UI 작게|UI 크게/.test(label))return 'layout';
    if(button.classList.contains('eh3-reference-add'))return 'save';
    return null;
}

class ActionRenderer {
    constructor(canvas){
        this.stage=new CameraStageRenderer(canvas);const s=this.stage;
        s.set.visible=false;s.gate.visible=false;s.vehicle.visible=false;s.release(s.modelRoot);s.modelRoot.clear();
        this.actor=new StudioActionActor();s.modelRoot.add(this.actor.root);
        const floor=new THREE.Mesh(new THREE.CircleGeometry(100,48),new THREE.MeshStandardMaterial({color:'#c9c7bc',roughness:.85}));floor.rotation.x=-Math.PI/2;floor.position.y=-.065;floor.receiveShadow=true;s.scene.add(floor);
        const plinth=new THREE.Mesh(new THREE.CylinderGeometry(.64,.69,.05,48),new THREE.MeshStandardMaterial({color:'#e6e0d1',roughness:.7}));plinth.position.y=-.035;plinth.receiveShadow=true;s.scene.add(plinth);
        s.camera.position.set(1.15,1.72,4.2);s.camera.fov=30;s.camera.lookAt(0,1.0,.05);s.camera.updateProjectionMatrix();
    }
    draw(kind,time){this.actor.pose(kind,time);this.stage.renderer.render(this.stage.scene,this.stage.camera);}
    dispose(){this.stage.dispose();}
}

let nextId=0;
export class StudioActionPreview {
    constructor(owner){
        this.owner=owner;this.bindings=[];this.motion=window.matchMedia?.('(prefers-reduced-motion: reduce)');
        const listen=(node,event,handler,options)=>{node.addEventListener(event,handler,options);this.bindings.push(()=>node.removeEventListener(event,handler,options));};
        const target=e=>{const button=e.target?.closest?.('button');return button&&owner.contains(button)&&studioActionFor(button)?button:null;};
        listen(owner,'pointerover',e=>{const button=target(e);if(button&&!button.contains(e.relatedTarget))this.schedule(button);});
        listen(owner,'pointerout',e=>{const button=target(e);if(button&&!button.contains(e.relatedTarget))this.hide();});
        listen(owner,'focusin',e=>{const button=target(e);if(button)this.show(button);});
        listen(owner,'focusout',()=>this.hide());
        listen(owner,'click',()=>this.hide(),true);
        listen(owner,'scroll',()=>this.hide(),true);
        listen(owner,'keydown',e=>{if(e.key==='Escape'&&(this.target||this.timer)){this.hide();e.preventDefault();e.stopImmediatePropagation();}},true);
        listen(window,'resize',()=>this.hide());listen(document,'visibilitychange',()=>{if(document.hidden)this.hide();});
        this.motionChanged=()=>{if(this.target)this.show(this.target,this.fromPointer);};this.motion?.addEventListener?.('change',this.motionChanged);
    }
    schedule(target){this.hide();this.timer=setTimeout(()=>{this.timer=null;this.show(target,true);},120);}
    create(){
        if(this.root)return;
        const el=(tag,cls,text)=>{const node=document.createElement(tag);node.className=cls;if(text)node.textContent=text;return node;};
        this.root=el('aside','eh3-action-guide');this.root.hidden=true;this.root.popover='manual';this.root.id=`eh3-action-guide-${++nextId}`;this.root.setAttribute('role','tooltip');
        this.canvas=el('canvas','eh3-action-scene');this.canvas.width=680;this.canvas.height=520;this.canvas.setAttribute('aria-hidden','true');
        this.heading=el('strong','eh3-action-title');this.description=el('p','eh3-action-description');
        const copy=el('div','eh3-action-copy');copy.append(el('span','eh3-action-eyebrow','SCENE ASSISTANT'),this.heading,this.description);
        this.unavailable=el('div','eh3-action-unavailable','기능 안내');this.unavailable.hidden=true;
        this.root.append(this.canvas,copy,this.unavailable);document.body.append(this.root);
        try{this.renderer=new ActionRenderer(this.canvas);}catch{this.unavailable.hidden=false;this.canvas.hidden=true;}
        this.canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();this.hide();this.renderer?.stage.dispose(false);this.renderer=null;});
        this.canvas.addEventListener('webglcontextrestored',()=>{if(this.disposed)return;try{this.renderer=new ActionRenderer(this.canvas);this.canvas.hidden=false;this.unavailable.hidden=true;}catch{this.canvas.hidden=true;this.unavailable.hidden=false;}});
    }
    show(target,fromPointer=false){
        this.hide();if(this.disposed||document.hidden||!target||!this.owner.contains(target))return;
        const kind=studioActionFor(target);if(!kind)return;
        this.create();this.target=target;this.fromPointer=fromPointer;this.kind=kind;const [label,description]=guides[kind];
        this.heading.textContent=target.classList.contains('eh3-generate')?'Generate':target.textContent.trim()||label;
        this.previousTitle=target.getAttribute('title');
        this.description.textContent=(target.disabled?'현재 사용할 수 없는 기능입니다. ':'')+(target.title||description);
        target.removeAttribute('title');
        this.previous=target.getAttribute('aria-describedby');target.setAttribute('aria-describedby',[this.previous,this.root.id].filter(Boolean).join(' '));
        this.root.style.setProperty('--action-font-scale',this.owner.style.getPropertyValue?.('--font-scale')||this.owner.style['--font-scale']||'1.5');
        this.root.hidden=false;this.root.showPopover();this.place(target);this.started=performance.now();this.lastFrame=-Infinity;
        const reduced=this.motion?.matches&&!fromPointer;
        this.renderer?.draw(kind,reduced ? .5 : 0);if(reduced||!this.renderer)return;
        const tick=now=>{if(!this.target)return;if(now-this.lastFrame>=1000/24){this.renderer.draw(this.kind,((now-this.started)%3600)/3600);this.lastFrame=now;}this.frame=requestAnimationFrame(tick);};
        this.frame=requestAnimationFrame(tick);
    }
    place(target){
        const a=target.getBoundingClientRect(),r=this.root.getBoundingClientRect(),w=window.innerWidth,h=window.innerHeight;
        const clamp=(v,max)=>Math.max(8,Math.min(v,Math.max(8,max)));
        let top=a.top-r.height-12,left=a.left+(a.width-r.width)/2;
        if(top<8){top=a.bottom+12;if(top+r.height>h-8){top=a.top;left=a.right+12;if(left+r.width>w-8)left=a.left-r.width-12;}}
        Object.assign(this.root.style,{left:`${clamp(left,w-r.width-8)}px`,top:`${clamp(top,h-r.height-8)}px`});
    }
    hide(){
        clearTimeout(this.timer);this.timer=null;if(this.frame!==undefined){cancelAnimationFrame(this.frame);this.frame=undefined;}
        if(this.target){if(this.previous)this.target.setAttribute('aria-describedby',this.previous);else this.target.removeAttribute('aria-describedby');if(this.previousTitle!==null&&this.target.getAttribute('title')===null)this.target.setAttribute('title',this.previousTitle);this.target=null;}
        if(this.root&&!this.root.hidden){this.root.hidePopover();this.root.hidden=true;}
    }
    dispose(){this.disposed=true;this.hide();for(const remove of this.bindings)remove();this.motion?.removeEventListener?.('change',this.motionChanged);this.renderer?.dispose();this.root?.remove();}
}
