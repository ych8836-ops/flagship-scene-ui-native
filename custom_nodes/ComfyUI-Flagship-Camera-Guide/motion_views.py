"""Choose camera-view anchors from observed background change and body projection."""
from pathlib import Path
import json
import math
import numpy as np
import torch
import torch.nn.functional as F
from ultralytics import YOLO
import folder_paths
import comfy.model_management as mm
from .wide_composite import detect_batch


def select_views(deltas,signature,mode,strength):
    delta=np.asarray(deltas,float);n=len(delta)+1
    if n<20 or not np.isfinite(delta).all() or np.any(delta<0):raise ValueError('Invalid camera draft motion measurements')
    ratio=None;stop=n-1
    if mode=='hero cam':
        values=np.asarray(signature,float);known=np.isfinite(values)
        opening=values[:max(5,n//10)];opening=opening[np.isfinite(opening)]
        if len(opening)<3 or known.mean()<.6:raise ValueError('Hero draft does not have enough reliable body-view measurements')
        baseline=float(np.median(opening))
        if abs(baseline)<.1:raise ValueError('Opening body is already too side-on to measure a relative hero arc')
        curve=np.interp(np.arange(n),np.flatnonzero(known),values[known])/baseline
        padded=np.pad(curve,(2,2),mode='edge');curve=np.array([np.median(padded[i:i+5]) for i in range(n)])
        target=math.cos(math.radians(min(85,max(15,70*float(strength)/.35))))
        hits=[i for i in range(5,n-2) if -.15<curve[i] and np.all(curve[i:i+3]<=target) and np.sum(known[max(0,i-2):i+3])>=2]
        if hits:stop=hits[0]
        else:
            candidates=[i for i in range(5,n) if known[i] and -.15<curve[i]<=.65]
            if not candidates:raise ValueError('Camera draft did not reveal a sufficiently reliable hero side view')
            stop=min(candidates,key=lambda i:abs(curve[i]-target))
        ratio=float(curve[stop])
    floor=float(np.quantile(delta,.1));motion=np.maximum(delta-floor,0)
    cumulative=np.r_[0,np.cumsum(motion)]
    if mode=='aerial pullback':
        amount=min(1,max(.01,float(strength)/.35))
        stop=min(n-1,int(np.searchsorted(cumulative,cumulative[-1]*amount)))
    total=float(cumulative[stop])
    if stop<12 or total<.01:raise ValueError('Camera draft has too little reliable camera travel')
    indices=[int(np.searchsorted(cumulative[:stop+1],total*t)) for t in (.25,.5,.75)]+[stop]
    if len(set(indices))!=4 or indices[0]<1:raise ValueError('Camera draft jumped between views instead of moving continuously')
    return indices,{'indices':indices,'end_body_projection_ratio':ratio,'background_change':total,
                   'scope':'relative body-view proxy and observed image change; not calibrated camera degrees'}


class FlagshipCameraMotionViews:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'mode':(['aerial pullback','hero cam'],),
            'strength':('FLOAT',{'default':.35,'min':.01,'max':1}),
            'pose_model':('STRING',{'default':'yolo11n-pose.pt'})}}
    RETURN_TYPES=('IMAGE','IMAGE','IMAGE','IMAGE','STRING')
    RETURN_NAMES=('quarter','middle','three_quarters','end','report')
    FUNCTION='measure'
    CATEGORY='Flagship/Camera'

    def measure(self,images,mode,strength,pose_model):
        if Path(pose_model).name!=pose_model:raise ValueError('Pose detector must be a local model filename')
        n,h,w,_=images.shape;device=mm.get_torch_device();mm.free_memory(1024**3,device)
        model=YOLO(folder_paths.get_full_path_or_raise('flagship_segmenters',pose_model))
        boxes=[];signature=[];parts=[];scale=288/max(h,w);gh,gw=round(h*scale),round(w*scale)
        try:
            for start in range(0,n,8):
                mm.throw_exception_if_processing_interrupted()
                rgb=images[start:start+8,...,:3].movedim(-1,1).to(device=device,dtype=torch.float32)
                parts.append(F.interpolate(rgb,(gh,gw),mode='area'))
                predictions,rh,rw=detect_batch(model,rgb,device)
                for prediction in predictions:
                    ids=[i for i,b in enumerate(prediction.boxes) if prediction.names[int(b.cls)]=='person']
                    if not ids:boxes.append([np.nan]*4);signature.append(np.nan);continue
                    xy=prediction.boxes.xyxy
                    i=max(ids,key=lambda i:float((xy[i,2]-xy[i,0])*(xy[i,3]-xy[i,1])))
                    box=xy[i].float().cpu().numpy()*np.array([gw/rw,gh/rh,gw/rw,gh/rh]);boxes.append(box)
                    joints=prediction.keypoints.data[i].float().cpu().numpy().copy()
                    joints[:,0]*=w/rw;joints[:,1]*=h/rh
                    if min(joints[[5,6,11,12],2])<.25:signature.append(np.nan);continue
                    torso=np.linalg.norm((joints[5,:2]+joints[6,:2]-joints[11,:2]-joints[12,:2])/2)
                    signature.append(float((joints[6,0]-joints[5,0])/torso) if torso>=24 else np.nan)
        finally:model.to('cpu')
        boxes=np.asarray(boxes,float);valid=np.isfinite(boxes).all(1)
        if valid.mean()<.85:raise ValueError('Camera draft lost the tracked performer')
        for axis in range(4):boxes[:,axis]=np.interp(np.arange(n),np.flatnonzero(valid),boxes[valid,axis])
        video=torch.cat(parts);b=torch.from_numpy(boxes.astype(np.float32)).to(device)
        pad=(b[:,2:]-b[:,:2])*.05;b[:,:2]-=pad;b[:,2:]+=pad
        xx=torch.arange(gw,device=device)[None,None,:];yy=torch.arange(gh,device=device)[None,:,None]
        background=~((xx>=b[:,0,None,None])&(xx<=b[:,2,None,None])&(yy>=b[:,1,None,None])&(yy<=b[:,3,None,None]))
        pair=background[1:]&background[:-1]
        if float(pair.float().mean())<.03:raise ValueError('Too little visible background to distribute the camera path reliably')
        luma=(video*torch.tensor([.2126,.7152,.0722],device=device)[None,:,None,None]).sum(1,keepdim=True)
        kernel=torch.tensor([[-1,0,1],[-2,0,2],[-1,0,1]],device=device,dtype=torch.float32)
        kernels=torch.stack([kernel,kernel.T])[:,None]/8
        edge=F.conv2d(luma,kernels,padding=1).abs().sum(1)
        weight=((edge[1:]+edge[:-1])*.5+.01)*pair
        delta=((video[1:]-video[:-1]).abs().mean(1)*weight).sum((1,2))/weight.sum((1,2)).clamp_min(1e-6)
        indices,report=select_views(delta.cpu().numpy(),signature,mode,strength)
        print('[Flagship Camera Views] '+json.dumps(report))
        return (*(images[i:i+1] for i in indices),json.dumps(report))
