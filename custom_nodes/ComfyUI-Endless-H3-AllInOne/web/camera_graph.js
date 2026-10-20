import {applyCameraDirections,validateCameraSegments} from './camera_controls.js?v=pruned_camera_20261017_v1';

import {applyCameraCorrections} from './camera_corrections.js?v=pruned_camera_20261017_v1';
import {applyCameraFaceAudio} from './camera_face_audio.js?v=recovery16_20261017_v2';
import {applyCameraMotion} from './camera_motion.js?v=pruned_camera_20261017_v1';

// The studio owns shared generation settings; the camera engine owns shot construction.

export function applyCameraSettings(graph,s,{strict=true,seed=-1,projectId='',segments=null,corrections=false,cacheKey='camera',controlModel}={}) {
    if(segments)validateCameraSegments(segments);

    let id=1+Math.max(0,...Object.keys(graph).map(Number).filter(Number.isFinite));

    const add=(class_type,inputs)=>{const key=String(id++);graph[key]={class_type,inputs};return [key,0];};

    const options=Object.values(graph).find(node=>node.class_type==='H3CameraModelOptions');

    if(!options)throw Error('카메라 모델 설정 연결을 찾을 수 없습니다.');

    let model=options.inputs.model;

    if(s.reference_lora&&s.reference_strength!==0)model=add('LoraLoaderModelOnly',{model,lora_name:s.reference_lora,strength_model:s.reference_strength});

    options.inputs.model=model;

    const optionId=Object.keys(graph).find(key=>graph[key]===options);model=[optionId,0];

    for(const lora of s.loras||[])if(lora.enabled!==false&&lora.name&&lora.strength!==0)model=add('LoraLoaderModelOnly',{model,lora_name:lora.name,strength_model:lora.strength});

    const attention=s.attention_mode||(s.sage?'h3_sage':'off');

    if(attention==='h3_sage')model=add('MiniMaxH3MemoryEfficientSageAttentionPatch',{model});

    else if(attention==='kj_sage')model=add('PathchSageAttentionKJ',{model,sage_attention:'auto',allow_compile:false});

    else if(['pytorch','kitchen'].includes(attention))model=add('ModelAttentionBackend',{model,attention:attention==='pytorch'?'pytorch attention':'comfy kitchen attention'});

    if(s.chunks>1)model=add('MiniMaxChunkFeedForward',{model,chunks:s.chunks,seq_threshold:4096});

    if(s.fp16_accumulation)model=add('ModelPatchTorchSettings',{model,enable_fp16_accumulation:true});

    if(s.cache_mode==='easycache')model=add('EasyCache',{model,reuse_threshold:s.easycache_threshold,start_percent:.2,end_percent:.9,verbose:false});

    if(s.cache_mode==='spectrum'&&!strict)model=add('SpectrumApplyMiniMaxH3',{model,enabled:true,blend_weight:s.spectrum_blend,degree:1,ridge_lambda:.1,window_size:2,flex_window:.75,warmup_steps:1,tail_actual_steps:2,max_history:8,debug:false,history_storage:'system_ram',offline_archive_storage:'system_ram',audio_blend_weight:0});

    const refs=Object.values(graph).filter(node=>node.class_type==='MiniMaxH3ReferenceToVideo');

    for(const node of refs){

        for(const [input,key] of [['clip','clip'],['vae','video_vae'],['audio_vae','audio_vae']]){

            const loader=graph[node.inputs[input]?.[0]];

            if(loader&&s[key])loader.inputs[input==='clip'?'clip_name':'vae_name']=s[key];

        }

        node.inputs.ref_image_size=s.ref_image_size;

    }

    let noiseIndex=0;

    const baseSeed=seed>=0?seed:Math.floor(Math.random()*Number.MAX_SAFE_INTEGER);

    for(const node of Object.values(graph)){

        if(node.class_type==='MiniMaxH3SigmaShift')Object.assign(node.inputs,{model,shift_video:s.shift_video,shift_audio:s.shift_audio});

        if(node.class_type==='KSamplerSelect')node.inputs.sampler_name=s.sampler;

        if(node.class_type==='BasicScheduler')node.inputs.scheduler=s.scheduler;

        if(node.class_type==='RandomNoise')node.inputs.noise_seed=(baseSeed+noiseIndex++)%Number.MAX_SAFE_INTEGER;

        if(node.class_type==='RTXVideoVSRRestore')Object.assign(node.inputs,{motion_repair:s.motion_repair,motion_repair_strength:s.motion_repair_strength,memory_profile:s.memory_profile});

        if(node.class_type==='SaveVideo')node.inputs.filename_prefix=/^[0-9a-f]{32}$/.test(projectId)?`EndlessH3AIO/${projectId}/camera/directed`:'h3_r2v_camera_lip_lock/studio';

    }

    const directed=segments?applyCameraDirections(graph,segments):graph;

    if(!corrections||!segments)return directed;
    const corrected=applyCameraCorrections(directed,segments,s,{cacheKey,controlModel});
    return strict?applyCameraMotion(applyCameraFaceAudio(corrected,s),segments,s):corrected;

}



export function cameraTimelineInputs(widgets,s) {
    if(widgets.camera_plan_json)validateCameraSegments(JSON.parse(widgets.camera_plan_json).segments||[]);

    return {...widgets,expected_segments:0,unet_name:s.model,lora_name:s.turbo_lora||'None',lora_strength:s.turbo_strength,

        sage_enabled:false,spectrum_enabled:false,steps:s.steps,aspect_ratio:'custom',custom_width:s.width,custom_height:s.height,

        upscale_enabled:!!s.upscale,upscale_scale:s.scale,upscale_color_treatment:s.color_treatment,upscale_output_quality:s.output_quality,

        upscale_quality:'Ultra',upscale_restore_mode:'Auto Scan (Clean/Chain90)',upscale_quality_target:'110% Master',upscale_encode_preset:'slow',upscale_temporal_mode:'Auto Temporal',upscale_subject_recovery:'Auto',upscale_output_mode:'SDR'};

}

