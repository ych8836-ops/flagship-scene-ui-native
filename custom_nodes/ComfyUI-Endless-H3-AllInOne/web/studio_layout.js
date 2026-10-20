function element(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
export class StudioDockLayout {
    constructor(root,workspace,parts,properties,save){
        const key='flagship_scene_ui_layout';
        let stored={};try{stored=JSON.parse(localStorage.getItem(key)||'{}');}catch{}
        const saved=properties.endless_dock_layout||stored;
        const ui=saved&&typeof saved==='object'&&!Array.isArray(saved)?saved:{};
        properties.endless_dock_layout=ui;
        const persist=()=>{try{localStorage.setItem(key,JSON.stringify(ui));}catch{}save();};
        this.root=root;this.parts=parts;this.panels=[];
        workspace.classList.add('eh3-dock-stage');
        const tools=element('div',undefined,'eh3-workspace-tools');
        tools.append(element('span','사이드 조절바로 패널 비율 조절'));
        const reset=element('button','기본 배치');reset.type='button';reset.dataset.dockReset='';tools.append(reset);workspace.before(tools);this.tools=tools;
        const labels={'1':'설정','2':'미리보기·아웃풋','3':'씬·클립 연결도'};
        for(const id of ['1','2','3']){
            const panel=element('section',undefined,'eh3-pane');panel.dataset.studioPanel=id;panel.setAttribute('aria-label',`${id}패널 ${labels[id]}`);
            const header=element('header',undefined,'eh3-pane-header');panel.append(header);
            const grip=element('button',`⠿ ${id} · ${labels[id]}`,'eh3-pane-grip');grip.type='button';grip.draggable=true;grip.dataset.panelDrag=id;grip.setAttribute('aria-label',`${id}패널 이동`);header.append(grip);
            const menu=element('details',undefined,'eh3-dock-menu');header.append(menu);menu.append(element('summary','배치'));
            const fields=element('div',undefined,'eh3-dock-fields');menu.append(fields);
            const target=element('select');target.dataset.dockTarget=id;target.setAttribute('aria-label','기준 패널');
            for(const other of ['1','2','3'].filter(value=>value!==id)){const option=element('option',`${other} · ${labels[other]}`);option.value=other;target.append(option);}fields.append(target);
            const edge=element('select');edge.dataset.dockEdge=id;edge.setAttribute('aria-label','배치 위치');for(const [value,label] of Object.entries({left:'왼쪽',right:'오른쪽',top:'위',bottom:'아래'})){const option=element('option',label);option.value=value;edge.append(option);}fields.append(edge);
            const apply=element('button','이동');apply.type='button';apply.dataset.dockApply=id;fields.append(apply);
            const max=element('button','확대');max.type='button';max.dataset.panelMax=id;header.append(max);
            const body=element('div',undefined,'eh3-pane-body');body.append(parts[id]);panel.append(body);
            workspace.append(panel);this.panels.push(panel);
        }
        this.controller=createDockWorkspace(root,ui,persist,text=>{const status=root.querySelector('.eh3-status');if(status)status.textContent=text;});
        this.controller.render();
    }
    dispose(){this.controller.dispose();this.tools.remove();}
}
  function createDockWorkspace(root,ui,persist,status){
    const stage=root.querySelector('.eh3-dock-stage');
    const splitterSize=32;root.style.setProperty('--dock-divider-size', `${splitterSize}px`);
    const panels=Object.fromEntries(Array.from(root.querySelectorAll('[data-studio-panel]'),panel=>[panel.dataset.studioPanel,panel]));
    const ids=['1','2','3'],defaultTree=()=>({axis:'x',ratio:.25,a:'1',b:{axis:'x',ratio:.61,a:'2',b:'3'}});
    const copy=value=>JSON.parse(JSON.stringify(value));
    function leaves(node){return typeof node==='string'?[node]:node?[...leaves(node.a),...leaves(node.b)]:[];}
    function valid(node){if(typeof node==='string')return ids.includes(node);return !!node&&['x','y'].includes(node.axis)&&Number.isFinite(node.ratio)&&node.ratio>0&&node.ratio<1&&valid(node.a)&&valid(node.b);}
    if(!valid(ui.dock)||leaves(ui.dock).sort().join('')!=='123')ui.dock=defaultTree();
    const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
    if(ui.sizing!=='flex'){
      const oldWidth=node=>typeof node==='string'?Math.max(1,Number(ui.panelWidths?.[node])||1):node.axis==='x'?oldWidth(node.a)+oldWidth(node.b)+splitterSize:Math.max(oldWidth(node.a),oldWidth(node.b));
      const migrate=node=>{if(typeof node==='string')return;if(node.axis==='x'&&ui.panelWidths){const a=oldWidth(node.a),b=oldWidth(node.b);node.ratio=clamp(a/(a+b),.1,.9);}migrate(node.a);migrate(node.b);};
      migrate(ui.dock);ui.sizing='flex';
    }
    for(const key of ['panelWidths','panelHeights','resultsHeight','previewHeight','viewportWidth','viewportHeight'])delete ui[key];
    if(!ids.includes(ui.focusPanel))ui.focusPanel=null;
    const refs=[];let moving=null;
    const minWidth=node=>typeof node==='string'?({'1':210,'2':300,'3':230}[node]):node.axis==='x'?minWidth(node.a)+minWidth(node.b)+splitterSize:Math.max(minWidth(node.a),minWidth(node.b));
    const minHeight=node=>typeof node==='string'?220:node.axis==='y'?minHeight(node.a)+minHeight(node.b)+splitterSize:Math.max(minHeight(node.a),minHeight(node.b));
    function apply(){
      for(const id of ids){panels[id].style.minWidth=`${minWidth(id)}px`;const max=root.querySelector(`[data-panel-max="${id}"]`);max.textContent=ui.focusPanel===id?'복원':id==='2'?'단독 보기':'확대';max.setAttribute('aria-pressed',String(ui.focusPanel===id));}
      for(const ref of refs){
        ref.element.style.minWidth=`${minWidth(ref.node)}px`;ref.element.style.minHeight=`${minHeight(ref.node)}px`;
        ref.a.style.flex=`${ref.node.ratio} 1 0px`;ref.b.style.flex=`${1-ref.node.ratio} 1 0px`;
        for(const [host,child] of [[ref.a,ref.node.a],[ref.b,ref.node.b]]){host.style.minWidth=`${minWidth(child)}px`;host.style.minHeight=ref.node.axis==='y'?`${minHeight(child)}px`:'0';}
        ref.separator.setAttribute('aria-valuenow',String(Math.round(ref.node.ratio*100)));
      }
    }
    function dragResize(handle,start,move,finish){let drag=null;
      handle.addEventListener('pointerdown',event=>{if(handle.disabled||(event.button!==undefined&&event.button!==0))return;event.preventDefault();drag=start(event);handle.setPointerCapture(event.pointerId);handle.classList.add('dragging');});
      handle.addEventListener('pointermove',event=>{if(drag)move(event,drag);});
      const stop=()=>{if(!drag)return;drag=null;handle.classList.remove('dragging');finish();};
      handle.addEventListener('pointerup',stop);handle.addEventListener('pointercancel',stop);handle.addEventListener('lostpointercapture',stop);
    }
    function updateSplit(node,delta,rect){
      if(node.axis!=='x')return;
      const size=Math.max(1,rect.cssWidth-splitterSize),move=delta*rect.cssWidth/Math.max(1,rect.width);
      const minimum=minWidth(node.a)/size,maximum=1-minWidth(node.b)/size;
      if(minimum>maximum)return;
      node.ratio=clamp(rect.ratio+move/size,minimum,maximum);apply();
    }
    function measure(element,node){const r=element.getBoundingClientRect();return {width:r.width,cssWidth:element.clientWidth,ratio:node.ratio};}
    function build(node){
      if(typeof node==='string')return panels[node];
      const element=document.createElement('div');element.className='eh3-dock-split';element.dataset.axis=node.axis;
      const a=document.createElement('div'),b=document.createElement('div');a.className=b.className='eh3-dock-host';
      const separator=document.createElement('button');separator.type='button';separator.className='eh3-dock-separator';separator.dataset.axis=node.axis;separator.setAttribute('role','separator');separator.setAttribute('aria-label',node.axis==='x'?'좌우 패널 너비 조절':'패널 경계 · 높이 자동 채움');separator.setAttribute('aria-orientation',node.axis==='x'?'vertical':'horizontal');separator.setAttribute('aria-valuemin','10');separator.setAttribute('aria-valuemax','90');
      separator.disabled=node.axis==='y';
      a.append(build(node.a));b.append(build(node.b));element.append(a,separator,b);refs.push({node,element,a,b,separator});
      dragResize(separator,event=>({x:event.clientX,rect:measure(element,node)}),(event,drag)=>updateSplit(node,event.clientX-drag.x,drag.rect),persist);
      separator.addEventListener('keydown',event=>{if(separator.disabled)return;const sign=event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:0;if(!sign)return;event.preventDefault();updateSplit(node,sign*(event.shiftKey?40:15),measure(element,node));persist();});
      separator.addEventListener('dblclick',()=>{if(separator.disabled)return;node.ratio=.5;apply();persist();});
      return element;
    }
    function render(){refs.length=0;const active=ui.focusPanel||ui.dock;const content=build(active);if(ui.focusPanel){const stash=document.createElement('div');stash.hidden=true;stash.className='eh3-panel-stash';ids.filter(id=>id!==ui.focusPanel).forEach(id=>stash.append(panels[id]));stage.replaceChildren(content,stash);}else stage.replaceChildren(content);apply();}
    function remove(node,id){if(typeof node==='string')return node===id?null:node;const a=remove(node.a,id),b=remove(node.b,id);return a&&b?{...node,a,b}:a||b;}
    function insert(node,target,source,edge){if(typeof node==='string'){if(node!==target)return node;return {axis:['left','right'].includes(edge)?'x':'y',ratio:.5,a:['left','top'].includes(edge)?source:node,b:['left','top'].includes(edge)?node:source};}return {...node,a:insert(node.a,target,source,edge),b:insert(node.b,target,source,edge)};}
    function dock(source,target,edge){if(source===target||!ids.includes(source)||!ids.includes(target)||!['left','right','top','bottom'].includes(edge))return;ui.dock=insert(remove(ui.dock,source),target,source,edge);ui.focusPanel=null;render();persist();status(`${source}패널을 ${target}패널 ${ {left:'왼쪽',right:'오른쪽',top:'위',bottom:'아래'}[edge]}에 배치했습니다.`);}
    function clearDrop(){ids.forEach(id=>panels[id].removeAttribute('data-drop-side'));}
    function dropSide(event,panel){const box=panel.getBoundingClientRect(),x=clamp((event.clientX-box.left)/Math.max(1,box.width),0,1),y=clamp((event.clientY-box.top)/Math.max(1,box.height),0,1);return [['left',x],['right',1-x],['top',y],['bottom',1-y]].sort((a,b)=>a[1]-b[1])[0][0];}
    for(const id of ids){
      const panel=panels[id],grip=root.querySelector(`[data-panel-drag="${id}"]`),target=root.querySelector(`[data-dock-target="${id}"]`),edge=root.querySelector(`[data-dock-edge="${id}"]`);
      target.value=id==='1'?'2':'1';edge.value='left';
      grip.addEventListener('dragstart',event=>{moving=id;if(event.dataTransfer){event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',id);}});
      grip.addEventListener('dragend',()=>{moving=null;clearDrop();});
      panel.addEventListener('dragover',event=>{if(!moving||moving===id)return;event.preventDefault();clearDrop();panel.dataset.dropSide=dropSide(event,panel);if(event.dataTransfer)event.dataTransfer.dropEffect='move';});
      panel.addEventListener('drop',event=>{if(!moving||moving===id)return;event.preventDefault();const source=moving,side=dropSide(event,panel);moving=null;clearDrop();dock(source,id,side);});
      root.querySelector(`[data-dock-apply="${id}"]`).addEventListener('click',()=>{panel.querySelector('.eh3-dock-menu').open=false;dock(id,target.value,edge.value);});
      root.querySelector(`[data-panel-max="${id}"]`).addEventListener('click',()=>{ui.focusPanel=ui.focusPanel===id?null:id;render();persist();});
    }
    root.querySelector('[data-dock-reset]').addEventListener('click',()=>{ui.dock=copy(defaultTree());ui.focusPanel=null;render();persist();status('기본 1 · 2 · 3패널 배치로 복원했습니다.');});
    return {render,dispose(){stage.querySelectorAll('video').forEach(media=>media.pause());}};
  }
