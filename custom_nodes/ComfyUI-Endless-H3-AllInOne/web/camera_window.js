import {MultiAngleEditor} from './multiangle_editor.js?v=precise_angles_20261017_v2';
import {slicePathFrames} from './multiangle_math.js?v=precise_angles_20261017_v2';

import {checkCameraCorrections} from './camera_corrections.js?v=pruned_camera_20261017_v1';

import {applyCameraSettings,cameraTimelineInputs} from './camera_graph.js?v=pruned_camera_20261017_v1';

import {SHOTS,ANGLES,MOVES,LENSES,FOCUS,SPEEDS,EASINGS,REMOVED_MOVES,normalizeCameraSegment} from './camera_controls.js?v=pruned_camera_20261017_v1';

import {CameraMotionPreview} from './camera_motion_preview.js?v=pruned_camera_20261017_v1';

import {cameraControlIcon} from './camera_icons.js?v=icons_20261017';

const clone = value => JSON.parse(JSON.stringify(value));

function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}

const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));

export const cameraEngineURL = (moduleURL = import.meta.url) => new URL('../ComfyUI-H3-R2V-CameraLipLock/camera_dynamic_graph.js', moduleURL).href;

let windowId=0;

export class StudioCameraWindow {

    constructor(studio,api,engineLoader=async()=>import(cameraEngineURL())){

        this.studio=studio;this.api=api;this.engineLoader=engineLoader;

        this.state=studio.node.properties.endless_camera_window||={widgets:{},bounds:{}};

        this.state.widgets||={};this.state.bounds||={};this.state.results||=[];this.selected=0;this.handlers=[];this.categoryFilters={};this.activeChoice='movement';

        Object.assign(this.state.widgets,{edit_strength:this.state.widgets.edit_strength??.95,lip_sync_strict:this.state.widgets.lip_sync_strict??true,segment_preview:this.state.widgets.segment_preview??true});

        this.root=el('section',undefined,'eh3-studio eh3-camera-window');this.root.id=`eh3-camera-window-${++windowId}`;this.root.hidden=true;this.root.popover='manual';this.root.tabIndex=-1;

        this.root.setAttribute('role','dialog');this.root.setAttribute('aria-modal','false');this.root.setAttribute('aria-label','4번 패널 · 카메라 디렉팅');

        this.header=el('header',undefined,'eh3-camera-window-header');const grip=el('div',undefined,'eh3-desk-brand');grip.tabIndex=0;grip.title='드래그 또는 방향키로 창 이동';

        const symbol=el('span',undefined,'eh3-desk-symbol');symbol.innerHTML=cameraControlIcon('movement','static camera');symbol.setAttribute('aria-hidden','true');

        const brand=el('div');brand.append(el('small','FLAGSHIP SCENE UI'),el('strong','카메라 디렉팅'));grip.append(symbol,brand);

        const close=this.button('×',()=>this.close(),'eh3-desk-close');close.setAttribute('aria-label','카메라 디렉팅 닫기');this.header.append(grip,close);

        const sourceRow=el('div',undefined,'eh3-camera-window-source');this.sourceSelect=el('select');this.sourceSelect.setAttribute('aria-label','참조 비디오 선택');this.sourceSelect.onchange=()=>this.useSource(this.sourceSelect.value);

        this.sourceMeta=el('span','참고 영상 선택','eh3-help');sourceRow.append(el('span','REF','eh3-desk-ref'),this.sourceSelect,this.sourceMeta);

        this.body=el('div',undefined,'eh3-camera-window-body');

        this.sourceVideo=el('video');this.sourceVideo.preload='metadata';this.sourceVideo.muted=true;

        this.sourceVideo.addEventListener('loadedmetadata',()=>this.metadata());

        this.planCard=el('section',undefined,'eh3-camera-card');this.body.append(this.planCard);

        const resize=this.button('↘',()=>{},'eh3-camera-window-resize');resize.title='드래그 또는 방향키로 창 크기 조절';

        this.root.append(this.header,sourceRow,this.body,resize);document.body.append(this.root);

        this.guideHost=el('aside',undefined,'eh3-desk-guide');this.motionGuide=new CameraMotionPreview(this.root,this.guideHost);

        this.bindDrag(grip,false);this.bindDrag(resize,true);this.viewportChanged=()=>this.place();window.addEventListener('resize',this.viewportChanged);

        this.root.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();this.close();}});

        for(const type of ['execution_start','progress','executed','execution_success','execution_error','execution_interrupted']){

            const handler=event=>this.event(type,event.detail);api.addEventListener(type,handler);this.handlers.push([type,handler]);

        }

        this.place();

    }

    button(text,action,cls){const node=el('button',text,cls);node.type='button';node.onclick=async()=>{try{await action();}catch(error){this.notice(error.message,true);}};return node;}

    persist(){this.studio.persist();}

    setFontScale(scale){this.root.style.setProperty('--font-scale',String(scale));}

    notice(text,error=false){this.message=text;this.error=error;this.updateControls();}

    place(){

        const b=this.state.bounds,old=this.lastViewport,w=window.innerWidth,h=window.innerHeight;

        if(old&&(old.width!==w||old.height!==h)){

            b.width=(Number(b.width)||Math.min(700,old.width*.48))*w/old.width;b.height=(Number(b.height)||old.height*.84)*h/old.height;

            b.left=(Number(b.left)||16)*w/old.width;b.top=(Number(b.top)||40)*h/old.height;

        }

        this.lastViewport={width:w,height:h};

        const width=clamp(Number(b.width)||Math.min(700,w*.48),Math.min(360,w-16),Math.max(1,w-16));

        const height=clamp(Number(b.height)||h*.84,Math.min(320,h-16),Math.max(1,h-16));

        const left=clamp(Number(b.left)||16,8,Math.max(8,w-width-8)),top=clamp(Number(b.top)||40,8,Math.max(8,h-height-8));

        Object.assign(this.root.style,{width:`${width}px`,height:`${height}px`,left:`${left}px`,top:`${top}px`});

        this.state.bounds={width,height,left,top};

    }

    bindDrag(handle,sizing){

        let drag;const bounds=()=>{const r=this.root.getBoundingClientRect();return {width:r.width,height:r.height,left:r.left,top:r.top};};

        const move=(dx,dy,b)=>{this.state.bounds=sizing?{...b,width:b.width+dx,height:b.height+dy}:{...b,left:b.left+dx,top:b.top+dy};this.place();};

        handle.addEventListener('pointerdown',e=>{if(e.button!==undefined&&e.button!==0)return;e.preventDefault();drag={...bounds(),x:e.clientX,y:e.clientY,id:e.pointerId};handle.setPointerCapture(e.pointerId);});

        handle.addEventListener('pointermove',e=>{if(drag&&e.pointerId===drag.id)move(e.clientX-drag.x,e.clientY-drag.y,drag);});

        const stop=()=>{if(drag){drag=null;this.persist();}};for(const type of ['pointerup','pointercancel','lostpointercapture'])handle.addEventListener(type,stop);

        handle.addEventListener('keydown',e=>{const dx=e.key==='ArrowRight'?20:e.key==='ArrowLeft'?-20:0,dy=e.key==='ArrowDown'?20:e.key==='ArrowUp'?-20:0;if(dx||dy){e.preventDefault();move(dx,dy,bounds());this.persist();}});

    }

    setReferences(entries){

        this.sources=entries.map(v=>typeof v==='string'?v:v.name).filter(Boolean);this.sourceSelect.replaceChildren();

        const manual=el('option','직접 업로드 영상');manual.value='';this.sourceSelect.append(manual);

        for(const name of this.sources){const option=el('option',name);option.value=name;this.sourceSelect.append(option);}

        if(this.state.selectedRef&&!this.sources.includes(this.state.selectedRef)){this.state.selectedRef='';this.state.widgets.source_video='';}

        this.sourceSelect.value=this.state.selectedRef||'';

    }

    async open(entries){

        this.setReferences(entries);this.setFontScale(this.studio.node.properties.endless_font_scale??1.5);this.root.hidden=false;

        this.place();this.root.showPopover();this.root.focus({preventScroll:true});this.studio.cameraButton?.setAttribute('aria-expanded','true');

        await this.ready();if(this.disposed)return;

        const source=this.state.widgets.source_video||this.sources[0];if(source)this.useSource(source,this.sources.includes(source));

        await this.restoreJob();

        this.studio.galleryPreview=null;this.studio.previewKind='camera';this.studio.cameraPreviewId='source';this.studio.persist();this.studio.drawPreview();

    }

    async ready(){

        if(!this.loading)this.loading=this.initialize().catch(error=>{this.loading=null;this.notice(error.message,true);throw error;});

        await this.loading;

    }

    async initialize(){

        const response=await this.api.fetchApi('/object_info/H3R2VCameraTimeline');if(!response.ok)throw Error('카메라 노드 정보를 불러올 수 없습니다.');

        const schema=(await response.json()).H3R2VCameraTimeline;if(!schema)throw Error('H3R2VCameraTimeline 설치를 확인해 주세요.');if(this.disposed)return;

        this.schema={...schema.input.required,...schema.input.optional};

        for(const [name,[type,options={}]] of Object.entries(this.schema))this.state.widgets[name]??=options.default??(Array.isArray(type)?type[0]:type==='BOOLEAN'?false:type==='STRING'?'':0);

        try{this.segments=JSON.parse(this.state.widgets.camera_plan_json).segments;}catch{}if(!Array.isArray(this.segments)||!this.segments.length)this.segments=[this.newSegment(0,124)];

        this.segments.forEach(normalizeCameraSegment);this.renderPlan();this.updateControls();await this.restoreJob();

    }

    fps(){return Number(this.state.widgets.source_fps)||24;}

    newSegment(start,end){return {start_frame:start,end_frame:Math.max(start+5,end),shot:'medium shot',movement:'static camera',speed:'slow',strength:.35,angle:'source angle',lens:'natural',focus:'source',easing:'linear'};}

    sourceURL(source,type='input'){

        const path=source.replaceAll('\\','/'),relative=/^[A-Za-z]:\//.test(path)||path.startsWith('/')?path.split('/').at(-1):path,slash=relative.lastIndexOf('/');

        return this.api.apiURL(`/view?${new URLSearchParams({filename:relative.slice(slash+1),subfolder:slash<0?'':relative.slice(0,slash),type})}`);

    }

    useSource(name,reference=true){

        this.state.widgets.source_video=name;this.state.selectedRef=reference?name:'';this.sourceSelect.value=this.state.selectedRef;

        this.sourceVideo.pause();this.sourceVideo.src=name?this.sourceURL(name):'';this.sourceVideo.hidden=!name;if(name)this.sourceVideo.load();

        this.sourceMeta.textContent=name||'참조 비디오를 선택하세요.';this.updateControls();this.persist();if(this.studio.previewKind==='camera'){this.studio.cameraPreviewId='source';this.studio.drawPreview();}

    }

    metadata(){

        const source=this.state.widgets.source_video,frames=Math.floor(Number(this.sourceVideo.duration)*this.fps());

        if(Number.isFinite(frames)&&frames>=5&&this.state.planSource!==source){this.segments=[this.newSegment(0,frames)];this.selected=0;this.state.planSource=source;this.writePlan();this.renderPlan();}

        this.sourceMeta.textContent=`${this.sourceVideo.videoWidth} × ${this.sourceVideo.videoHeight} · ${Number(this.sourceVideo.duration||0).toFixed(2)}초 · ${this.fps()}fps 기준`;

    }

    async prepareSource(){

        if(this.sourceVideo.readyState<1)await new Promise((resolve,reject)=>{

            const cleanup=()=>{clearTimeout(timer);this.sourceVideo.removeEventListener('loadedmetadata',loaded);this.sourceVideo.removeEventListener('error',failed);};

            const loaded=()=>{cleanup();resolve();},failed=()=>{cleanup();reject(Error('참고 비디오를 불러오지 못했습니다. 본 UI에서 파일을 확인해 주세요.'));};

            const timer=setTimeout(failed,20000);this.sourceVideo.addEventListener('loadedmetadata',loaded);this.sourceVideo.addEventListener('error',failed);

        });

        this.metadata();

    }

    writePlan(){

        for(const part of this.segments){part.start_seconds=part.start_frame/this.fps();part.end_seconds=part.end_frame/this.fps();}

        this.state.widgets.camera_plan_json=JSON.stringify({segments:this.segments});this.persist();

    }

    choices(parent,title,items,key,segment){

        const values=items.map(item=>Array.isArray(item)?{value:item[0],label:item[1],group:title}:item);

        const group=el('section',undefined,'eh3-camera-choices');group.dataset.choicePanel=key;group.hidden=this.activeChoice!==key;group.id=this.root.id+'-'+key;group.setAttribute('aria-label',title);

        const heading=el('div',undefined,'eh3-desk-choice-heading');heading.append(el('strong',title),el('small',`${values.length}개`));group.append(heading);parent.append(group);

        const sections=[],categories=[...new Set(values.map(item=>item.group))];

        let category=this.categoryFilters[key]||values.find(item=>item.value===segment[key])?.group||categories[0],query='';

        const filter=()=>{for(const section of sections){const buttons=Array.from(section.querySelectorAll('[data-camera-choice]'));for(const button of buttons)button.hidden=!!query&&!button.dataset.search.includes(query);section.hidden=buttons.every(button=>button.hidden)||(!query&&category!=='전체'&&category!==section.dataset.category);}};

        if(values.length>12){

            const search=el('input');search.type='search';search.placeholder='기능 찾기 · 한글 / English';search.setAttribute('aria-label',title+' 검색');search.oninput=()=>{query=search.value.trim().toLowerCase();filter();};group.append(search);

        }

        if(categories.length>1){

            const chips=el('div',undefined,'eh3-desk-categories');

            for(const name of ['전체',...categories]){const chip=this.button(name,()=>{category=name;this.categoryFilters[key]=name;for(const b of chips.children){b.classList.toggle('selected',b===chip);b.setAttribute('aria-pressed',String(b===chip));}filter();});chip.classList.toggle('selected',category===name);chip.setAttribute('aria-pressed',String(category===name));chips.append(chip);}group.append(chips);

        }

        for(const category of categories){

            const section=el('div',undefined,'eh3-camera-option-group'),options=values.filter(item=>item.group===category);section.dataset.category=category;

            if(categories.length>1)section.append(el('span',category,'eh3-desk-category-title'));

            const row=el('div',undefined,'eh3-choice-buttons');section.append(row);group.append(section);sections.push(section);

            for(const item of options){

                const button=this.button('',()=>{segment[key]=item.value;this.categoryFilters[key]=this.categoryFilters[key]==='전체'?'전체':item.group;this.writePlan();this.renderPlan();});

                const icon=el('span',undefined,'eh3-camera-choice-icon');icon.innerHTML=cameraControlIcon(key,item.value);icon.setAttribute('aria-hidden','true');

                button.append(icon,el('span',item.label,'eh3-camera-choice-name'));button.classList.add('eh3-camera-choice-tile');

                button.setAttribute('aria-label',`${item.label} · ${item.value}`);

                button.dataset.cameraChoice=key;button.dataset.value=item.value;button.dataset.search=[item.label,item.value,item.group].join(' ').toLowerCase();

                button.classList.toggle('selected',segment[key]===item.value);button.setAttribute('aria-pressed',String(segment[key]===item.value));row.append(button);

            }

        }

        filter();

    }

    activateChoice(key){

        this.motionGuide.hide();this.activeChoice=key;

        for(const panel of this.planCard.querySelectorAll('[data-choice-panel]'))panel.hidden=panel.dataset.choicePanel!==key;

        for(const button of this.planCard.querySelectorAll('[data-choice-tab]')){button.classList.toggle('selected',button.dataset.choiceTab===key);button.setAttribute('aria-pressed',String(button.dataset.choiceTab===key));button.setAttribute('aria-controls',this.root.id+'-'+button.dataset.choiceTab);}

    }

    renderPlan(){

        this.motionGuide.hide();
        this.multiAngleEditor?.destroy();

        const scroll=this.body.scrollTop;

        this.planCard.replaceChildren();const timeline=el('section',undefined,'eh3-desk-timeline'),head=el('div',undefined,'eh3-desk-timeline-heading'),duration=this.segments.at(-1).end_frame/this.fps();

        head.append(el('strong','카메라 구간'),el('span',`총 ${duration.toFixed(2)}초`));timeline.append(head);

        const ruler=el('div',undefined,'eh3-desk-ruler');for(let i=0;i<5;i++)ruler.append(el('span',(duration*i/4).toFixed(1)+'s'));timeline.append(ruler);

        const tabs=el('div',undefined,'eh3-desk-segments');

        this.segments.forEach((segment,i)=>{const button=this.button('',()=>{this.selected=i;this.renderPlan();});button.append(el('span',`구간 ${String(i+1).padStart(2,'0')}`),el('small',`${(segment.start_frame/this.fps()).toFixed(1)}—${(segment.end_frame/this.fps()).toFixed(1)}s`));button.style.flexGrow=String(segment.end_frame-segment.start_frame);button.classList.toggle('selected',i===this.selected);button.setAttribute('aria-pressed',String(i===this.selected));tabs.append(button);});timeline.append(tabs);

        const part=this.segments[this.selected],times=el('div',undefined,'eh3-camera-fields');
        const removed=part.multi_angle?.enabled===true?null:REMOVED_MOVES.find(([value])=>value===part.movement);
        if(removed){const warning=el('p',`${removed[1]}은 제거된 모드입니다. 무빙에서 다른 모드를 선택하세요.`,'eh3-help');warning.setAttribute('role','status');timeline.append(warning);}

        for(const [key,title] of [['start_frame','시작 · 초'],['end_frame','끝 · 초']]){

            const label=el('label',title,'eh3-field'),input=el('input');input.type='number';input.min='0';input.step=(1/this.fps()).toFixed(4);input.value=String(part[key]/this.fps());input.onchange=()=>{const frame=Math.round(Number(input.value)*this.fps());part[key]=key==='start_frame'?clamp(frame,0,part.end_frame-5):Math.max(part.start_frame+5,frame);this.writePlan();this.renderPlan();};label.append(input,this.button('재생 위치 지정',()=>{input.value=String(Number(this.studio.previewKind==='camera'&&this.studio.cameraPreviewId==='source'?this.studio.video.currentTime:0)||0);input.onchange();}));times.append(label);

        }

        timeline.append(times);this.planCard.append(timeline);
        this.multiAngleEditor=new MultiAngleEditor(this.planCard,part.multi_angle,path=>{
            part.multi_angle=path;this.writePlan();
        },{duration:Math.max(1/this.fps(),(part.end_frame-part.start_frame-1)/this.fps())});

        const nav=el('nav',undefined,'eh3-desk-tabs');nav.setAttribute('aria-label','카메라 기능');

        for(const [key,label] of [['shot','프레이밍'],['angle','앵글'],['movement','무빙'],['lens','렌즈'],['focus','초점']]){const button=this.button(label,()=>this.activateChoice(key));button.dataset.choiceTab=key;nav.append(button);}this.planCard.append(nav);

        const shelf=el('div',undefined,'eh3-desk-shelf'),editor=el('div',undefined,'eh3-desk-editor');shelf.append(editor,this.guideHost);this.planCard.append(shelf);

        this.choices(editor,'프레이밍',SHOTS,'shot',part);this.choices(editor,'카메라 앵글',ANGLES,'angle',part);this.choices(editor,'카메라 무빙',MOVES,'movement',part);this.choices(editor,'렌즈',LENSES,'lens',part);this.choices(editor,'초점·포커스 전환',FOCUS,'focus',part);this.choices(editor,'이동 속도',SPEEDS,'speed',part);this.choices(editor,'가감속',EASINGS,'easing',part);

        const params=el('div',undefined,'eh3-desk-params'),strength=el('label',undefined,'eh3-field'),strengthLabel=el('span',`모션 강도 · ${Number(part.strength).toFixed(2)}`),range=el('input');range.type='range';range.min='0';range.max='1';range.step='.05';range.value=part.strength;range.dataset.cameraChoice='strength';range.setAttribute('aria-label','카메라 모션 강도');range.oninput=()=>{part.strength=Number(range.value);this.writePlan();strengthLabel.textContent=`모션 강도 · ${part.strength.toFixed(2)}`;};strength.append(strengthLabel,range);params.append(strength);

        for(const [key,label,value] of [['speed','이동 속도',SPEEDS.find(([value])=>value===part.speed)?.[1]],['easing','가감속',EASINGS.find(item=>item.value===part.easing)?.label]]){const group=el('div');group.append(el('small',label));const button=this.button((value||'선택')+' ⌄',()=>this.activateChoice(key));button.dataset.choiceTab=key;group.append(button);params.append(group);}this.planCard.append(params);

        const footer=el('footer',undefined,'eh3-desk-footer'),actions=el('div',undefined,'eh3-row');footer.append(el('small','생성·업스케일은 메인 스튜디오에서'),actions);

        actions.append(this.button('+ 구간',()=>{if(this.segments.length>=64)throw Error('최대 64구간입니다.');const end=this.segments.at(-1).end_frame;this.segments.push(this.newSegment(end,end+Math.round(5*this.fps())));this.selected=this.segments.length-1;this.writePlan();this.renderPlan();}),this.button('분할',()=>this.split()),this.button('구간 삭제',()=>{if(this.segments.length===1)return;this.segments.splice(this.selected,1);this.selected=Math.min(this.selected,this.segments.length-1);this.writePlan();this.renderPlan();}));this.planCard.append(footer);

        this.activateChoice(this.activeChoice);const selected=editor.querySelector('[data-choice-panel="'+this.activeChoice+'"] [data-camera-choice].selected');if(selected){this.motionGuide.show(selected);this.motionGuide.hide();}this.body.scrollTop=scroll;this.updateControls();

    }

    split(){

        const part=this.segments[this.selected],frame=Math.round((Number(this.studio.previewKind==='camera'&&this.studio.cameraPreviewId==='source'?this.studio.video.currentTime:0)||0)*this.fps());

        if(frame<part.start_frame+5||frame>part.end_frame-5)throw Error('구간 안에서 양쪽에 5프레임 이상 남는 위치를 선택해 주세요.');if(this.segments.length>=64)throw Error('최대 64구간입니다.');

        const left={...part,end_frame:frame},right={...part,start_frame:frame};
        if(part.multi_angle?.enabled){
            const total=part.end_frame-part.start_frame,offset=frame-part.start_frame;
            left.multi_angle=slicePathFrames(part.multi_angle,total,0,offset);
            right.multi_angle=slicePathFrames(part.multi_angle,total,offset,total);
        }
        this.segments.splice(this.selected,1,left,right);this.writePlan();this.renderPlan();

    }

    renderMainSettings(parent){

        const panel=this.studio.collapsible(parent,'camera_execution','카메라 생성 설정','eh3-camera-execution',true);

        for(const [label,key,options] of [['재생성 강도','edit_strength',{type:'number',min:.7,max:1,step:.05}],['원본 립싱크 고정','lip_sync_strict',{}],['구간 미리보기','segment_preview',{}]])this.studio.field(panel,label,this.state.widgets,key,options);

        panel.append(el('p','모델·샘플링·해상도·업스케일은 본 UI 설정을 사용합니다. 원본 립싱크 고정 ON이면 카메라 생성의 Spectrum은 OFF입니다.','eh3-help'));

        this.executionPanel=panel;

    }

    updateControls(){

        const busy=!!this.running||!!this.submitting;

        this.sourceSelect.disabled=busy;this.planCard.querySelectorAll('input,button,select').forEach(input=>{input.disabled=busy;});

        this.executionPanel?.querySelectorAll('input,button').forEach(input=>{input.disabled=busy;});

        if(this.studio.generateButton&&!this.studio.disposed)this.studio.updateStatus();

    }

    async queue(){

        if(this.submitting||this.running)return;await this.ready();this.submitting=true;this.updateControls();

        try{const q=await(await this.api.fetchApi('/queue')).json();if([...q.queue_running,...q.queue_pending].some(item=>item[1]===this.state.promptId))throw Error('이 카메라 작업이 이미 대기 또는 생성 중입니다.');

            if(!this.state.widgets.source_video)throw Error('먼저 영상을 선택하세요.');await this.prepareSource();this.writePlan();const engine=await this.engineLoader(),s=clone(this.studio.state.plan.settings),inputs=cameraTimelineInputs(this.state.widgets,s);

            const controlModel=await checkCameraCorrections(this.api,this.segments);

            this.state.job={created:Date.now()/1000,project_id:this.studio.state.project_id||'',project_name:this.studio.state.name};this.state.segmentPreview=null;

            const output=applyCameraSettings(engine.expandCameraTimelines(await engine.materializeCameraWorkflow({'1':{class_type:'H3R2VCameraTimeline',inputs}})),s,{strict:inputs.lip_sync_strict,seed:this.studio.state.plan.clips[this.studio.selected].seed,projectId:this.state.job.project_id,segments:this.segments,corrections:true,cacheKey:crypto.randomUUID(),controlModel});

            this.finalNodeId=Object.keys(output).find(key=>output[key].class_type==='SaveVideo');

            const workflow={version:.4,last_node_id:1,last_link_id:0,links:[],groups:[],config:{},extra:{},nodes:[{id:1,type:'H3R2VCameraTimeline',pos:[0,0],size:[1200,760],flags:{},order:0,mode:0,properties:{},widgets_values:Object.keys(this.schema).map(k=>inputs[k])}]};

            const result=await this.api.queuePrompt(0,{output,workflow});this.state.promptId=result.prompt_id;this.state.finalNodeId=this.finalNodeId;this.running=true;this.studio.previewKind='camera';this.persist();this.notice('카메라 작업 예약 완료');

        }catch(error){this.notice(error.message,true);throw error;}finally{this.submitting=false;this.updateControls();}

    }

    event(type,data){

        if(!this.state.promptId||data?.prompt_id!==this.state.promptId)return;

        if(type==='execution_start'){this.running=true;this.notice('카메라 영상 생성 중');}

        if(type==='progress'){this.running=true;this.notice(`카메라 생성 중 · ${data.value}/${data.max}`);}

        if(type==='executed'){

            const segment=data.output?.h3_camera_preview?.at(-1);if(segment){this.state.segmentPreview=segment;this.studio.cameraPreviewId='live';this.studio.previewKind='camera';}

            if(String(data.node)===String(this.state.finalNodeId))this.outputs(data.output);

        }

        if(['execution_success','execution_error','execution_interrupted'].includes(type)){this.running=false;this.notice(type==='execution_success'?'카메라 생성 완료':type==='execution_error'?`생성 실패 · ${data.exception_message||'로그를 확인해 주세요.'}`:'카메라 작업 중단됨',type==='execution_error');}

        this.updateControls();

    }

    outputs(output,select=true){

        const item=(output?.videos||output?.gifs)?.at(-1);if(!item?.filename||item.type==='temp')return;

        this.state.lastOutput=item;

        let result=this.state.results.find(value=>value.job===this.state.promptId);

        if(!result){result={...this.state.job,job:this.state.promptId,created:this.state.job?.created||Date.now()/1000};this.state.results.push(result);}

        Object.assign(result,item,{finished:result.finished||Date.now()/1000});

        if(select){this.studio.galleryPreview=null;this.studio.cameraPreviewId=result.job;this.studio.previewKind='camera';}this.persist();

    }

    async restoreJob(){

        if(!this.state.promptId||this.restoringJob)return;this.restoringJob=true;

        try{

        const promptId=this.state.promptId;

        const [history,q]=await Promise.all([this.api.fetchApi(`/history/${encodeURIComponent(promptId)}`).then(r=>r.json()),this.api.fetchApi('/queue').then(r=>r.json())]);

        if(this.disposed||promptId!==this.state.promptId)return;const outputs=history[promptId]?.outputs||{};const output=outputs[this.state.finalNodeId]||Object.values(outputs).find(value=>(value?.videos||value?.gifs)?.some(item=>item.type==='output'));if(output)this.outputs(output,!!this.running);

        this.running=[...q.queue_running,...q.queue_pending].some(item=>item[1]===promptId);this.updateControls();

        }finally{this.restoringJob=false;}

    }

    async cancel(){

        if(!this.state.promptId)return;const q=await(await this.api.fetchApi('/queue')).json();

        if(q.queue_pending.some(item=>item[1]===this.state.promptId))await this.api.deleteItem('queue',this.state.promptId);

        else if(q.queue_running.some(item=>item[1]===this.state.promptId))await this.api.interrupt(this.state.promptId);

        this.running=false;this.updateControls();this.notice('이 카메라 작업만 중단 요청했습니다.');

    }

    close(){this.motionGuide.hide();this.root.hidePopover();this.root.hidden=true;this.root.querySelectorAll('video,audio').forEach(media=>media.pause());this.studio.cameraButton?.setAttribute('aria-expanded','false');this.persist();}

    dispose(){this.disposed=true;this.motionGuide.dispose();for(const [type,handler] of this.handlers)this.api.removeEventListener(type,handler);window.removeEventListener('resize',this.viewportChanged);this.sourceVideo.pause();this.root.remove();}

}

