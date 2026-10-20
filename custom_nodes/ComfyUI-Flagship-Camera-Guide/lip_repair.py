"""Conservative eligibility checks for source-audio face repair."""
import json
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from ultralytics import YOLO

import comfy.model_management as mm
import folder_paths
from .speech_prompt import source_speech, repair_prompt


def face_policy(source, target, max_crop, audio_rms, visible_only=False):
    if audio_rms < 10 ** (-45 / 20):
        return False, 384, 'silent soundtrack'
    for label, frames in [('source', source), ('target', target)]:
        if visible_only and label=='target':
            if any(len(boxes)>2 for boxes in frames):return False,384,'target: more than two visible faces'
            largest=[max(boxes,key=lambda b:(b[2]-b[0])*(b[3]-b[1])) for boxes in frames if boxes]
            usable=[b for b in largest if min(b[2]-b[0],b[3]-b[1])>=24 and (b[2]-b[0])/max(b[3]-b[1],1)>=.45]
            if len(usable)<len(frames)*.25:return False,384,'target: too few usable visible-face windows'
            continue
        if any(len(boxes) > 1 for boxes in frames):
            return False, 384, f'{label}: multiple faces'
        visible = [boxes[0] for boxes in frames if len(boxes) == 1]
        if len(visible) < len(frames) * .8:
            return False, 384, f'{label}: insufficient visible face coverage'
        if any(min(b[2]-b[0], b[3]-b[1]) < 24 for b in visible):
            return False, 384, f'{label}: face too small'
        if any((b[2]-b[0]) / max(b[3]-b[1], 1) < .45 for b in visible):
            return False, 384, f'{label}: narrow/side face'
    canvas = max(384, math.ceil(max_crop / 32) * 32)
    if canvas > 768:
        return False, 384, 'face crop exceeds tested memory bound; no downsampling'
    return True, canvas, 'single visible face; original audio has signal (not a speech classifier)'


class FlagshipCameraLipRepairGuard:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'source_images': ('IMAGE',), 'target_images': ('IMAGE',),
            'audio': ('AUDIO',), 'detector': ('STRING', {'default': 'face_yolov8m.pt'})},
            'optional':{'visible_only':('BOOLEAN',{'default':False})}}

    RETURN_TYPES = ('BOOLEAN', 'INT', 'STRING', 'STRING')
    RETURN_NAMES = ('repair', 'canvas_size', 'report', 'prompt')
    FUNCTION = 'check'
    CATEGORY = 'Flagship/Camera'

    def check(self, source_images, target_images, audio, detector, visible_only=False):
        if Path(detector).name != detector:
            raise ValueError('Face detector must be a local model filename')
        path = next((Path(folder_paths.models_dir)/sub/detector for sub in
            ('ultralytics/bbox', 'ultralytics') if (Path(folder_paths.models_dir)/sub/detector).is_file()), None)
        if path is None:
            raise FileNotFoundError(f'Local face detector missing: {detector}')
        rms = float(audio['waveform'].float().square().mean().sqrt())
        if rms < 10 ** (-45 / 20):
            result = (False, 384, 'silent soundtrack')
        else:
            model = YOLO(str(path))
            device = mm.get_torch_device()
            all_boxes, max_crop = [], 0.
            for images in (source_images, target_images):
                count, h, w, _ = images.shape
                indices = np.unique(np.linspace(0, count-1, min(count, 48)).round().astype(int))
                scale = 640 / max(h, w)
                rh, rw = round(h*scale), round(w*scale)
                boxes = []
                for start in range(0, len(indices), 8):
                    mm.throw_exception_if_processing_interrupted()
                    batch = images[indices[start:start+8], ..., :3].movedim(-1, 1).to(device=device, dtype=torch.float32)
                    batch = F.interpolate(batch, (rh, rw), mode='bilinear', align_corners=False)
                    batch = F.pad(batch, (0, 640-rw, 0, 640-rh), value=114/255)
                    for prediction in model.predict(batch, conf=.35, imgsz=640, verbose=False, device=device):
                        found = prediction.boxes.xyxy.cpu().numpy()
                        found[:, (0, 2)] *= w/rw
                        found[:, (1, 3)] *= h/rh
                        boxes.append(found.tolist())
                        for x1, y1, x2, y2 in found:
                            max_crop = max(max_crop, min(max(x2-x1, y2-y1)*2.5, w, h))
                all_boxes.append(boxes)
            result = face_policy(*all_boxes, max_crop, rms, visible_only=visible_only)
        enabled, canvas, reason = result
        speech, prompt = None, ''
        if enabled:
            speech, error = source_speech(audio)
            if speech is None:
                enabled, reason = False, error
            else:
                prompt = repair_prompt(speech)
        report = json.dumps({'repair': enabled, 'canvas': canvas, 'reason': reason,
            'sample_limit_per_video': 48, 'denoise': .35 if enabled else 0, 'source_transcript': speech,
            'policy':'largest_visible_face_only' if visible_only else 'continuous_single_face'}, ensure_ascii=False)
        print('[Flagship Camera Face Audio] '+report)
        return enabled, canvas, report, prompt


class FlagshipCameraLipRepairSwitch:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'repair': ('BOOLEAN',), 'original': ('IMAGE', {'lazy': True}),
            'corrected': ('IMAGE', {'lazy': True})}}

    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'choose'
    CATEGORY = 'Flagship/Camera'

    def check_lazy_status(self, repair, original=None, corrected=None):
        if repair and corrected is None:
            return ['corrected']
        if not repair and original is None:
            return ['original']
        return []

    def choose(self, repair, original=None, corrected=None):
        return (corrected if repair else original,)


class FlagshipCameraProtectProps:
    """Retain foreground props from the camera view, after correcting its face."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'original':('IMAGE',),'corrected':('IMAGE',),
            'segmenter':('STRING',{'default':'yolo11n-seg.pt'})},'optional':{'visibility':('H3FACEXFORM',)}}
    RETURN_TYPES=('IMAGE',)
    FUNCTION='protect'
    CATEGORY='Flagship/Camera'

    def protect(self,original,corrected,segmenter,visibility=None):
        if original.shape!=corrected.shape:raise ValueError('Prop protection requires matching camera frames')
        if Path(segmenter).name!=segmenter:raise ValueError('Prop detector must be a local model filename')
        n,h,w,_=original.shape;device=mm.get_torch_device()
        valid=np.ones(n,bool)
        if visibility is not None:
            if visibility['frames']!=n or tuple(visibility['src_size'])!=(w,h):raise ValueError('Visibility coordinates differ from camera frames')
            if any(len(visibility[key])!=n for key in ('boxes','face_rect','detected')):raise ValueError('One visibility record per frame is required')
            cw,ch=visibility['canvas']
            for i,(box,rect) in enumerate(zip(visibility['boxes'],visibility['face_rect'])):
                fw,fh=rect[2]/cw*box[2],rect[3]/ch*box[3]
                valid[i]=visibility['detected'][i] and min(fw,fh)>=24 and fw/max(fh,1)>=.45
        path=folder_paths.get_full_path('flagship_segmenters',segmenter)
        if path is None:
            print('[Flagship Camera] prop protection skipped: local segmenter missing; no download')
            result=corrected.clone();missing=torch.from_numpy(~valid).to(result.device)
            result[missing]=original[missing]
            return (result,)
        mm.free_memory(1024**3,device)
        model=YOLO(path);output=[];protected=0
        scale=640/max(h,w);rh,rw=round(h*scale),round(w*scale)
        pad=max(2,round(min(h,w)*.006))
        props={'cell phone','cup','bottle','book','remote','scissors','wine glass'}
        try:
            for start in range(0,n,8):
                mm.throw_exception_if_processing_interrupted()
                source=original[start:start+8,...,:3].movedim(-1,1).to(device=device,dtype=torch.float32)
                batch=F.interpolate(source,(rh,rw),mode='bilinear',align_corners=False)
                batch=F.pad(batch,(0,640-rw,0,640-rh),value=114/255)
                result=corrected[start:start+8,...,:3].movedim(-1,1).to(device=device,dtype=torch.float32).clone()
                for i in range(len(source)):
                    if not valid[start+i]:result[i]=source[i]
                predictions=model.predict(batch,conf=.12,imgsz=640,verbose=False,device=device)
                for i,prediction in enumerate(predictions):
                    if not valid[start+i]:continue
                    for box_index,box in enumerate(prediction.boxes):
                        if prediction.names[int(box.cls)] not in props:continue
                        if prediction.masks is not None:
                            plane=prediction.masks.data[box_index:box_index+1,None].float()
                            if plane.shape[-2:]!=(640,640):plane=F.interpolate(plane,(640,640),mode='bilinear',align_corners=False)
                            mask=F.interpolate(plane[...,:rh,:rw],(h,w),mode='bilinear',align_corners=False)
                            mask=F.max_pool2d((mask>.5).float(),2*pad+1,stride=1,padding=pad)[0,0]>.5
                            result[i]=torch.where(mask[None],source[i],result[i]);protected+=1
                            continue
                        x0,y0,x1,y1=box.xyxy[0].cpu().numpy()*np.array([w/rw,h/rh,w/rw,h/rh])
                        x0,x1=max(0,int(np.floor(x0))-pad),min(w,int(np.ceil(x1))+pad)
                        y0,y1=max(0,int(np.floor(y0))-pad),min(h,int(np.ceil(y1))+pad)
                        if x1>x0 and y1>y0:
                            result[i,:,y0:y1,x0:x1]=source[i,:,y0:y1,x0:x1];protected+=1
                output.append(result.movedim(1,-1).cpu())
        finally:
            model.to('cpu')
        print(f'[Flagship Camera] preserved {protected} visible props by instance mask (bbox fallback only when mask unavailable)')
        return (torch.cat(output),)
