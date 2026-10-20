import {addFaceAudioRepair} from './camera_face_audio.js?v=recovery16_20261017_v2';

export const MOTION_LORA='minimax\\flagship_camera\\camera_motion_h3_lora_v1_3000_pruned.safetensors';
export function proxyMotion(p){
    if(p.multi_angle?.enabled===true||p.angle!=='source angle'||p.lens!=='natural'||p.focus!=='source'||!(Number(p.strength)>0)||
       (p.speed||'slow')!=='slow'||(p.easing||'linear')!=='linear')return null;
    if(p.shot==='extreme wide shot'&&p.movement==='static camera')return 'extreme wide shot';
    return p.shot==='source framing'&&p.movement==='aerial pullback'?p.movement:null;
}

export function applyCameraMotion(graph,segments,s){
    if(!String(s.model||'').toLowerCase().includes('fl2v'))return graph;
    let next=1+Math.max(0,...Object.keys(graph).map(Number).filter(Number.isFinite));
    const add=(class_type,inputs)=>{const id=String(next++);graph[id]={class_type,inputs};return[id,0];};
    const refs=Object.entries(graph).filter(([,n])=>n.class_type==='MiniMaxH3ReferenceToVideo');
    for(const [refId,ref] of refs){
        const prepId=ref.inputs['ref_videos.ref_video_0']?.[0],prep=graph[prepId];if(prep?.class_type!=='H3R2VCameraLipLock')continue;
        const part=segments[Number(prep.inputs.segment_index)],mode=part&&proxyMotion(part);if(!mode)continue;
        const trackId=Object.keys(graph).find(k=>graph[k].class_type==='H3FaceTrackCrop'&&graph[k].inputs.images?.[0]===prepId);
        const lockEntry=Object.entries(graph).find(([,n])=>n.class_type==='H3CameraExactAudioLock'&&n.inputs.av_latent?.[0]===refId);
        if(!trackId||!lockEntry)throw Error('카메라 이동의 원본 추적·음성 연결을 찾지 못했습니다.');
        const [lockId,lock]=lockEntry;
        const sample=Object.values(graph).find(n=>n.class_type==='SamplerCustomAdvanced'&&n.inputs.latent_image?.[0]===lockId);
        const sampleId=Object.keys(graph).find(k=>graph[k]===sample);
        const decodeId=Object.keys(graph).find(k=>graph[k].class_type==='VAEDecode'&&graph[k].inputs.samples?.[0]===sampleId);
        const trimId=Object.keys(graph).find(k=>graph[k].class_type==='H3CameraTrimClip'&&graph[k].inputs.images?.[0]===decodeId);
        if(!sample||!trimId)throw Error('카메라 이동의 기존 출력 연결을 찾지 못했습니다.');
        const originalRepair=Object.keys(graph).find(k=>graph[k].class_type==='FlagshipCameraLipRepairSwitch'&&graph[k].inputs.original?.[0]===trimId);
        const original=[originalRepair||trimId,0];
        const consumers=Object.values(graph).flatMap(n=>Object.entries(n.inputs).filter(([,v])=>Array.isArray(v)&&v[0]===original[0]&&v[1]===0).map(([key])=>[n.inputs,key]));
        const source=[prepId,0],audio=[prepId,1];
        const targets=add('FlagshipCameraVisibleTargets',{images:source,face_transform:[trackId,1],pose_model:'yolo11n-pose.pt',segmenter:'yolo11n-seg.pt'});
        const eligibility=add('FlagshipCameraMotionEligibility',{targets,face_transform:[trackId,1],images:source,audio,mode});
        const factor=Math.max(1,448/Math.min(s.width,s.height));const width=Math.round(s.width*factor/32)*32,height=Math.round(s.height*factor/32)*32;
        const first=add('ImageScale',{image:add('ImageFromBatch',{image:source,batch_index:0,length:1}),width,height,upscale_method:'area',crop:'disabled'});
        const adapter=add('LoraLoaderModelOnly',{model:lock.inputs.model,lora_name:MOTION_LORA,strength_model:1.2});
        graph[adapter[0]]._meta={flagship_camera_view_adapter:true};
        const schedule=add('BasicScheduler',{model:adapter,scheduler:'simple',steps:Math.max(12,Number(s.steps)||12),denoise:1});
        const sampler=add('KSamplerSelect',{sampler_name:s.sampler||'res_multistep'});
        function render(condition,positive){
            const pinned=add('H3CameraExactAudioLock',{model:adapter,av_latent:[condition[0],1],audio_vae:ref.inputs.audio_vae,audio});
            const guider=add('BasicGuider',{model:pinned,conditioning:positive||condition});
            const result=add('SamplerCustomAdvanced',{noise:sample.inputs.noise,guider,sampler,sigmas:schedule,latent_image:[pinned[0],1]});
            return add('H3CameraTrimClip',{images:add('VAEDecode',{samples:result,vae:ref.inputs.vae}),source_frames:source});
        }
        const condition=add('MiniMaxH3ImageToVideo',{clip:ref.inputs.clip,vae:ref.inputs.vae,prompt:[eligibility[0],2],width,height,length:124,first_frame:first});
        const raw=render(condition);let corrected;
        if(mode==='extreme wide shot'){
            const last=add('ImageFromBatch',{image:raw,batch_index:123,length:1});
            corrected=add('FlagshipCameraWideComposite',{images:source,wide_frame:last,targets,segmenter:'yolo11n-seg.pt'});
        }else{
            const selected=add('FlagshipCameraMotionViews',{images:raw,mode,strength:Number(part.strength),pose_model:'yolo11n-pose.pt'});
            const views=[0,1,2,3].map(index=>[selected[0],index]);
            const refined=add('MiniMaxH3ImageToVideo',{clip:ref.inputs.clip,vae:ref.inputs.vae,prompt:[eligibility[0],3],width,height,length:124,first_frame:first,last_frame:views[3]});
            let positive=refined;
            for(let i=0;i<3;i++)positive=add('MiniMaxH3AddGuide',{positive,latent:[refined[0],1],frame_idx:[31,62,93][i],vae:ref.inputs.vae,image:views[i]});
            const camera=render(refined,positive);
            const noiseSeed=graph[sample.inputs.noise[0]]?.inputs.noise_seed;if(!Number.isInteger(noiseSeed))throw Error('현재 카메라 구간의 시드가 없습니다.');
            corrected=addFaceAudioRepair(graph,{target:camera,source,audio,reference:ref.inputs,model:lock.inputs.model,
                scheduler:s.scheduler,steps:8,noiseSeed,visibleOnly:true});
            next=1+Math.max(...Object.keys(graph).map(Number).filter(Number.isFinite));
        }
        if(width!==s.width||height!==s.height)corrected=add('ImageScale',{image:corrected,width:s.width,height:s.height,upscale_method:'area',crop:'disabled'});
        const chosen=add('FlagshipCameraLipRepairSwitch',{repair:eligibility,original,corrected});
        for(const [inputs,key] of consumers)inputs[key]=chosen;
    }
    return graph;
}
