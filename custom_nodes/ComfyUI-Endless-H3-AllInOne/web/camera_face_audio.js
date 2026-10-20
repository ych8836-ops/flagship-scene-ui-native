// Repair only generated speaking faces; the final soundtrack remains the original.
export function addFaceAudioRepair(graph,{target,source,audio,reference,model,scheduler,steps,noiseSeed,visibleOnly=false}){
    let next=1+Math.max(0,...Object.keys(graph).map(Number).filter(Number.isFinite));
    const add=(class_type,inputs)=>{const id=String(next++);graph[id]={class_type,inputs};return [id,0];};
    const guard=add('FlagshipCameraLipRepairGuard',{source_images:source,target_images:target,audio,detector:'face_yolov8m.pt',...(visibleOnly?{visible_only:true}:{})});
    const tracking={detector:'face_yolov8m.pt',confidence:.25,crop_factor:2.5,canvas_width:[guard[0],1],canvas_height:[guard[0],1],
        canvas_mode:'manual',smooth_window:21,size_smooth_window:51,smooth_method:'gaussian',size_mode:'per_frame',
        identity_track:true,identity_threshold:.28,select:'largest',fallback_detector:'none',fallback_head_frac:.5};
    const tracked=add('H3FaceTrackCrop',{images:target,...tracking,...(visibleOnly?{confidence:.35,smooth_window:5,size_smooth_window:21,identity_track:false}:{})});
    const original=add('H3FaceTrackCrop',{images:source,...tracking});
    const first=add('ImageFromBatch',{image:tracked,batch_index:0,length:1});
    const cond=add('MiniMaxH3ReferenceToVideo',{clip:reference.clip,vae:reference.vae,audio_vae:reference.audio_vae,
        prompt:[guard[0],3],width:[guard[0],1],height:[guard[0],1],length:reference.length,ref_image_size:'match',
        'ref_images.ref_image_0':first,'ref_videos.ref_video_0':original,'ref_video_audios.ref_video_audio_0':audio});
    const injected=add('H3InjectVideoLatent',{av_latent:[cond[0],1],images:tracked,vae:reference.vae});
    const encoded=add('VAEEncodeAudio',{audio,vae:reference.audio_vae});
    const zero=add('SolidMask',{value:0,width:1,height:1});
    const locked=add('SetLatentNoiseMask',{samples:encoded,mask:zero});
    const av=add('LTXVConcatAVLatent',{video_latent:injected,audio_latent:locked});
    const guider=add('BasicGuider',{model,conditioning:cond});
    const sampler=add('KSamplerSelect',{sampler_name:'res_multistep'});
    const schedule=add('BasicScheduler',{model,scheduler,steps,denoise:.35});
    const noise=add('RandomNoise',{noise_seed:noiseSeed});
    const sampled=add('SamplerCustomAdvanced',{noise,guider,sampler,sigmas:schedule,latent_image:av});
    const decoded=add('VAEDecode',{samples:sampled,vae:reference.vae});
    const aligned=add('H3CameraTrimClip',{images:decoded,source_frames:target});
    const corrected=add('H3FaceStitch',{base_images:target,refined_crops:aligned,transform:[tracked[0],1],
        paste_region:'face_ellipse',mask_dilation:8,feather:3,colour_match:.8,blend:1,
        undetected_frames:'fade_out',feather_scales_with_crop:false});
    const protectedProps=add('FlagshipCameraProtectProps',{original:target,corrected,segmenter:'yolo11n-seg.pt',...(visibleOnly?{visibility:[tracked[0],1]}:{})});
    return add('FlagshipCameraLipRepairSwitch',{repair:guard,original:target,corrected:protectedProps});
}

function containsSampler(graph,link,seen=new Set()){
    if(!Array.isArray(link)||typeof link[0]!=='string'||seen.has(link[0]))return false;
    seen.add(link[0]);const node=graph[link[0]];if(!node)return false;
    return node.class_type==='SamplerCustomAdvanced'||Object.values(node.inputs).some(value=>containsSampler(graph,value,seen));
}

export function applyCameraFaceAudio(graph,s){
    const segments=Object.entries(graph).filter(([,n])=>n.class_type==='H3CameraTrimClip');
    for(const [id,trim] of segments){
        const source=trim.inputs.source_frames,prep=graph[source?.[0]];
        if(prep?.class_type!=='H3R2VCameraLipLock'||!containsSampler(graph,trim.inputs.images))continue;
        if(['FlagshipCameraTargetFraming','FlagshipCameraLayeredDolly'].includes(graph[trim.inputs.images?.[0]]?.class_type))continue;
        const consumers=Object.values(graph).flatMap(n=>Object.entries(n.inputs)
            .filter(([,v])=>Array.isArray(v)&&v[0]===id&&v[1]===0).map(([key])=>[n.inputs,key]));
        if(!consumers.length)continue;
        // Source-pixel warps keep the speaking face; only their unseen borders are synthesized.
        if(Object.values(graph).some(n=>n.class_type==='FlagshipCameraSourceWarp'&&n.inputs.generated_images?.[0]===id))continue;
        const lock=Object.values(graph).find(n=>n.class_type==='H3CameraExactAudioLock'&&n.inputs.audio?.[0]===source[0]);
        if(!lock)continue;
        const reference=graph[lock.inputs.av_latent[0]].inputs;
        let model=lock.inputs.model;
        while(graph[model[0]]?.class_type==='MiniMaxH3FunControlNetApply'||graph[model[0]]?._meta?.flagship_camera_view_adapter===true)model=graph[model[0]].inputs.model;
        const lockId=Object.keys(graph).find(key=>graph[key]===lock);
        const sample=Object.values(graph).find(n=>n.class_type==='SamplerCustomAdvanced'&&n.inputs.latent_image?.[0]===lockId);
        const noise=graph[sample?.inputs.noise?.[0]];
        if(!noise)throw Error('얼굴 보정에 필요한 현재 구간의 시드를 찾지 못했습니다.');
        const repaired=addFaceAudioRepair(graph,{target:[id,0],source,audio:[source[0],1],reference,model,
            scheduler:s.scheduler,steps:8,noiseSeed:noise?.inputs.noise_seed??0,visibleOnly:trim._meta?.flagship_camera_visible_face_only===true});
        for(const [inputs,key] of consumers)inputs[key]=repaired;
    }
    return graph;
}
