import {normalizePath,neutralPath,sourceZoomPath} from './multiangle_math.js?v=precise_angles_20261017_v2';
import {proxyMotion,MOTION_LORA} from './camera_motion.js?v=pruned_camera_20261017_v1';
// Native Comfy camera corrections. Unsupported controls retain their existing prompt path.
import {topdownDepthPrompt} from './camera_topdown_prompt.js';
export const CAMERA_GUIDE_MODELS={
    geometry:'moge_2_vitl_normal_fp16.safetensors',
    control:'minimax_h3_fun_controlnet_union_pruned_bf16.safetensors',
    person:'yolo11n-seg.pt',
    pose:'yolo11n-pose.pt',
};
const ROTATION_PRESETS={'slow pan left':['pan_left',20],'slow pan right':['pan_right',20],'slow tilt up':['tilt_up',12],'slow tilt down':['tilt_down',12],
    'whip pan left':['pan_left',20,'very fast','snap settle'],'whip pan right':['pan_right',20,'very fast','snap settle']};
const sourceRotation=p=>p.shot==='source framing'&&p.angle==='source angle'&&p.lens==='natural'&&p.focus==='source'&&Number(p.strength)>0?ROTATION_PRESETS[p.movement]:null;
const PIXEL_SHOTS=['medium shot','close-up','extreme close-up'];
const layeredDolly=p=>p.multi_angle?.enabled!==true&&p.shot==='source framing'&&p.angle==='source angle'&&p.lens==='natural'&&p.focus==='source'&&Number(p.strength)>0&&['dolly zoom in','dolly zoom out'].includes(p.movement);
const measuredFraming=p=>p.multi_angle?.enabled!==true&&p.angle==='source angle'&&p.lens==='natural'&&p.focus==='source'&&p.movement==='static camera'&&['medium wide shot','insert shot','macro shot'].includes(p.shot);
const CROSSVIEW_LORA='minimax\\flagship_camera\\MiniMax-H3_Ref2VA-LoRA-CrossView-Warp_v1_3500.safetensors';
const CROSSVIEW_ANGLES={'front left three-quarter':[-45,0],'front right three-quarter':[45,0],'left side profile':[-90,0],'right side profile':[90,0],'ground level':[0,-35]};
function crossviewPose(p){
    if(p.multi_angle?.enabled===true||p.shot!=='source framing'||p.lens!=='natural'||p.focus!=='source'||!(Number(p.strength)>0))return null;
    if(p.movement==='static camera'&&CROSSVIEW_ANGLES[p.angle]){
        const a=CROSSVIEW_ANGLES[p.angle];return {start:[...a,1],end:[...a,1]};
    }
    if(p.angle!=='source angle')return null;
    if(p.movement==='arc left')return {start:[0,0,1],end:[-Math.min(75,100*Number(p.strength)),0,1]};
    if(p.movement==='crane over the head')return {start:[0,0,1],end:[0,Math.min(85,200*Number(p.strength)),1+Math.min(.6,.4*Number(p.strength)/.35)]};
    return null;
}
const sourceFraming=p=>p.angle==='source angle'&&p.lens==='natural'&&p.focus==='source'&&(
    p.movement==='static camera'&&PIXEL_SHOTS.includes(p.shot)?p.shot:
    p.shot==='source framing'&&Number(p.strength)>0&&['head tracking','yoyo zoom'].includes(p.movement)&&(p.speed||'slow')==='slow'&&(p.easing||'linear')==='linear'?p.movement:null);
export function cameraCorrectionRequirements(segments,controlModel=CAMERA_GUIDE_MODELS.control){
    const zoom=segments.some(p=>p.multi_angle?.enabled===true&&sourceZoomPath(p.multi_angle));
    const numeric=segments.some(p=>p.multi_angle?.enabled===true&&!neutralPath(p.multi_angle)&&!sourceZoomPath(p.multi_angle));
    segments=segments.filter(p=>p.multi_angle?.enabled!==true);
    const orbit=segments.some(p=>p.movement==='smooth orbit left'&&Number(p.strength)>0);
    const overhead=segments.some(p=>p.angle==='top-down overhead view');
    const focus=segments.some(p=>['near to far','far to near'].includes(p.focus));
    const rotation=segments.some(sourceRotation);
    const framing=segments.some(sourceFraming);
    const measured=segments.some(measuredFraming);
    const dolly=segments.some(layeredDolly);
    const crossview=segments.some(crossviewPose);
    const proxy=segments.some(proxyMotion);
    if(!numeric&&!zoom&&!orbit&&!overhead&&!focus&&!rotation&&!framing&&!measured&&!dolly&&!crossview&&!proxy)return [];
    const checks=[];
    if(proxy)checks.push(['FlagshipCameraMotionEligibility'],['FlagshipCameraVisibleTargets','pose_model',CAMERA_GUIDE_MODELS.pose],['FlagshipCameraVisibleTargets','segmenter',CAMERA_GUIDE_MODELS.person],['LoraLoaderModelOnly','lora_name',MOTION_LORA]);
    if(segments.some(p=>proxyMotion(p)==='extreme wide shot'))checks.push(['FlagshipCameraWideComposite']);
    if(segments.some(p=>proxyMotion(p)==='aerial pullback'))checks.push(['FlagshipCameraMotionViews']);
    if(numeric)checks.push(['FlagshipMultiAngleGuide']);
    if(zoom)checks.push(['FlagshipMultiAngleSourceZoom']);
    if(numeric||orbit||overhead||focus||rotation||dolly||crossview)checks.push(['LoadMoGeModel','model_name',CAMERA_GUIDE_MODELS.geometry],['MoGeInference'],['FlagshipPrepareCameraGeometry']);
    if(crossview)checks.push(['FlagshipCrossViewGuide'],['LoraLoaderModelOnly','lora_name',CROSSVIEW_LORA]);
    if(dolly)checks.push(['FlagshipCameraDollyLayers','segmenter',CAMERA_GUIDE_MODELS.person],['FlagshipCameraLayeredDolly']);
    if(framing)checks.push(['FlagshipCameraSourceFraming']);
    if(measured)checks.push(['FlagshipCameraVisibleTargets','pose_model',CAMERA_GUIDE_MODELS.pose],['FlagshipCameraVisibleTargets','segmenter',CAMERA_GUIDE_MODELS.person],['FlagshipCameraTargetFraming']);
    if(orbit||overhead||rotation)checks.push(['FlagshipGeometryCamera']);
    if(numeric||orbit||overhead||rotation)checks.push(['ModelPatchLoader','name',controlModel],['MiniMaxH3FunControlNetApply']);
    if(rotation)checks.push(['FlagshipCameraSourceWarp']);
    if(focus)checks.push(['FlagshipDepthRackFocus']);
    if(overhead)checks.push(['FlagshipPrepareCameraGeometry','segmenter',CAMERA_GUIDE_MODELS.person]);
    return checks;
}

export function applyCameraCorrections(graph,segments,s,{cacheKey='camera',controlModel=CAMERA_GUIDE_MODELS.control}={}){
    let next=1+Math.max(0,...Object.keys(graph).map(Number).filter(Number.isFinite));
    const add=(class_type,inputs)=>{const id=String(next++);graph[id]={class_type,inputs};return [id,0];};
    const find=(type,predicate=()=>true)=>Object.entries(graph).find(([,n])=>n.class_type===type&&predicate(n));
    const references=Object.entries(graph).filter(([,n])=>n.class_type==='MiniMaxH3ReferenceToVideo');
    let moge=null,control=null;
    const width=Number(s.width),height=Number(s.height),scale=384/Math.min(width,height);
    const gw=Math.round(width*scale),gh=Math.round(height*scale);
    const geometry=(images,name,stabilize=false,foreground=false)=>{
        moge??=add('LoadMoGeModel',{model_name:CAMERA_GUIDE_MODELS.geometry});
        const small=add('ImageScale',{image:images,width:gw,height:gh,upscale_method:'area',crop:'disabled'});
        const estimated=add('MoGeInference',{moge_model:moge,image:small,resolution_level:0,fov_x_degrees:0,batch_size:2,force_projection:true,apply_mask:false,refine_steps:0});
        return add('FlagshipPrepareCameraGeometry',{geometry:estimated,name,stabilize_static_border:stabilize,
            foreground_only:foreground,segmenter:foreground?CAMERA_GUIDE_MODELS.person:'None'});
    };
    for(const [refId,ref] of references){
        const prepId=ref.inputs['ref_videos.ref_video_0']?.[0],prep=graph[prepId];
        if(prep?.class_type!=='H3R2VCameraLipLock')continue;
        const index=Number(prep.inputs.segment_index),part=segments[index];if(!part)continue;
        const numeric=part.multi_angle?.enabled===true;
        const neutral=numeric&&neutralPath(part.multi_angle);
        const zoom=numeric&&sourceZoomPath(part.multi_angle);
        const orbit=!numeric&&part.movement==='smooth orbit left'&&Number(part.strength)>0;
        const overhead=!numeric&&part.angle==='top-down overhead view';
        const focus=!numeric&&['near to far','far to near'].includes(part.focus);
        const rotation=!numeric&&sourceRotation(part);
        const framing=!numeric&&sourceFraming(part);
        const measured=!numeric&&measuredFraming(part);
        const dolly=!numeric&&layeredDolly(part);
        const crossview=!numeric&&crossviewPose(part);
        const unchanged=neutral||(!numeric&&part.shot==='source framing'&&part.angle==='source angle'&&part.lens==='natural'&&part.focus==='source'&&(part.movement==='static camera'||Number(part.strength)===0));
        if(!numeric&&!orbit&&!overhead&&!focus&&!unchanged&&!rotation&&!framing&&!measured&&!dolly&&!crossview)continue;
        if(orbit&&overhead)throw Error('깊이 교정에서 좌측 오빗과 수직 탑뷰의 동시 조합은 아직 검증하지 않았습니다.');
        if(overhead&&(part.movement!=='static camera'||focus))throw Error('탑뷰 교정은 고정 무빙·원본 초점 조합에서 검증했습니다. 다른 조합은 교정 OFF 경로를 사용하세요.');
        const [lockId,lock]=find('H3CameraExactAudioLock',n=>n.inputs.av_latent?.[0]===refId)||[];
        if(unchanged||framing||zoom||measured||dolly){
            const [sample]=find('SamplerCustomAdvanced',n=>n.inputs.latent_image?.[0]===(lockId||refId))||[];
            const [decode]=find('VAEDecode',n=>n.inputs.samples?.[0]===sample)||[];
            const [,trimmed]=find('H3CameraTrimClip',n=>n.inputs.images?.[0]===decode)||[];
            if(!trimmed)throw Error('원본 보존 출력 연결을 찾지 못했습니다.');
            if(dolly){
                const [trackId]=find('H3FaceTrackCrop',n=>n.inputs.images?.[0]===prepId)||[];
                if(!trackId)throw Error('돌리 줌에 필요한 원본 인물 추적 연결을 찾지 못했습니다.');
                const saved=geometry([prepId,0],'dolly_'+String(cacheKey).replace(/[^a-zA-Z0-9_]/g,'')+'_'+index,true,false);
                const layers=add('FlagshipCameraDollyLayers',{images:[prepId,0],face_transform:[trackId,1],geometry_file:saved,segmenter:CAMERA_GUIDE_MODELS.person});
                trimmed.inputs.images=add('FlagshipCameraLayeredDolly',{images:[prepId,0],layers,width,height,direction:part.movement==='dolly zoom in'?'in':'out',strength:Number(part.strength),speed:part.speed||'slow',easing:part.easing||'linear',fallback_images:trimmed.inputs.images});
            }else if(zoom){
                trimmed.inputs.images=add('FlagshipMultiAngleSourceZoom',{images:[prepId,0],path_json:JSON.stringify(normalizePath(part.multi_angle)),width,height});
            }else if(measured){
                const [trackId]=find('H3FaceTrackCrop',n=>n.inputs.images?.[0]===prepId)||[];
                if(!trackId)throw Error('측정 프레이밍에 필요한 인물 추적 연결을 찾지 못했습니다.');
                const targets=add('FlagshipCameraVisibleTargets',{images:[prepId,0],face_transform:[trackId,1],pose_model:CAMERA_GUIDE_MODELS.pose,segmenter:CAMERA_GUIDE_MODELS.person});
                trimmed.inputs.images=add('FlagshipCameraTargetFraming',{images:[prepId,0],targets,mode:part.shot,width,height,fallback_images:trimmed.inputs.images});
            }else if(framing){
                const [trackId]=find('H3FaceTrackCrop',n=>n.inputs.images?.[0]===prepId)||[];
                if(!trackId)throw Error('원본 프레이밍에 필요한 얼굴 추적 연결을 찾지 못했습니다.');
                trimmed.inputs.images=add('FlagshipCameraSourceFraming',{images:[prepId,0],face_transform:[trackId,1],mode:framing,width,height,strength:Number(part.strength)});
            }else trimmed.inputs.images=add('ImageScale',{image:[prepId,0],width,height,upscale_method:'area',crop:'center'});
            continue;
        }
        if(!lock)throw Error('카메라 교정에는 원본 립싱크 고정이 필요합니다.');
        const [guiderId,guider]=find('BasicGuider',n=>n.inputs.model?.[0]===lockId)||[];
        const [samplerId]=find('SamplerCustomAdvanced',n=>n.inputs.guider?.[0]===guiderId)||[];
        const [decodeId]=find('VAEDecode',n=>n.inputs.samples?.[0]===samplerId)||[];
        const [trimId,trim]=find('H3CameraTrimClip',n=>n.inputs.images?.[0]===decodeId)||[];
        if(!guider||!trim)throw Error('카메라 교정의 샘플링·출력 연결을 확인할 수 없습니다.');
        const safe=String(cacheKey).replace(/[^a-zA-Z0-9_]/g,'')+'_'+index;
        const vae=ref.inputs.vae,source=[prepId,0];
        if(crossview){
            const factor=Math.max(1,448/Math.min(width,height));
            const rw=Math.round(width*factor/32)*32,rh=Math.round(height*factor/32)*32;
            const saved=geometry(source,'crossview_'+safe,false,false);
            const projected=add('FlagshipCrossViewGuide',{images:source,geometry_file:saved,width:rw,height:rh,
                start_azimuth:crossview.start[0],end_azimuth:crossview.end[0],start_elevation:crossview.start[1],end_elevation:crossview.end[1],
                start_distance:crossview.start[2],end_distance:crossview.end[2],speed:part.speed||'slow',easing:part.easing||'linear'});
            for(const key of Object.keys(ref.inputs))if(key.startsWith('ref_images.'))delete ref.inputs[key];
            ref.inputs['ref_videos.ref_video_0']=add('ImageScale',{image:source,width:rw,height:rh,upscale_method:'area',crop:'disabled'});
            Object.assign(ref.inputs,{width:rw,height:rh,prompt:'crossview'});
            guider.inputs.conditioning=add('MiniMaxH3AddGuide',{positive:[refId,0],latent:[refId,1],frame_idx:0,vae,image:projected});
            const adapter=add('LoraLoaderModelOnly',{model:lock.inputs.model,lora_name:CROSSVIEW_LORA,strength_model:1});
            graph[adapter[0]]._meta={flagship_camera_view_adapter:true};lock.inputs.model=adapter;
            const schedule=graph[graph[samplerId].inputs.sigmas[0]];
            if(schedule?.class_type!=='BasicScheduler')throw Error('시점 보정의 스케줄러 연결을 찾지 못했습니다.');
            schedule.inputs.scheduler='simple';
            if(rw!==width||rh!==height)trim.inputs.images=add('ImageScale',{image:trim.inputs.images,width,height,upscale_method:'area',crop:'disabled'});
            trim._meta={...trim._meta,flagship_camera_visible_face_only:true};
            continue;
        }
        if(numeric){
            const path=normalizePath(part.multi_angle);
            const saved=geometry(source,'numeric_'+safe,true,false);
            const projected=add('FlagshipMultiAngleGuide',{geometry_file:saved,path_json:JSON.stringify(path),width:gw,height:gh,depth_only:true});
            control??=add('ModelPatchLoader',{name:controlModel});
            lock.inputs.model=add('MiniMaxH3FunControlNetApply',{model:lock.inputs.model,model_patch:control,vae,
                control_video:projected,strength:1,start_percent:0,end_percent:.85});
            continue;
        }
        if(orbit||overhead||rotation){
            const saved=geometry(source,'guide_'+safe,true,overhead);
            const projected=add('FlagshipGeometryCamera',{geometry_file:saved,mode:rotation?rotation[0]:orbit?'orbit_left':'top_down',
                degrees:rotation?rotation[1]*Number(part.strength):orbit?Math.min(75,100*Number(part.strength)):90,width:gw,height:gh,projection:'mesh',first_frame_only:false,depth_only:true,speed:rotation?.[2]||part.speed||'slow',easing:rotation?.[3]||part.easing||'linear'});
            if(rotation){
                control??=add('ModelPatchLoader',{name:controlModel});
                lock.inputs.model=add('MiniMaxH3FunControlNetApply',{model:lock.inputs.model,model_patch:control,vae,
                    control_video:projected,strength:1,start_percent:0,end_percent:.85});
                ref.inputs.prompt+='\nCAMERA GEOMETRY: Follow the animated depth-control layout. Use the requested optical-center rotation without any camera roll. Preserve the source performer world orientation and source articulation timing.';
                const consumers=Object.values(graph).flatMap(n=>Object.entries(n.inputs).filter(([,v])=>Array.isArray(v)&&v[0]===trimId&&v[1]===0).map(([key])=>[n.inputs,key]));
                const preserved=add('FlagshipCameraSourceWarp',{source_images:source,generated_images:[trimId,0],geometry_file:saved,
                    mode:rotation[0],degrees:rotation[1]*Number(part.strength),speed:rotation[2]||part.speed||'slow',easing:rotation[3]||part.easing||'linear',
                    feather_pixels:Math.min(64,Math.max(1,Math.round(4*Math.min(width,height)/320)))});
                for(const [inputs,key] of consumers)inputs[key]=preserved;
            }else if(orbit){
                control??=add('ModelPatchLoader',{name:controlModel});
                lock.inputs.model=add('MiniMaxH3FunControlNetApply',{model:lock.inputs.model,model_patch:control,vae,
                    control_video:projected,strength:.8,start_percent:0,end_percent:.65});
                ref.inputs.prompt+='\nGEOMETRY CONTROL: Follow the depth-guide camera path. Keep the performer in the original world orientation while the camera travels left. Background perspective and occlusions change with the camera. Do not substitute a body pivot. Preserve source articulation timing.';
            }else{
                const first=add('ImageFromBatch',{image:source,batch_index:0,length:1});
                const start=part.start_seconds===undefined?part.start_frame:Math.round(part.start_seconds*24);
                const end=part.end_seconds===undefined?part.end_frame:Math.round(part.end_seconds*24);
                control??=add('ModelPatchLoader',{name:controlModel});
                lock.inputs.model=add('MiniMaxH3FunControlNetApply',{model:lock.inputs.model,model_patch:control,vae,
                    control_video:projected,strength:1.15,start_percent:0,end_percent:.9});
                // Frontal semantic video fought the new overhead view. Keep the
                // original facial identity/audio, and carry motion in the depth guide.
                delete ref.inputs['ref_videos.ref_video_0'];
                delete ref.inputs['ref_video_audios.ref_video_audio_0'];
                ref.inputs['ref_images.ref_image_1']=first;
                ref.inputs['ref_audios.ref_audio_0']=[prepId,1];
                guider.inputs.conditioning=[refId,0];
                ref.inputs.prompt=topdownDepthPrompt((end-start)/24);
            }
        }
        if(focus){
            // Preserve the source pixels for a pure focus change. Otherwise analyze
            // the generated viewpoint, never reuse mismatched source-camera depth.
            const pure=!orbit&&!overhead&&part.movement==='static camera'&&part.shot==='source framing'&&part.angle==='source angle'&&part.lens==='natural';
            const images=pure?add('ImageScale',{image:source,width,height,upscale_method:'area',crop:'center'}):[trimId,0];
            const consumers=Object.values(graph).flatMap(n=>Object.entries(n.inputs).filter(([,v])=>Array.isArray(v)&&v[0]===trimId&&v[1]===0).map(([key])=>[n.inputs,key]));
            ref.inputs.prompt=ref.inputs.prompt.replace(/FOCUS: [^\n]*/, 'FOCUS: keep the source focus; the depth-aware optical pass applies the requested rack focus.');
            const saved=geometry(images,'focus_'+safe);
            const originalFace=find('H3FaceTrackCrop',n=>n.inputs.images?.[0]===prepId)?.[1];
            if(!originalFace)throw Error('자동 초점의 얼굴 추적 연결을 찾지 못했습니다.');
            const tracked=add('H3FaceTrackCrop',{...originalFace.inputs,images});
            const focused=add('FlagshipDepthRackFocus',{images,geometry_file:saved,blur_pixels:14,face_transform:[tracked[0],1],direction:part.focus});
            if(pure)trim.inputs.images=focused;
            else for(const [inputs,key] of consumers)inputs[key]=focused;
        }
    }
    return graph;
}

export async function checkCameraCorrections(api,segments){
    const requirements=cameraCorrectionRequirements(segments);
    let controlModel=CAMERA_GUIDE_MODELS.control;
    for(const [type,input,name] of requirements){
        const response=await api.fetchApi('/object_info/'+encodeURIComponent(type));
        const info=(await response.json())[type];
        if(!response.ok||!info)throw Error(`카메라 교정에 ${type} 노드가 필요합니다.`);
        if(!input)continue;
        const spec=info.input?.required?.[input]||info.input?.optional?.[input];
        const choices=Array.isArray(spec?.[0])?spec[0]:spec?.[1]?.options;
        if(!Array.isArray(choices))throw Error(`카메라 교정 모델 목록을 확인할 수 없습니다: ${type}`);
        if(type==='ModelPatchLoader'&&!choices.includes(name)&&choices.includes('Codex_'+name))controlModel='Codex_'+name;
        else if(!choices.includes(name))throw Error(`카메라 교정 모델이 없습니다: ${name}`);
    }
    return controlModel;
}
