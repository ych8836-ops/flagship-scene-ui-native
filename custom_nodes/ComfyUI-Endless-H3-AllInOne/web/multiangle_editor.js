import {defaultPath,normalizePath,angleSweep} from './multiangle_math.js?v=precise_angles_20261017_v2';

const style=`
.fma{--fma-accent:#a5deca;background:#2b2521;border:1px solid #63594f;border-radius:12px;padding:12px;margin:12px 0;color:#f2ece5;font:calc(13px * var(--font-scale,1))/1.4 'Noto Sans KR',sans-serif;box-sizing:border-box}
.fma *{box-sizing:border-box}.fma [hidden]{display:none!important}.fma-head,.fma-row{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.fma-head{justify-content:space-between;margin-bottom:9px}.fma strong{font-size:1.08em}.fma small{font-size:.85em;color:#c7bfb5}.fma button,.fma select,.fma input[type=number]{background:#454544;color:#f3efea;border:1px solid #696963;border-radius:7px;min-height:30px;padding:4px 8px;font:inherit}.fma button{cursor:pointer}.fma button:hover{border-color:var(--fma-accent)}.fma button.on{background:#a5deca;color:#19382e;border-color:#a5deca}.fma button:disabled{opacity:.45;cursor:default}.fma-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(calc(72px * var(--font-scale,1)),1fr));gap:5px;margin:8px 0}.fma-grid button{padding:6px 3px}.fma-grid b{display:block;font-size:1.15em}.fma-grid small{display:block;font-size:.8em;color:inherit;opacity:.8}.fma-fields{display:grid;gap:8px;grid-template-columns:repeat(3,minmax(0,1fr));margin:10px 0}.fma-field{display:flex;flex-direction:column;gap:5px;min-width:0}.fma-field input[type=number]{width:100%;font-variant-numeric:tabular-nums;font-size:1.15em}.fma input[type=range]{width:100%;accent-color:var(--fma-accent);height:20px;cursor:pointer}.fma-points{display:flex;gap:6px;overflow-x:auto;scrollbar-width:auto;padding:5px 0 10px}.fma-points::-webkit-scrollbar{height:12px}.fma-points::-webkit-scrollbar-thumb{background:#94bcae;border:2px solid #2b2521;border-radius:10px}.fma-points button{min-width:94px;text-align:left;white-space:nowrap;flex-shrink:0}.fma-points small{display:block;color:inherit}.fma details{margin-top:8px;border-top:1px solid #554c43;padding-top:8px}.fma summary{cursor:pointer}.fma details .fma-row{margin-top:7px}.fma-note{display:block;margin:8px 0 0}.fma-error{color:#ffb29c;min-height:0}.fma select{max-width:100%}.fma .fma-time{width:80px}.fma .fma-wide{flex:1}.fma details input[type=number]{width:65px}
`;
const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
const button=(text,fn)=>{const b=el('button',text);b.type='button';b.onclick=fn;return b;};
const clone=v=>JSON.parse(JSON.stringify(v));

// A compact value editor, shared by the standalone node and camera directing.
// It never submits generation or changes any shared model settings.
export class MultiAngleEditor{
    constructor(host,value,onChange,{duration=5,onError=()=>{}}={}){
        if(!document.getElementById('flagship-multiangle-style')){const s=el('style');s.id='flagship-multiangle-style';s.textContent=style;document.head.append(s);}
        this.path=normalizePath(value||{...defaultPath(),enabled:false});this.onChange=onChange;this.onError=onError;this.duration=duration;this.selected=0;
        this.root=el('section');this.root.className='fma';host.append(this.root);this.render();
    }
    change(){const p=normalizePath(this.path);this.path.keyframes.sort((a,b)=>a.t-b.t);this.onChange(clone(p));}
    run(fn){try{fn();this.error.textContent='';}catch(e){this.error.textContent=e.message;this.onError(e);}}
    render(){
        this.root.replaceChildren();const head=el('div');head.className='fma-head';head.append(el('strong','빠른 앵글 · MultiAngle'));
        const toggle=button(this.path.enabled?'ON':'OFF',()=>{this.path.enabled=!this.path.enabled;this.change();this.render();});toggle.classList.toggle('on',this.path.enabled);toggle.setAttribute('aria-pressed',String(this.path.enabled));head.append(toggle);this.root.append(head);
        const content=el('div');content.hidden=!this.path.enabled;this.root.append(content);
        this.error=el('small');this.error.className='fma-error';this.root.append(this.error);
        const grid=el('div');grid.className='fma-grid';
        for(const [name,rotate,vertical] of [['정면',0,0],['좌 15°',-15,0],['좌 30°',-30,0],['좌 45°',-45,0],['우 15°',15,0],['우 30°',30,0],['우 45°',45,0],['좌 측면',-90,0],['우 측면',90,0],['후면',180,0],['하이',0,30],['로우',0,-30]]){
            const b=button('',()=>this.run(()=>{const k=this.path.keyframes[this.selected];k.rotate=rotate;k.vertical=vertical;this.change();this.render();}));b.append(el('b',`${rotate}°`),el('small',name));b.title=`수평 ${rotate}°, 수직 ${vertical}° · 선택 앵글에 적용`;grid.append(b);
        }
        content.append(grid);const mode=el('div');mode.className='fma-row';
        mode.append(button('고정 앵글',()=>{const k=this.path.keyframes[this.selected];this.path.keyframes=[{...k,t:0}];this.selected=0;this.change();this.render();}),button('줌 인',()=>this.motion('in')),button('줌 아웃',()=>this.motion('out')),button('좌 → 우',()=>this.motion('orbit')),button('원본 구도',()=>{this.path.keyframes=[{t:0,rotate:0,vertical:0,zoom:5}];this.selected=0;this.change();this.render();}));content.append(mode);
        const points=el('div');points.className='fma-points';
        this.path.keyframes.forEach((k,i)=>{const b=button('',()=>{this.selected=i;this.render();});b.classList.toggle('on',i===this.selected);b.append(el('b',`${i+1} · ${(k.t*this.duration).toFixed(2)}s`),el('small',`${k.rotate.toFixed(1)}° / ${k.vertical.toFixed(1)}°`),el('small',`줌 ${k.zoom.toFixed(1)}`));points.append(b);});content.append(points);
        const k=this.path.keyframes[this.selected],fields=el('div');fields.className='fma-fields';
        for(const [key,label,min,max,step] of [['rotate','수평 °',-720,720,.1],['vertical','수직 °',-90,90,.1],['zoom','줌',0,10,.1]]){
            const box=el('label');box.className='fma-field';box.append(el('span',label));const number=el('input'),range=el('input');number.type='number';range.type='range';
            for(const input of [number,range]){input.min=min;input.max=max;input.step=step;input.value=k[key];input.setAttribute('aria-label',label);}
            const update=input=>this.run(()=>{const v=Number(input.value);if(!Number.isFinite(v)||input.value.trim()==='')return;const previous=k[key];k[key]=v;try{this.change();}catch(e){k[key]=previous;throw e;}number.value=range.value=v;});
            number.onchange=()=>update(number);range.oninput=()=>update(range);range.onchange=()=>this.render();box.append(number,range);fields.append(box);
        }
        content.append(fields);const tools=el('div');tools.className='fma-row';
        const time=el('input');time.type='number';time.min=0;time.max=this.duration;time.step=.01;time.value=(k.t*this.duration).toFixed(3);time.className='fma-time';time.setAttribute('aria-label','선택 앵글 시간 · 초');
        time.onchange=()=>this.run(()=>{const next={...k,t:Number(time.value)/this.duration};const values=this.path.keyframes.map((v,i)=>i===this.selected?next:v);const p=normalizePath({...this.path,keyframes:values});this.path=p;this.selected=p.keyframes.findIndex(v=>v.t===next.t);this.change();this.render();});
        tools.append(el('span','시간'),time,el('small','초'),button('+ 앵글',()=>this.run(()=>this.addPoint())),button('삭제',()=>{if(this.path.keyframes.length===1)return;this.path.keyframes.splice(this.selected,1);this.selected=Math.min(this.selected,this.path.keyframes.length-1);this.change();this.render();}));content.append(tools);
        const details=el('details'),summary=el('summary','각도 분할 · 이동 방식');details.append(summary);
        const sweep=el('div');sweep.className='fma-row';const start=el('input'),end=el('input'),step=el('select');start.type=end.type='number';start.step=end.step=.1;start.value=-45;end.value=45;
        for(const [n,label] of [[start,'시작 각도'],[end,'끝 각도']])n.setAttribute('aria-label',label);
        for(const v of [.1,1,5,10,15,30,45,90]){const o=el('option',v+'° 간격');o.value=v;o.selected=v===15;step.append(o);}step.setAttribute('aria-label','각도 분할 간격');
        sweep.append(el('small','수평'),start,el('small','→'),end,step,button('분할 적용',()=>this.run(()=>{this.path.keyframes=angleSweep(k,Number(start.value),Number(end.value),Number(step.value));this.selected=0;this.change();this.render();})));details.append(sweep);
        for(const [key,label,options] of [['zoom_mode','줌 방식',[['dolly','거리 이동'],['optical','광학 줌']]],['interpolation','이동',[['smooth','부드럽게'],['linear','일정 속도']]],['rotation','회전',[['direct','입력한 각도 그대로'],['shortest','최단 경로']]]]){
            const row=el('label');row.className='fma-row';row.append(el('span',label));const select=el('select');for(const [v,l] of options){const o=el('option',l);o.value=v;o.selected=this.path[key]===v;select.append(o);}select.onchange=()=>{this.path[key]=select.value;this.change();};row.append(select);details.append(row);
        }
        const files=el('div');files.className='fma-row';const file=el('input');file.type='file';file.accept='.json,application/json';file.hidden=true;
        file.onchange=async()=>{try{if(file.files[0]){this.path=normalizePath(JSON.parse(await file.files[0].text()));this.path.enabled=true;this.selected=0;this.change();this.render();}}catch(e){this.error.textContent=e.message;}finally{file.value='';}};
        files.append(button('Easy 값 / JSON 불러오기',()=>file.click()),button('JSON 저장',()=>{const blob=new Blob([JSON.stringify(this.path,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='flagship_multiangle.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}),file);details.append(files);content.append(details);
        const note=el('small','ON: 이 구간의 기존 앵글·무빙·프레이밍 대신 숫자 경로 적용. 줌 5 = 원본. 큰 시점 변경의 새 표면은 생성이 필요합니다.');note.className='fma-note';content.append(note);
    }
    motion(kind){
        const k=this.path.keyframes[this.selected],start={...k,t:0},end={...k,t:1};
        if(kind==='in')end.zoom=Math.min(10,k.zoom+2);else if(kind==='out')end.zoom=Math.max(0,k.zoom-2);else{start.rotate=-30;end.rotate=30;}
        this.path.keyframes=[start,end];this.selected=1;this.change();this.render();
    }
    addPoint(){
        const points=this.path.keyframes;let t;
        if(points.length===1)t=points[0].t<1?1:0;
        else if(points.at(-1).t<1)t=1;
        else{let gap=-1;for(let i=1;i<points.length;i++)if(points[i].t-points[i-1].t>gap){gap=points[i].t-points[i-1].t;t=(points[i].t+points[i-1].t)/2;}}
        this.path.keyframes.push({...points[this.selected],t});this.change();this.selected=this.path.keyframes.findIndex(k=>k.t===t);this.render();
    }
    destroy(){this.root.remove();}
}
