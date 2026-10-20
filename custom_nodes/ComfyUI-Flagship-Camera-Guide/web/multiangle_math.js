// Easy MultiAngle-compatible numeric paths. No angle-to-label quantization.
export const defaultPath=()=>({version:1,enabled:true,interpolation:'smooth',rotation:'direct',zoom_mode:'optical',keyframes:[
    {t:0,rotate:0,vertical:0,zoom:5}]});
export const neutralPath=raw=>normalizePath(raw).keyframes.every(k=>k.rotate===0&&k.vertical===0&&k.zoom===5);
export const sourceZoomPath=raw=>{const p=normalizePath(raw);return p.zoom_mode==='optical'&&p.keyframes.every(k=>k.rotate===0&&k.vertical===0&&k.zoom>=5)&&p.keyframes.some(k=>k.zoom>5);};
const finite=(v,key)=>{const n=Number(v);if(!Number.isFinite(n))throw Error(`${key}: 유효한 숫자를 입력하세요.`);return n;};
export function normalizePath(raw){
    let p=typeof raw==='string'?JSON.parse(raw):raw;
    if(Array.isArray(p))p={keyframes:p.map((k,i)=>({...k,t:i/Math.max(1,p.length-1)}))};
    if(!p||!Array.isArray(p.keyframes)||!p.keyframes.length)throw Error('앵글을 하나 이상 지정하세요.');
    const keyframes=p.keyframes.map(k=>({t:finite(k.t??0,'시간'),rotate:finite(k.rotate??0,'수평'),vertical:finite(k.vertical??0,'수직'),zoom:finite(k.zoom??5,'줌')})).sort((a,b)=>a.t-b.t);
    for(let i=0;i<keyframes.length;i++){
        const k=keyframes[i];if(k.t<0||k.t>1||k.vertical < -90||k.vertical>90||k.zoom<0||k.zoom>10)throw Error('시간 0~100%, 수직 −90~90°, 줌 0~10 범위로 입력하세요.');
        if(i&&k.t===keyframes[i-1].t)throw Error('앵글마다 서로 다른 시간을 지정하세요.');
    }
    if(!['linear','smooth'].includes(p.interpolation??'smooth')||!['direct','shortest'].includes(p.rotation??'direct'))throw Error('지원하지 않는 경로 방식입니다.');
    if(!['dolly','optical'].includes(p.zoom_mode??'optical'))throw Error('지원하지 않는 줌 방식입니다.');
    return {version:1,enabled:p.enabled!==false,interpolation:p.interpolation??'smooth',rotation:p.rotation??'direct',zoom_mode:p.zoom_mode??'optical',keyframes};
}
export function samplePath(raw,t){
    const p=normalizePath(raw),points=p.keyframes.map(k=>({...k}));
    if(p.rotation==='shortest')for(let i=1;i<points.length;i++){
        let d=(points[i].rotate-points[i-1].rotate)%360;if(d>180)d-=360;if(d < -180)d+=360;points[i].rotate=points[i-1].rotate+d;
    }
    if(points.length===1||t<=points[0].t)return {...points[0]};
    if(t>=points.at(-1).t)return {...points.at(-1)};
    const b=points.findIndex(k=>k.t>t),a=points[b-1];let f=(t-a.t)/(points[b].t-a.t);if(p.interpolation==='smooth')f=f*f*(3-2*f);
    return {t,rotate:a.rotate+(points[b].rotate-a.rotate)*f,vertical:a.vertical+(points[b].vertical-a.vertical)*f,zoom:a.zoom+(points[b].zoom-a.zoom)*f};
}
export const radiusScale=z=>2**((5-z)/5);
export function slicePathFrames(raw,total,start,end){
    const p=normalizePath(raw),keyframes=[];
    for(let i=start;i<end;i++)keyframes.push({...samplePath(p,i/Math.max(1,total-1)),t:(i-start)/Math.max(1,end-start-1)});
    return {...p,interpolation:'linear',keyframes};
}
export function angleSweep(current,start,end,step){
    for(const [key,value] of Object.entries({start,end,step}))finite(value,key);
    if(step<=0||Math.ceil(Math.abs(end-start)/step)>10000)throw Error('간격은 양수이며 한 번에 최대 10,001개 앵글입니다.');
    const sign=end>=start?1:-1,angles=[];
    for(let i=0;i<=Math.floor(Math.abs(end-start)/step+1e-9);i++)angles.push(start+sign*i*step);
    if(Math.abs(angles.at(-1)-end)>1e-7)angles.push(end);
    return angles.map((rotate,i)=>({...current,rotate,t:i/Math.max(1,angles.length-1)}));
}
export function numericCameraPrompt(raw,count){
    const p=normalizePath(raw),duration=(count-1)/24;
    // The full path drives the guide. Avoid thousands of redundant lines in the text encoder.
    const promptKeys=p.keyframes.length<=9?p.keyframes:Array.from({length:9},(_,i)=>({...samplePath(p,i/8),t:i/8}));
    const keys=promptKeys.map(k=>`${(k.t*duration).toFixed(3)}s: camera azimuth ${k.rotate.toFixed(3)} degrees, elevation ${k.vertical.toFixed(3)} degrees, ${p.zoom_mode==='optical'?'focal-length':'working-distance'} multiplier ${(p.zoom_mode==='optical'?1/radiusScale(k.zoom):radiusScale(k.zoom)).toFixed(4)}`).join('\n');
    return `subject_definitions:
<Subject 1> is the original principal performer in <Video 1>, preserving identity, wardrobe, body proportions and action timing.
<Video 1> defines the existing scene and performance. <Audio 1> is its synchronized original soundtrack.

summary:
[reference generation + audio reuse] Rephotograph the original performance along the numeric camera path supplied by the depth-control video.

retention_analysis:
<Video 1>: partially_preserved - retain cast, setting, lighting and action timing; change camera only.
<Audio 1>: fully_copy - preserve original sound and timing.

detailed_description:
[Shot 1] One continuous ${(count/24).toFixed(3)}-second shot. Zero azimuth and elevation match the source camera. Positive azimuth moves the camera toward screen-right around the subject; positive elevation raises the camera. These are camera movements, never instructions to turn the performer. ${p.zoom_mode==='optical'?'Change focal length for zoom without changing the camera radius.':'Keep the lens perspective fixed; distance changes are physical dolly travel, not digital zoom.'}
NUMERIC KEYFRAMES (the last frame occurs at ${(duration).toFixed(3)}s):
${keys}
Follow the per-frame depth guide with ${p.interpolation==='smooth'?'smooth acceleration and deceleration at keyframes':'linear travel between keyframes'}. ${p.rotation==='direct'?'Respect signed unwrapped angles, including complete 360-degree circuits.':'Take the shortest angular route between adjacent keyframes.'}
Preserve source performance speed and exact syllable timing. Keep naturally hidden faces hidden. If the mouth is visible, synchronize it to <Audio 1>. Maintain coherent perspective, parallax and occlusions; no body pivot replacing camera orbit, cuts, duplicated bodies or unrelated scene changes.

overall_soundscape:
Copy <Audio 1> at its original timing. Add no dialogue or sound.

non_diegetic_music:
Keep only music already in <Audio 1>.`;
}
