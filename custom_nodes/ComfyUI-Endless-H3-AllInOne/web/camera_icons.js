const path=(d,extra='')=>`<path d="${d}" ${extra}/>`;
const circle=(x,y,r,extra='')=>`<circle cx="${x}" cy="${y}" r="${r}" ${extra}/>`;
const box=(x,y,w,h,extra='')=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="2" ${extra}/>`;
const arrow=(x,y,toX,toY)=>{
    const a=Math.atan2(toY-y,toX-x),point=d=>`${toX-5*Math.cos(a+d)},${toY-5*Math.sin(a+d)}`;
    return path(`M${x},${y} L${toX},${toY} M${point(.6)} L${toX},${toY} L${point(-.6)}`);
};
const camera=(x=23,y=17)=>box(x,y,16,12)+path(`M${x+16},${y+4} l7,-4 v12 l-7,-4 Z`)+circle(x+5,y+6,2);
const person=(x=32,y=16,h=22)=>circle(x,y,h*.16)+path(`M${x},${y+h*.20} v${h*.46} M${x-h*.24},${y+h*.33} h${h*.48} M${x},${y+h*.66} l${-h*.20},${h*.32} M${x},${y+h*.66} l${h*.20},${h*.32}`);
const frame=()=>path('M8 16 V7 H20 M44 7 H56 V16 M56 32 V41 H44 M20 41 H8 V32');
const badge=text=>`<text x="32" y="43" fill="currentColor" stroke="none" text-anchor="middle" font-family="Arial,sans-serif" font-size="9" font-weight="700">${text}</text>`;
const mirror=(svg,left)=>left?`<g transform="translate(64 0) scale(-1 1)">${svg}</g>`:svg;
let clipId=0;

// A local pictogram vocabulary: framing, camera position, path, lens and focus.
export function cameraControlIcon(key,value){
    let drawing='';
    if(key==='shot'){
        const order=['source framing','extreme wide shot','wide shot','full body shot','medium wide shot','medium shot','medium close-up','close-up','extreme close-up','insert shot','macro shot'],i=order.indexOf(value);
        if(i<0)return null;
        const id=`eh3-frame-${++clipId}`,scale=[.9,.35,.65,.95,1.25,1.65,2.1,2.75,4,1,1][i],offset=i<4?24:[25.5,31.5,38,47.5,64][i-4];
        drawing=frame()+`<defs><clipPath id="${id}">${box(10,8,44,32)}</clipPath></defs><g clip-path="url(#${id})"><g transform="translate(32 ${offset||24}) scale(${scale}) translate(-32 -24)">${person(32,14,24)}</g></g>`;
        if(i===0)drawing+=circle(51,10,3,'fill="currentColor" stroke="none"');
        if(i>=9)drawing=frame()+circle(30,22,i===10?9:6)+path('M35 27 L43 35')+(i===9?path('M17 18 h4 M19 16 v4'):circle(30,22,3));
    }else if(key==='angle'){
        if(value==='source angle')drawing=frame()+camera(22,17);
        else if(value==='dutch angle')drawing=`<g transform="rotate(-18 32 24)">${frame()+person(32,15,22)}</g>`;
        else if(value==='first-person POV')drawing=path('M7 24 Q32 1 57 24 Q32 47 7 24 Z')+circle(32,24,8)+circle(32,24,3,'fill="currentColor" stroke="none"');
        else if(value==='object POV')drawing=box(24,17,16,16)+arrow(10,25,22,25)+path('M27 17 l5,-6 l8,6');
        else if(value==='over-the-shoulder')drawing=circle(17,26,7)+path('M5 43 Q17 28 29 43')+person(42,13,21);
        else if(['low angle','high angle','top-down overhead view','bird-eye view','worm-eye view','ground level'].includes(value)){
            drawing=person(38,17,23)+path('M8 42 H56');
            const y=value==='low angle'?32:value==='worm-eye view'||value==='ground level'?38:value==='high angle'?12:6;
            drawing+=box(8,y-4,12,8)+arrow(22,y,31,value==='ground level'?38:22);
            if(value==='bird-eye view')drawing+=path('M8 9 l6,-5 l6,5');
        }else{
            const az={'eye level':0,'front left three-quarter':-.8,'front right three-quarter':.8,'left side profile':-1.57,'right side profile':1.57,'rear view':3.14}[value];
            if(az===undefined)return null;
            const x=32+Math.sin(az)*21,y=24+Math.cos(az)*14;
            drawing='<ellipse cx="32" cy="24" rx="22" ry="15" opacity=".35" stroke-dasharray="2 4"/>'+circle(32,24,5)+circle(x,y,4,'fill="currentColor"')+path(`M${x},${y} L32,24`)+path('M27 16 L32 12 L37 16');
        }
    }else if(key==='movement'){
        const left=/left|counterclockwise/.test(value);
        if(value==='static camera')drawing=camera()+path('M31 29 V34 M31 34 L20 43 M31 34 L42 43')+box(7,5,12,11)+path('M10 5 V3 Q13 -1 16 3 V5');
        else if(/pan/.test(value))drawing=mirror(camera()+path('M14 34 Q32 46 50 34')+arrow(43,39,50,34)+(value.startsWith('whip')?path('M5 14 H17 M3 19 H14'):''),left);
        else if(/tilt/.test(value))drawing=camera(12,17)+path('M47 8 Q59 24 47 40')+(value.endsWith('up')?arrow(53,18,47,8):arrow(53,30,47,40));
        else if(value==='slow dolly in'||value==='slow dolly out')drawing=person(47,10,20)+camera(10,24)+path('M5 40 L41 31 M13 45 L49 36')+(value.endsWith('in')?arrow(26,23,42,14):arrow(42,14,26,23));
        else if(/^dolly (left|right)$/.test(value)||value==='smooth tracking shot')drawing=mirror(camera(23,8)+path('M9 32 H55 M9 38 H55 M17 30 V40 M47 30 V40')+arrow(15,44,49,44)+(value==='smooth tracking shot'?person(9,8,14):''),left);
        else if(/crane|jib|aerial/.test(value)){
            drawing=path('M10 42 H29 M19 42 V25 L44 9')+circle(19,25,3)+box(40,5,14,9);
            drawing+=value==='crane over the head'?path('M30 20 Q41 1 58 18 L53 15 M58 18 V12'):value==='aerial pullback'?arrow(41,31,56,14):value.endsWith('down')?arrow(58,9,58,37):arrow(58,37,58,9);
            if(value.startsWith('jib'))drawing+=circle(36,15,2);
        }else if(/orbit|^arc|hero cam|lazy susan/.test(value)){
            drawing=person(32,12,21)+'<ellipse cx="32" cy="31" rx="24" ry="10" opacity=".35"/>';
            drawing+=mirror(path(value.startsWith('arc')?'M32 42 Q55 42 56 31 L51 35 M56 31 L59 36':'M11 25 C-2 45 62 48 55 25 L52 31 M55 25 L60 29'),left);
            if(value.startsWith('360'))drawing+=`<text x="32" y="9" fill="currentColor" stroke="none" font-family="Arial" font-size="9" text-anchor="middle">360°</text>`;
            if(value==='hero cam')drawing+=path('M43 14 L45 9 L47 14 L52 16 L47 18 L45 23 L43 18 L38 16 Z');
            if(value==='lazy susan')drawing=box(25,14,14,18)+path('M25 14 L32 9 L39 14')+path('M12 29 C-2 46 63 46 53 27 L51 33 M53 27 L59 30');
        }else if(value.startsWith('camera roll'))drawing=mirror(`<g transform="rotate(20 32 24)">${frame()}</g>`+path('M16 6 C39 -5 62 15 50 36 L51 29 M50 36 L57 34'),left);
        else if(/zoom|super dolly/.test(value)){
            const out=value.endsWith('out');drawing=circle(29,21,12)+path('M38 30 L49 41 M23 21 H35')+(out?'':path('M29 15 V27'));
            if(value.startsWith('dolly zoom'))drawing+=path('M5 42 H27 M10 38 V46 M22 38 V46');
            if(value.startsWith('rapid')||value.startsWith('crash')||value.startsWith('super'))drawing+=path('M48 7 L43 17 H49 L43 27');
            if(value==='yoyo zoom')drawing+=path('M4 11 H15 L11 7 M15 11 L11 15 M58 34 H47 L51 30 M47 34 L51 38');
        }else if(value==='subtle handheld')drawing=camera()+path('M8 14 Q3 24 8 34 M55 14 Q60 24 55 34 M17 34 L22 40 H43 L48 34');
        else if(value==='head tracking')drawing=frame()+circle(32,22,8)+path('M20 22 H25 M39 22 H44 M32 10 V15 M32 29 V34');
        else if(value==='snorricam')drawing=person(32,11,27)+box(24,25,16,10)+path('M13 20 L24 30 M51 20 L40 30');
        else if(value==='car grip'||value==='car chasing'){
            drawing=path('M9 31 V23 H15 L21 15 H43 L49 23 H55 V31 Z')+circle(18,33,4)+circle(46,33,4)+path('M22 16 L19 23 H45 L42 16');
            drawing+=value==='car grip'?box(29,5,10,7)+path('M34 12 V16'):arrow(14,43,50,43);
        }else if(value==='robo arm')drawing=path('M11 42 H33 M22 42 V32 L37 20 L25 11 H44')+circle(22,32,3)+circle(37,20,3)+circle(25,11,3)+box(44,6,12,9);
        else if(value==='wiggle')drawing=camera()+path('M5 9 Q10 2 15 9 T25 9 M39 39 Q44 32 49 39 T59 39');
        else if(value==='FPV drone')drawing=path('M21 16 L43 32 M21 32 L43 16')+circle(19,14,7)+circle(45,14,7)+circle(19,34,7)+circle(45,34,7)+box(26,19,12,10);
        else if(value==='flying cam transition')drawing=path('M5 38 C17 35 12 12 32 12 S47 31 58 9 L52 12 M58 9 V16')+camera(21,27);
        else if(value.startsWith('through object'))drawing=path('M18 43 V7 H48 V43 M23 43 V12 H43 V43')+(value.endsWith('in')?arrow(5,25,57,25):arrow(57,25,5,25));
        else return null;
    }else if(key==='lens'){
        if(value==='fisheye')drawing=circle(32,24,19)+path('M16 12 Q32 25 48 12 M16 36 Q32 23 48 36 M23 7 Q35 24 23 41 M41 7 Q29 24 41 41');
        else {const mm=Number.parseInt(value);drawing=circle(32,21,16)+circle(32,21,10)+path('M27 12 L37 12 L42 21 L37 30 L27 30 L22 21 Z')+badge(Number.isFinite(mm)?`${mm}mm`:'AUTO');}
    }else if(key==='focus'){
        if(value==='source')drawing=frame()+circle(32,24,9)+circle(32,24,3);
        else if(value==='face')drawing=frame()+circle(32,21,8)+path('M20 38 Q32 27 44 38');
        else if(value==='deep'||value==='shallow')drawing=person(23,18,20)+person(43,12,16)+(value==='shallow'?circle(43,20,13,'opacity=".35" stroke-dasharray="1 4"'):path('M8 7 H55 M8 43 H55'));
        else drawing=circle(13,25,8)+circle(34,20,5,'opacity=".6"')+circle(52,16,3,'opacity=".35"')+(value==='near to far'?arrow(12,41,53,41):arrow(53,41,12,41));
    }else if(key==='speed'){
        const i=['very slow','slow','moderate','fast','very fast'].indexOf(value);if(i<0)return null;
        const angle=-Math.PI+(i/4)*Math.PI;drawing=path('M10 37 A22 22 0 0 1 54 37')+path(`M32 37 L${32+Math.cos(angle)*18} ${37+Math.sin(angle)*18}`)+circle(32,37,3,'fill="currentColor"');
        for(let n=0;n<5;n++)drawing+=box(13+n*8,42,5,2,`fill="currentColor" opacity="${n<=i?1:.2}" stroke="none"`);
    }else if(key==='easing'){
        const curves={'linear':'M10 37 L54 9','ease in':'M10 37 Q47 37 54 9','ease out':'M10 37 Q17 9 54 9','ease in out':'M10 37 C32 37 32 9 54 9','snap settle':'M10 37 L21 11 Q24 5 31 9 H54'};
        if(!curves[value])return null;drawing=path('M7 6 V41 H58','opacity=".3"')+path(curves[value],'stroke-width="2.6"')+circle(10,37,2,'fill="currentColor"')+circle(54,9,2,'fill="currentColor"');
    }else return null;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 48" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${drawing}</svg>`;
}
