import {app} from '../../../scripts/app.js';
import {MultiAngleEditor} from './multiangle_editor.js?v=precise_angles_20261017_v2';

app.registerExtension({
    name:'Flagship.PreciseMultiAngle',
    async beforeRegisterNodeDef(type,data){
        if(data.name!=='FlagshipMultiAngle')return;
        const create=type.prototype.onNodeCreated,configure=type.prototype.onConfigure,remove=type.prototype.onRemoved;
        type.prototype.onNodeCreated=function(){
            const result=create?.apply(this,arguments),node=this;
            const widget=node.widgets.find(w=>w.name==='path_json');
            const host=document.createElement('div');host.style.cssText='overflow:auto;max-height:610px;min-width:0;';
            const hint=document.createElement('small');hint.textContent='Easy MultiAngle params 입력을 연결하면 외부 값이 우선합니다.';hint.style.cssText='display:block;color:#c7bfb5;padding:4px 12px';host.append(hint);
            const area=document.createElement('div');host.append(area);
            const dom=node.addDOMWidget('precise_angles','div',host,{serialize:false,hideOnZoom:false});dom.computeSize=()=>[420,620];
            const original=widget.callback;
            const refresh=()=>{
                try{node.multiAngleEditor?.destroy();area.replaceChildren();const frames=Number(node.widgets.find(w=>w.name==='frames')?.value)||124,fps=Number(node.widgets.find(w=>w.name==='fps')?.value)||24;
                    node.multiAngleEditor=new MultiAngleEditor(area,widget.value,value=>{widget.value=JSON.stringify(value);original?.call(widget,widget.value);node.setDirtyCanvas(true,true);},{duration:Math.max(.01,(frames-1)/fps)});
                }catch(e){area.textContent=e.message;}
            };
            widget.callback=function(){original?.apply(this,arguments);refresh();};
            // Keep the serialized STRING widget; hide only its redundant raw-JSON editor.
            widget.type='converted-widget';widget.computeSize=()=>[0,-4];if(widget.inputEl)widget.inputEl.hidden=true;
            for(const w of node.widgets.filter(w=>['frames','fps'].includes(w.name))){const callback=w.callback;w.callback=function(){callback?.apply(this,arguments);refresh();};}
            node.refreshMultiAngle=refresh;refresh();node.setSize([Math.max(450,node.size[0]),Math.max(725,node.size[1])]);return result;
        };
        type.prototype.onConfigure=function(){const result=configure?.apply(this,arguments);this.refreshMultiAngle?.();return result;};
        type.prototype.onRemoved=function(){this.multiAngleEditor?.destroy();return remove?.apply(this,arguments);};
    }
});
