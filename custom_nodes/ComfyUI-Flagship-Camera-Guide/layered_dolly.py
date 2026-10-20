"""Small axial dolly zooms: source performer over a depth-projected background."""
from pathlib import Path
import warnings
import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt
import torch
import torch.nn.functional as F
from ultralytics import YOLO
import folder_paths
import comfy.model_management
from .camera_timing import camera_progress


def build_layers(images, geometry, masks):
    depth = geometry['points'][...,2].copy()
    n,h,w = depth.shape
    if len(images)!=n or masks.shape!=(n,h,w):
        return {'valid':False,'reason':'source, depth and mask timelines differ'}
    good=np.isfinite(depth)&(depth>.01)
    if good.mean()<.99:return {'valid':False,'reason':'insufficient valid source depth'}
    actor=masks>.1
    dilated=np.stack([cv2.dilate(np.uint8(m),np.ones((5,5),np.uint8))>0 for m in actor])
    observed=(~dilated).any(0)
    if observed.mean()<.3:return {'valid':False,'reason':'too little observed background'}
    rgb=np.stack([cv2.resize(im.detach().float().cpu().numpy()[...,:3],(w,h),interpolation=cv2.INTER_AREA) for im in images])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        clean=np.nanmedian(np.where(dilated[...,None],np.nan,rgb),axis=0)
    # Reject a moving source camera/environment; temporal filling assumes a fixed background.
    error=np.abs(rgb-np.nan_to_num(clean)).mean(-1)
    static_error=float(np.median(error[~dilated]))
    if static_error>.035:return {'valid':False,'reason':f'moving source background ({static_error:.4f})'}
    clean=cv2.inpaint(np.uint8(np.nan_to_num(clean).clip(0,1)*255),(~observed).astype(np.uint8),7,cv2.INPAINT_TELEA).astype(np.float32)/255
    _,nearest=distance_transform_edt(~observed,return_indices=True)
    back_depth=np.median(depth,axis=0)[nearest[0],nearest[1]]
    subject_depth=float(np.median(depth[actor]))
    k=np.median(geometry['intrinsics'],axis=0)
    alpha=np.stack([cv2.GaussianBlur(m.astype(np.float32),(3,3),.6) for m in masks])
    return {'valid':True,'frames':n,'src_size':[images.shape[2],images.shape[1]],
        'depth':depth,'dilated':dilated,'alpha':alpha,'clean':clean,'back_depth':back_depth,
        'subject_depth':subject_depth,'principal':[float(k[0,2]),float(k[1,2])],
        'static_background_error':static_error,'unseen_source_fraction':float((~observed).mean())}


class FlagshipCameraDollyLayers:
    @classmethod
    def INPUT_TYPES(cls):
        choices=[f for f in folder_paths.get_filename_list('flagship_segmenters') if 'seg' in f and f.endswith('.pt')]
        return {'required':{'images':('IMAGE',),'face_transform':('H3FACEXFORM',),
            'geometry_file':('STRING',{'default':'source.npz'}),'segmenter':(choices or ['yolo11n-seg.pt'],)}}
    RETURN_TYPES=('FLAGSHIP_DOLLY_LAYERS',)
    FUNCTION='prepare'
    CATEGORY='Flagship/Camera'

    def prepare(self,images,face_transform,geometry_file,segmenter):
        n,sh,sw,_=images.shape
        if face_transform['frames']!=n or tuple(face_transform['src_size'])!=(sw,sh):
            raise ValueError('Dolly tracking must refer to this exact source batch')
        path=Path(folder_paths.get_output_directory())/'CameraGeometry'/Path(geometry_file).name
        with np.load(path,allow_pickle=False) as d:
            geometry={key:d[key] for key in ('points','intrinsics')}
        if len(geometry['points'])!=n:raise ValueError('Dolly depth timeline differs from source')
        h,w=geometry['points'].shape[1:3]
        masks=np.zeros((n,h,w),np.float32);known=np.zeros(n,bool)
        device=comfy.model_management.get_torch_device()
        comfy.model_management.free_memory(1024**3,device)
        model=YOLO(folder_paths.get_full_path_or_raise('flagship_segmenters',segmenter))
        cw,ch=face_transform['canvas']
        try:
            for start in range(0,n,8):
                comfy.model_management.throw_exception_if_processing_interrupted()
                rgb=(images[start:start+8,...,:3].detach().float().cpu().numpy().clip(0,1)*255).astype(np.uint8)
                results=model.predict([np.ascontiguousarray(im[...,::-1]) for im in rgb],imgsz=640,
                    conf=.12,device=str(device),retina_masks=True,verbose=False)
                for offset,r in enumerate(results):
                    i=start+offset
                    if not face_transform['detected'][i] or r.masks is None:continue
                    people=[j for j,b in enumerate(r.boxes) if r.names[int(b.cls)]=='person' and float(b.conf)>.3]
                    if len(people)!=1:continue
                    j=people[0];box=r.boxes.xyxy[j].cpu().numpy()
                    bx,by,bw,bh=face_transform['boxes'][i];rx,ry,rw,rh=face_transform['face_rect'][i]
                    fx,fy=bx+(rx+rw/2)/cw*bw,by+(ry+rh/2)/ch*bh
                    if not (box[0]<=fx<=box[2] and box[1]<=fy<=box[3]):continue
                    m=r.masks.data[j].cpu().numpy().copy()
                    # Keep visible handheld props with the original performer pixels.
                    for prop in r.boxes:
                        if r.names[int(prop.cls)] not in {'cell phone','cup','bottle','book','remote'}:continue
                        x0,y0,x1,y1=prop.xyxy[0].cpu().numpy();cx,cy=(x0+x1)/2,(y0+y1)/2
                        if box[0]<=cx<=box[2] and box[1]<=cy<=box[3]:
                            m[max(0,int(y0)-3):min(sh,int(y1)+4),max(0,int(x0)-3):min(sw,int(x1)+4)]=1
                    masks[i]=cv2.resize(m,(w,h),interpolation=cv2.INTER_AREA);known[i]=True
        finally:
            model.to('cpu')
        if known.mean()<.9:return ({'valid':False,'reason':'one tracked source person required in at least 90% of frames'},)
        runs=np.split(np.flatnonzero(~known),np.where(np.diff(np.flatnonzero(~known))>1)[0]+1)
        if any(len(run)>3 for run in runs):return ({'valid':False,'reason':'source mask gap exceeds three frames'},)
        valid_indices=np.flatnonzero(known)
        for i in np.flatnonzero(~known):masks[i]=masks[valid_indices[np.argmin(abs(valid_indices-i))]]
        return (build_layers(images,geometry,masks),)


def render_dolly(images,layers,width,height,direction,strength,speed,easing):
    n=layers['frames'];device=comfy.model_management.get_torch_device()
    cx,cy=layers['principal'];zactor=layers['subject_depth']
    yy,xx=torch.meshgrid((torch.arange(height,device=device,dtype=torch.float32)+.5)/height,
        (torch.arange(width,device=device,dtype=torch.float32)+.5)/width,indexing='ij')
    target=torch.stack((xx-cx,yy-cy),-1)[None]
    center=torch.tensor([cx,cy],device=device,dtype=torch.float32)
    clean=torch.from_numpy(layers['clean']).to(device)[None].movedim(-1,1)
    back=torch.from_numpy(layers['back_depth']).to(device)[None,None]
    progress=np.array([camera_progress(i/max(n-1,1),speed,easing) for i in range(n)],np.float32)
    amount=min(.30,.7*max(0.,float(strength)))*(1 if direction=='in' else -1)
    output=[];unseen=[]
    h,w=layers['depth'].shape[1:]
    for start in range(0,n,8):
        comfy.model_management.throw_exception_if_processing_interrupted()
        end=min(start+8,n);count=end-start
        actor=images[start:end,...,:3].movedim(-1,1).to(device=device,dtype=torch.float32)
        rgb=F.interpolate(actor,size=(h,w),mode='area')
        mask=torch.from_numpy(layers['dilated'][start:end]).to(device)[:,None]
        depth=torch.from_numpy(layers['depth'][start:end]).to(device)[:,None]
        field=torch.where(mask,back,depth)
        pixels=torch.where(mask,clean,rgb)
        d=torch.from_numpy(progress[start:end]).to(device)[:,None,None,None]*amount*zactor
        focal=1-d/zactor
        uv=(target/focal+center).expand(count,-1,-1,-1)
        for _ in range(6):
            z=F.grid_sample(field,uv*2-1,mode='bilinear',padding_mode='border',align_corners=False).movedim(1,-1)
            uv=target/focal*(1-d/z.clamp_min(.01))+center
        unseen.extend(((uv<0)|(uv>1)).any(-1).float().mean((1,2)).cpu().tolist())
        sampled=F.grid_sample(pixels,uv*2-1,mode='bilinear',padding_mode='border',align_corners=False)
        alpha=torch.from_numpy(layers['alpha'][start:end]).to(device)[:,None]
        alpha=F.interpolate(alpha,size=(height,width),mode='bilinear',align_corners=False).clamp(0,1)
        actor=F.interpolate(actor,size=(height,width),mode='area')
        result=(sampled*(1-alpha)+actor*alpha).clamp(0,1)
        result=torch.where((d==0).movedim(-1,1),actor,result)
        output.append(result.movedim(1,-1).cpu())
    if max(unseen)>.12:raise ValueError('Dolly projection reveals more than 12% outside the source; reduce strength')
    return torch.cat(output),{'max_unseen_fraction':max(unseen),'amount':amount,'subject_plane_scale':1.}


class FlagshipCameraLayeredDolly:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'layers':('FLAGSHIP_DOLLY_LAYERS',),
            'width':('INT',{'default':320,'min':32,'max':4096,'step':32}),
            'height':('INT',{'default':576,'min':32,'max':4096,'step':32}),
            'direction':(['in','out'],),'strength':('FLOAT',{'default':.35,'min':0,'max':1}),
            'speed':(['very slow','slow','moderate','fast','very fast'],),
            'easing':(['linear','ease in','ease out','ease in out','snap settle'],),
            'fallback_images':('IMAGE',{'lazy':True})}}
    RETURN_TYPES=('IMAGE',)
    FUNCTION='render'
    CATEGORY='Flagship/Camera'

    def check_lazy_status(self,images,layers,width,height,direction,strength,speed,easing,fallback_images=None):
        if not layers['valid'] and fallback_images is None:return ['fallback_images']
        return []

    def render(self,images,layers,width,height,direction,strength,speed,easing,fallback_images=None):
        if not layers['valid']:
            print('[Flagship Dolly] source-layer bypass: '+layers['reason'])
            return (fallback_images,)
        if layers['frames']!=len(images) or layers['src_size']!=[images.shape[2],images.shape[1]]:
            raise ValueError('Dolly layers do not belong to this source')
        frames,report=render_dolly(images,layers,width,height,direction,strength,speed,easing)
        print(f'[Flagship Dolly] {direction}: source performer preserved, coupled focal/axial background projection; {report}')
        return (frames,)
