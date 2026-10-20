import * as THREE from './vendor/build/three.module.js';
import {createCameraMuse} from './camera_muse.js?v=lowpoly_20261017';

const ease=t=>{t=THREE.MathUtils.clamp(t,0,1);return t*t*(3-2*t);};
const mix=THREE.MathUtils.lerp;

// Repose the same low-poly character; these meshes never enter a generation graph.
export class StudioActionActor {
    constructor(){
        this.root=new THREE.Group();this.model=createCameraMuse();this.root.add(this.model);
        this.materials={mint:new THREE.MeshStandardMaterial({color:'#9adfc7',roughness:.55}),dark:new THREE.MeshStandardMaterial({color:'#36413f',roughness:.6}),ivory:new THREE.MeshStandardMaterial({color:'#f5eedc',roughness:.7}),gold:new THREE.MeshStandardMaterial({color:'#c7a47a',roughness:.5}),red:new THREE.MeshStandardMaterial({color:'#d78d82',roughness:.65})};
        this.arms=[];
        for(const side of [-1,1]){
            const parts=this.model.children.filter(o=>['Puff sleeve','Upper arm','Elbow','Lower arm','Hand'].includes(o.name)&&Math.sign(o.position.x)===side);
            const upper=new THREE.Group(),fore=new THREE.Group();upper.position.set(side*.245,1.31,0);fore.position.set(side*.302,1.06,.015);this.model.add(upper,fore);this.model.updateMatrixWorld(true);
            for(const part of parts)(['Lower arm','Hand'].includes(part.name)?fore:upper).attach(part);
            upper.attach(fore);this.arms.push({upper,fore});
        }
        this.head=new THREE.Group();this.head.position.set(0,1.47,0);this.model.add(this.head);this.model.updateMatrixWorld(true);
        for(const part of [...this.model.children])if(['Face','Hair crown','Back hair','Wavy hair lock','Swept fringe','Side fringe','Soft eyelash','Earring','Smile'].includes(part.name))this.head.attach(part);
        this.props={};
        const prop=name=>{const group=new THREE.Group();group.name=name;this.props[name]=group;this.root.add(group);return group;};
        const box=(parent,x,y,z,w,h,d,mat)=>{const obj=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),mat);obj.position.set(x,y,z);obj.castShadow=true;obj.receiveShadow=true;parent.add(obj);return obj;};
        const circle=(parent,r,tube,mat)=>{const obj=new THREE.Mesh(new THREE.TorusGeometry(r,tube,6,40),mat);parent.add(obj);return obj;};
        const {mint,dark,ivory,gold,red}=this.materials;
        const slate=prop('generate');slate.position.set(0,1.1,.43);
        box(slate,0,0,0,.58,.32,.045,dark);box(slate,0,-.09,.027,.43,.007,.008,ivory);
        for(let i=0;i<3;i++)box(slate,-.17+i*.17,.045,.027,.12,.007,.008,mint);
        this.clap=new THREE.Group();this.clap.position.set(-.29,.18,0);slate.add(this.clap);
        box(this.clap,.29,0,0,.58,.067,.05,ivory);
        for(let i=0;i<5;i++){const stripe=box(this.clap,.06+i*.116,0,.027,.06,.068,.004,dark);stripe.rotation.z=-.45;}
        const clock=prop('schedule');clock.position.set(0,1.17,.43);circle(clock,.22,.023,gold);
        const face=new THREE.Mesh(new THREE.CircleGeometry(.202,40),ivory);clock.add(face);
        this.handHour=new THREE.Group();this.handMinute=new THREE.Group();clock.add(this.handHour,this.handMinute);
        box(this.handHour,0,.052,.015,.014,.12,.012,dark);box(this.handMinute,0,.085,.02,.01,.18,.01,mint);
        const stop=prop('stop');stop.position.set(.36,1.26,.43);box(stop,0,0,0,.19,.19,.035,red);
        const frame=prop('upscale');frame.position.set(0,1.16,.42);
        box(frame,0,0,0,.49,.36,.03,dark);box(frame,0,0,.021,.43,.30,.012,ivory);
        const mountain=new THREE.Mesh(new THREE.ConeGeometry(.15,.18,3),mint);mountain.position.set(-.06,-.05,.04);mountain.rotation.x=Math.PI/2;frame.add(mountain);
        const sun=new THREE.Mesh(new THREE.SphereGeometry(.043,12,6),gold);sun.position.set(.12,.08,.04);frame.add(sun);
        this.corners=new THREE.Group();frame.add(this.corners);
        for(const sx of [-1,1])for(const sy of [-1,1]){
            box(this.corners,sx*.30,sy*.245,.02,.09,.018,.018,mint);box(this.corners,sx*.337,sy*.208,.02,.018,.09,.018,mint);
        }
        const merge=prop('merge');merge.position.set(0,1.17,.42);this.film=[];
        for(const side of [-1,1]){
            const film=new THREE.Group();merge.add(film);this.film.push(film);box(film,0,0,0,.27,.31,.03,side<0?dark:mint);box(film,0,0,.02,.2,.18,.012,ivory);
            for(const x of [-.095,.095])for(const y of [-.125,.125])box(film,x,y,.02,.034,.022,.012,dark);
        }
        const save=prop('save');save.position.set(0,1.08,.45);
        box(save,0,0,-.04,.48,.28,.035,gold);box(save,-.12,.16,-.04,.19,.07,.035,gold);box(save,0,-.025,.06,.48,.23,.035,mint);
        this.paper=box(save,0,.15,0,.25,.30,.014,ivory);box(this.paper,0,0,.01,.13,.01,.005,dark);
        const refresh=prop('refresh');refresh.position.set(0,1.2,.45);
        const arc=new THREE.Mesh(new THREE.TorusGeometry(.2,.025,6,36,Math.PI*1.65),mint);refresh.add(arc);
        const arrow=new THREE.Mesh(new THREE.ConeGeometry(.055,.10,3),mint);arrow.position.set(.2,0,0);refresh.add(arrow);
        const settings=prop('settings');settings.position.set(0,1.2,.44);circle(settings,.14,.045,dark);
        for(let i=0;i<8;i++){const a=i*Math.PI/4,tooth=box(settings,Math.sin(a)*.19,Math.cos(a)*.19,0,.065,.09,.045,gold);tooth.rotation.z=-a;}
        const camera=prop('camera');camera.position.set(0,1.2,.43);box(camera,0,0,0,.43,.25,.12,dark);box(camera,-.09,.15,-.02,.14,.08,.09,mint);
        const lens=new THREE.Mesh(new THREE.CylinderGeometry(.095,.10,.12,20),gold);lens.rotation.x=Math.PI/2;lens.position.z=.1;camera.add(lens);circle(camera,.063,.013,mint).position.z=.165;
        const favorite=prop('favorite');favorite.position.set(0,1.24,.45);
        const heart=new THREE.Shape();heart.moveTo(0,-.16);heart.bezierCurveTo(-.32,.02,-.20,.27,0,.12);heart.bezierCurveTo(.20,.27,.32,.02,0,-.16);
        const heartMesh=new THREE.Mesh(new THREE.ExtrudeGeometry(heart,{depth:.045,bevelEnabled:true,bevelSegments:2,steps:1,bevelSize:.012,bevelThickness:.012}),red);favorite.add(heartMesh);
        const trash=prop('delete');trash.position.set(.36,.72,.38);box(trash,0,0,0,.21,.27,.17,dark);box(trash,0,.15,0,.24,.035,.19,gold);this.discard=box(trash,-.4,.58,0,.13,.17,.014,ivory);
        const clips=prop('clips');clips.position.set(0,1.14,.44);this.tiles=[];
        for(let i=0;i<3;i++){const tile=new THREE.Group();clips.add(tile);box(tile,0,0,0,.22,.27,.025,i===1?mint:ivory);box(tile,0,-.07,.02,.12,.009,.004,dark);this.tiles.push(tile);}
        const layout=prop('layout');layout.position.set(0,1.17,.44);this.panels=[];
        for(let i=0;i<3;i++)this.panels.push(box(layout,(i-1)*.19,0,0,.16,.32,.035,i===1?mint:dark));
        this.pose('generate',0);
    }
    pose(kind,time){
        const t=THREE.MathUtils.clamp(time,0,1),wave=Math.sin(t*Math.PI*2),cycle=(1-Math.cos(t*Math.PI*2))/2,breathe=wave*.006;
        this.root.position.y=breathe;this.model.rotation.set(0,-.10+wave*.025,0);this.head.rotation.set(0,0,wave*.025);
        for(const [i,arm] of this.arms.entries()){arm.upper.rotation.set(-.88,0,(i?-.08:.08));arm.fore.rotation.set(-1.05,0,0);}
        for(const [name,prop] of Object.entries(this.props)){prop.visible=name===kind;prop.rotation.set(0,0,0);prop.scale.setScalar(1);}
        if(kind==='generate'){
            const closed=cycle;this.clap.rotation.z=mix(.46,0,closed);
            this.arms[1].upper.rotation.x=-1.10+(1-closed)*-.18;this.arms[1].fore.rotation.x=-1.10-(1-closed)*.45;this.head.rotation.x=Math.sin(closed*Math.PI)*.045;
        }else if(kind==='schedule'){
            this.handMinute.rotation.z=-t*Math.PI*2;this.handHour.rotation.z=-.6-t*.5;this.head.rotation.z=-.08;
        }else if(kind==='stop'){
            this.arms[1].upper.rotation.x=-1.65;this.arms[1].fore.rotation.x=-.2;this.arms[0].upper.rotation.x=0;this.arms[0].fore.rotation.x=0;this.head.rotation.y=wave*.1;
        }else if(kind==='upscale'){
            const scale=1+.28*cycle;this.props.upscale.scale.setScalar(scale);this.corners.scale.setScalar(1+wave*.05);
        }else if(kind==='merge'){
            const gap=mix(.36,.145,cycle);this.film[0].position.x=-gap;this.film[1].position.x=gap;this.head.rotation.x=-.04*wave;
        }else if(kind==='save'){
            this.paper.position.y=mix(.35,.08,cycle);this.paper.rotation.z=wave*.04;
        }else if(kind==='refresh')this.props.refresh.rotation.z=-t*Math.PI*2;
        else if(kind==='settings')this.props.settings.rotation.z=t*Math.PI*2;
        else if(kind==='camera'){this.props.camera.rotation.y=Math.sin(t*Math.PI*2)*.18;this.head.rotation.y=-.1;}
        else if(kind==='favorite'){this.props.favorite.scale.setScalar(1+.10*Math.sin(t*Math.PI*4));this.head.rotation.z=-.10;}
        else if(kind==='delete'){const p=ease((t-.1)/.65);this.discard.position.set(-.4*(1-p),.58*(1-p)+.12,.02);this.discard.rotation.z=p*2;this.discard.visible=t<.8;}
        else if(kind==='clips')this.tiles.forEach((tile,i)=>{tile.position.set((i-1)*.24,Math.sin(t*Math.PI*2-i*.7)*.035,-Math.abs(i-1)*.03);tile.rotation.z=(i-1)*-.09;});
        else if(kind==='layout')this.panels.forEach((panel,i)=>panel.scale.y=1+Math.sin(t*Math.PI*2+i)*.14);
        this.root.updateMatrixWorld(true);
    }
}
