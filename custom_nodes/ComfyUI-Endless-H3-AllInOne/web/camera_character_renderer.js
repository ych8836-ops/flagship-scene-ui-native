import * as THREE from './vendor/build/three.module.js';
import {createCameraMuse} from './camera_muse.js?v=lowpoly_20261017';
import {RoomEnvironment} from './vendor/examples/jsm/environments/RoomEnvironment.js';
import {buildCameraStage} from './camera_stage_scene.js?v=cinema_20261017';

export const cameraPostShader={
    vertexShader:`varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.,1.);}`,
    fragmentShader:`varying vec2 vUv;uniform sampler2D sceneColor;uniform sampler2D sceneDepth;
uniform vec2 pixel;uniform float focusDistance;uniform float aperture;uniform float fisheye;
void main(){
    vec2 center=vUv-.5,uv=.5+center*(1.+fisheye*dot(center,center)*1.4);
    if(any(lessThan(uv,vec2(0.)))||any(greaterThan(uv,vec2(1.)))){gl_FragColor=vec4(.55,.54,.50,1.);}
    else{
        float depth=texture2D(sceneDepth,uv).x;
        float distance=(2.*.08*70.)/(70.+.08-(2.*depth-1.)*(70.-.08));
        float radius=clamp(abs(distance-focusDistance)/max(distance,.1)*aperture,0.,12.);
        vec3 color=texture2D(sceneColor,uv).rgb*2.;
        for(int i=0;i<16;i++){
            float a=float(i)*2.399963,r=sqrt((float(i)+.5)/16.);
            vec2 p=clamp(uv+vec2(cos(a),sin(a))*r*radius*pixel,vec2(.001),vec2(.999));
            color+=texture2D(sceneColor,p).rgb;
        }
        gl_FragColor=vec4(color/18.,1.);
    }
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
}`,
};

export class CameraStageRenderer {
    constructor(canvas){
        this.canvas=canvas;this.renderer=new THREE.WebGLRenderer({canvas,alpha:false,antialias:true,powerPreference:'low-power'});
        this.renderer.setSize(canvas.width,canvas.height,false);this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1.1;
        this.renderer.shadowMap.enabled=true;this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;
        this.scene=new THREE.Scene();this.scene.background=new THREE.Color('#cbc9c1');this.scene.fog=new THREE.Fog('#cbc9c1',15,40);
        this.camera=new THREE.PerspectiveCamera(44,canvas.width/canvas.height,.08,70);
        const environment=new RoomEnvironment(),pmrem=new THREE.PMREMGenerator(this.renderer);this.environment=pmrem.fromScene(environment,.04);this.scene.environment=this.environment.texture;environment.dispose();pmrem.dispose();
        this.scene.add(new THREE.HemisphereLight('#f4f6ef','#9c9a8d',1.25));
        const key=new THREE.DirectionalLight('#fff1dd',3.2);key.position.set(-3,7,5);key.castShadow=true;key.shadow.mapSize.set(1024,1024);Object.assign(key.shadow.camera,{left:-9,right:9,top:9,bottom:-9,near:.1,far:30});key.shadow.bias=-.0005;key.shadow.normalBias=.015;this.scene.add(key);
        const rim=new THREE.DirectionalLight('#cee8e0',1.5);rim.position.set(3,4,-4);this.scene.add(rim);
        const data=buildCameraStage();this.set=this.stageMesh(data.set);this.scene.add(this.set);this.gate=this.stageMesh(data.gate);this.gate.visible=false;this.scene.add(this.gate);this.vehicle=this.stageMesh(data.vehicle);this.vehicle.visible=false;this.scene.add(this.vehicle);
        this.modelRoot=new THREE.Group();this.scene.add(this.modelRoot);
        const model=createCameraMuse();this.modelRoot.add(model);this.loaded=true;
        this.target=new THREE.WebGLRenderTarget(canvas.width,canvas.height,{type:THREE.HalfFloatType});
        this.target.depthTexture=new THREE.DepthTexture(canvas.width,canvas.height);
        this.post=new THREE.Scene();this.postCamera=new THREE.OrthographicCamera(-1,1,1,-1,0,1);
        this.postMaterial=new THREE.ShaderMaterial({...cameraPostShader,depthTest:false,depthWrite:false,uniforms:{sceneColor:{value:this.target.texture},sceneDepth:{value:this.target.depthTexture},pixel:{value:new THREE.Vector2(1/canvas.width,1/canvas.height)},focusDistance:{value:6},aperture:{value:0},fisheye:{value:0}}});
        this.post.add(new THREE.Mesh(new THREE.PlaneGeometry(2,2),this.postMaterial));
    }
    stageMesh(data){
        const geometry=new THREE.BufferGeometry(),position=[],normal=[],color=[],materials=[];let last=-1;
        for(let i=0;i<data.length;i+=10){position.push(...data.slice(i,i+3));normal.push(...data.slice(i+3,i+6));color.push(...data.slice(i+6,i+9));const tag=Math.round(data[i+9]);if(tag!==last){if(geometry.groups.length)geometry.groups.at(-1).count=i/10-geometry.groups.at(-1).start;geometry.addGroup(i/10,0,tag);last=tag;}}
        if(geometry.groups.length)geometry.groups.at(-1).count=data.length/10-geometry.groups.at(-1).start;
        geometry.setAttribute('position',new THREE.Float32BufferAttribute(position,3));geometry.setAttribute('normal',new THREE.Float32BufferAttribute(normal,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(color,3));
        for(let tag=0;tag<4;tag++)materials.push(new THREE.MeshStandardMaterial({vertexColors:true,roughness:tag===2?.3:.65,metalness:tag===2?.7:0,side:THREE.DoubleSide,emissive:tag===3?'#fff2dc':'#000000',emissiveIntensity:tag===3?.7:0}));
        const mesh=new THREE.Mesh(geometry,materials);mesh.castShadow=true;mesh.receiveShadow=true;return mesh;
    }
    draw(state,key,value){
        if(this.disposed)return;
        this.camera.position.set(state.position.x,state.position.y,state.position.z);this.camera.up.set(0,1,0);this.camera.lookAt(state.target.x,state.target.y,state.target.z);this.camera.rotateZ(-state.roll);
        this.camera.fov=THREE.MathUtils.radToDeg(2*Math.atan(1/(2.45*state.focal)));this.camera.updateProjectionMatrix();
        this.modelRoot.position.set(state.actor.x,state.actor.y,state.actor.z);this.modelRoot.visible=!state.vehicle;this.vehicle.visible=!!state.vehicle;this.vehicle.position.copy(this.modelRoot.position);this.gate.visible=!!state.gate;
        const rack=state.focus==='near to far'||state.focus==='far to near',shallow=state.focus==='shallow'||state.focus==='face';
        if(rack||shallow||state.fisheye){
            this.camera.updateMatrixWorld();const direction=this.camera.getWorldDirection(new THREE.Vector3());
            const distance=point=>new THREE.Vector3(...point).sub(this.camera.position).dot(direction);
            let focus=distance([state.actor.x,1.65+state.actor.y,state.actor.z]);
            if(rack){const p=state.focus==='near to far'?state.focusProgress:1-state.focusProgress;focus=THREE.MathUtils.lerp(distance([-1.8,1.5,2.5]),distance([0,1,-6]),p);}
            this.postMaterial.uniforms.focusDistance.value=Math.max(.1,focus);this.postMaterial.uniforms.aperture.value=rack?22:shallow?18:0;this.postMaterial.uniforms.fisheye.value=state.fisheye?1:0;
            this.renderer.setRenderTarget(this.target);this.renderer.render(this.scene,this.camera);this.renderer.setRenderTarget(null);this.renderer.render(this.post,this.postCamera);
        }else this.renderer.render(this.scene,this.camera);
    }
    release(root){root.traverse(object=>{object.geometry?.dispose();for(const m of (Array.isArray(object.material)?object.material:[object.material]).filter(Boolean)){for(const v of Object.values(m))if(v?.isTexture)v.dispose();m.dispose();}});}
    dispose(loseContext=true){if(this.disposed)return;this.disposed=true;this.release(this.scene);this.post.children[0].geometry.dispose();this.postMaterial.dispose();this.target.dispose();this.environment.dispose();this.renderer.dispose();if(loseContext)this.renderer.forceContextLoss();}
}
