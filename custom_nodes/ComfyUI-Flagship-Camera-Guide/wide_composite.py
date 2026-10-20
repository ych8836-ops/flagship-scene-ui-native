"""Place original moving foreground in a generated, static wide-view plate."""
from pathlib import Path
import cv2
import numpy as np
import torch
import torch.nn.functional as F
from ultralytics import YOLO
import folder_paths
import comfy.model_management as mm

HELD={'cell phone','cup','bottle','book','remote','scissors','wine glass'}


def place_actor(source,alpha,plate,scale,translation):
    n,_,sh,sw=source.shape;_,h,w=plate.shape;device=source.device
    xx=torch.arange(w,device=device,dtype=torch.float32)[None,:].expand(h,-1)
    yy=torch.arange(h,device=device,dtype=torch.float32)[:,None].expand(-1,w)
    grid=torch.stack((((xx-translation[0])/scale+.5)*2/sw-1,
                      ((yy-translation[1])/scale+.5)*2/sh-1),dim=-1)[None].expand(n,-1,-1,-1)
    premult=source*alpha
    small=(max(2,round(sh*min(scale,1))),max(2,round(sw*min(scale,1))))
    if small!=(sh,sw):
        premult=F.interpolate(premult,small,mode='bilinear',align_corners=False,antialias=True)
        alpha=F.interpolate(alpha,small,mode='bilinear',align_corners=False,antialias=True)
    rgb=F.grid_sample(premult,grid,mode='bilinear',padding_mode='zeros',align_corners=False)
    a=F.grid_sample(alpha,grid,mode='bilinear',padding_mode='zeros',align_corners=False).clamp(0,1)
    return (rgb+plate[None]*(1-a)).clamp(0,1)


def detect_batch(model,images,device):
    _,_,h,w=images.shape;factor=640/max(h,w);rh,rw=round(h*factor),round(w*factor)
    batch=F.interpolate(images,(rh,rw),mode='bilinear',align_corners=False)
    batch=F.pad(batch,(0,640-rw,0,640-rh),value=114/255)
    return model.predict(batch,conf=.12,imgsz=640,verbose=False,device=device),rh,rw


def person_mask(prediction,rh,rw,h,w):
    ids=[i for i,b in enumerate(prediction.boxes) if prediction.names[int(b.cls)]=='person']
    if len(ids)!=1 or prediction.masks is None:raise ValueError('Wide framing requires one unambiguous foreground person in every frame')
    i=ids[0]
    plane=prediction.masks.data[i:i+1,None].float()
    if plane.shape[-2:]!=(640,640):plane=F.interpolate(plane,(640,640),mode='bilinear',align_corners=False)
    mask=F.interpolate(plane[...,:rh,:rw],(h,w),mode='bilinear',align_corners=False)[0,0]
    box=prediction.boxes.xyxy[i].float()*torch.tensor([w/rw,h/rh,w/rw,h/rh],device=mask.device)
    return mask,box


class FlagshipCameraWideComposite:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'wide_frame':('IMAGE',),'targets':('FLAGSHIP_CAMERA_TARGETS',),
            'segmenter':('STRING',{'default':'yolo11n-seg.pt'})}}
    RETURN_TYPES=('IMAGE',)
    FUNCTION='compose'
    CATEGORY='Flagship/Camera'

    def compose(self,images,wide_frame,targets,segmenter):
        if len(wide_frame)!=1 or targets['frames']!=len(images) or tuple(targets['src_size'])!=(images.shape[2],images.shape[1]):
            raise ValueError('Wide composition needs one plate and source-aligned body measurements')
        if Path(segmenter).name!=segmenter:raise ValueError('Segmenter must be a local model filename')
        source_box=np.asarray(targets['person_boxes'][0],float)
        if not np.isfinite(source_box).all() or source_box[3]<=source_box[1]:raise ValueError('Opening body position is unavailable')
        device=mm.get_torch_device();mm.free_memory(2*1024**3,device)
        model=YOLO(folder_paths.get_full_path_or_raise('flagship_segmenters',segmenter))
        n,sh,sw,_=images.shape;_,h,w,_=wide_frame.shape;output=[]
        try:
            target=wide_frame[...,:3].movedim(-1,1).to(device=device,dtype=torch.float32)
            predictions,rh,rw=detect_batch(model,target,device)
            mask,box=person_mask(predictions[0],rh,rw,h,w)
            b=box.cpu().numpy();fraction=float((b[3]-b[1])/h)
            if not .08<=fraction<=.30:raise ValueError('Generated plate did not reach extreme-wide scale; no false camera pass')
            cut=(mask>.3).to(torch.uint8).cpu().numpy()*255
            for item in predictions[0].boxes:
                if predictions[0].names[int(item.cls)] in HELD:
                    q=item.xyxy[0].cpu().numpy()*np.array([w/rw,h/rh,w/rw,h/rh])
                    center=(q[:2]+q[2:])/2
                    if b[0]-20<=center[0]<=b[2]+20 and b[1]-20<=center[1]<=b[3]+20:
                        x0,y0,x1,y1=q.astype(int);cut[max(0,y0):min(h,y1+1),max(0,x0):min(w,x1+1)]=255
            cut=cv2.dilate(cut,np.ones((9,9),np.uint8))
            plate=(wide_frame[0,:,:,:3].float().cpu().numpy().clip(0,1)*255).round().astype(np.uint8)
            plate=cv2.inpaint(plate,cut,3,cv2.INPAINT_TELEA)
            plate=torch.from_numpy(plate).movedim(-1,0).to(device=device,dtype=torch.float32)/255
            scale=float((b[3]-b[1])/(source_box[3]-source_box[1]))
            source_anchor=np.array([(source_box[0]+source_box[2])/2,source_box[3]])
            target_anchor=np.array([(b[0]+b[2])/2,b[3]])
            translation=target_anchor-scale*source_anchor
            props=np.asarray(targets['objects']['boxes'],float)
            for start in range(0,n,8):
                mm.throw_exception_if_processing_interrupted()
                rgb=images[start:start+8,...,:3].movedim(-1,1).to(device=device,dtype=torch.float32)
                predictions,rh,rw=detect_batch(model,rgb,device);masks=[]
                for k,prediction in enumerate(predictions):
                    alpha,_=person_mask(prediction,rh,rw,sh,sw)
                    if np.isfinite(props[start+k]).all():
                        x0,y0,x1,y1=props[start+k];x0,x1=max(0,int(x0)-3),min(sw,int(np.ceil(x1))+4)
                        y0,y1=max(0,int(y0)-3),min(sh,int(np.ceil(y1))+4);alpha[y0:y1,x0:x1]=1
                    masks.append(alpha)
                result=place_actor(rgb,torch.stack(masks)[:,None],plate,scale,translation)
                output.append(result.movedim(1,-1).cpu())
        finally:model.to('cpu')
        print(f'[Flagship Camera Wide] original live actor, generated static plate; actor height {fraction:.1%}; 2.5D composition')
        return (torch.cat(output),)
