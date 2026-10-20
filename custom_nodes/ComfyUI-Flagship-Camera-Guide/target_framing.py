"""Locate the selected performer's knees and visible held object before framing."""
from collections import Counter
import numpy as np
import torch
import torch.nn.functional as F
from ultralytics import YOLO
import folder_paths
import comfy.model_management
from .source_framing import resample_source
from .target_math import target_boxes


HELD_OBJECTS = {'cell phone', 'cup', 'bottle', 'book', 'remote', 'scissors', 'wine glass'}


def macro_focus(frames, targets, crops):
    """Keep the measured prop pixels; gently defocus only the surrounding area."""
    device=comfy.model_management.get_torch_device()
    n,h,w,_=frames.shape
    props=np.asarray(targets['objects']['boxes'],np.float32).copy()
    known=np.isfinite(props).all(1)
    for axis in range(4):props[:,axis]=np.interp(np.arange(n),np.flatnonzero(known),props[known,axis])
    x=torch.arange(w,device=device,dtype=torch.float32)[None,None,:]
    y=torch.arange(h,device=device,dtype=torch.float32)[None,:,None]
    radius=max(2,round(min(w,h)/128));sigma=max(.8,radius/2)
    t=torch.arange(-radius,radius+1,device=device,dtype=torch.float32)
    kernel=torch.exp(-t.square()/(2*sigma*sigma));kernel/=kernel.sum()
    horizontal=kernel[None,None,None,:].expand(3,1,1,-1)
    vertical=kernel[None,None,:,None].expand(3,1,-1,1)
    result=[]
    for start in range(0,n,8):
        comfy.model_management.throw_exception_if_processing_interrupted()
        end=min(start+8,n)
        source=frames[start:end].movedim(-1,1).to(device)
        blurred=F.conv2d(F.pad(source,(radius,radius,0,0),mode='replicate'),horizontal,groups=3)
        blurred=F.conv2d(F.pad(blurred,(0,0,radius,radius),mode='replicate'),vertical,groups=3)
        p=torch.from_numpy(props[start:end].copy()).to(device)
        c=torch.from_numpy(np.asarray(crops[start:end],np.float32)).to(device)
        left=(p[:,0]-c[:,0])/c[:,2]*w;right=(p[:,2]-c[:,0])/c[:,2]*w
        top=(p[:,1]-c[:,1])/c[:,3]*h;bottom=(p[:,3]-c[:,1])/c[:,3]*h
        dx=torch.maximum(left[:,None,None]-x,x-right[:,None,None]).clamp_min(0)
        dy=torch.maximum(top[:,None,None]-y,y-bottom[:,None,None]).clamp_min(0)
        alpha=(1-torch.maximum(dx,dy)/max(4,min(w,h)*.04)).clamp(0,1)[:,None]
        result.append((source*alpha+blurred*(1-alpha)).movedim(1,-1).cpu())
    return torch.cat(result)


def held_object(result, joints):
    candidates = []
    for box in result.boxes:
        name = result.names[int(box.cls)]
        if name not in HELD_OBJECTS:continue
        xy = box.xyxy[0].cpu().numpy()
        center = (xy[:2] + xy[2:]) / 2
        for elbow, wrist in [(7,9), (8,10)]:
            if min(joints[elbow,2], joints[wrist,2]) < .4:continue
            reach = max(16, float(np.linalg.norm(joints[wrist,:2] - joints[elbow,:2])) * 1.5)
            distance = float(np.linalg.norm(center - joints[wrist,:2]))
            if distance <= reach:
                candidates.append((float(box.conf) / (1 + distance / reach), name, xy.tolist()))
    return max(candidates, key=lambda x:x[0]) if candidates else None


class FlagshipCameraVisibleTargets:
    @classmethod
    def INPUT_TYPES(cls):
        files = folder_paths.get_filename_list('flagship_segmenters')
        return {'required': {'images': ('IMAGE',), 'face_transform': ('H3FACEXFORM',),
            'pose_model': ([f for f in files if 'pose' in f and f.endswith('.pt')] or ['yolo11n-pose.pt'],),
            'segmenter': ([f for f in files if 'seg' in f and f.endswith('.pt')] or ['yolo11n-seg.pt'],)}}
    RETURN_TYPES = ('FLAGSHIP_CAMERA_TARGETS',)
    FUNCTION = 'measure'
    CATEGORY = 'Flagship/Camera'

    def measure(self, images, face_transform, pose_model, segmenter):
        n, h, w, _ = images.shape
        if face_transform['frames'] != n or tuple(face_transform['src_size']) != (w,h):
            raise ValueError('Target measurements require face tracking from the same source frame batch')
        device = comfy.model_management.get_torch_device()
        comfy.model_management.free_memory(1024 * 1024 * 1024, device)
        pose = YOLO(folder_paths.get_full_path_or_raise('flagship_segmenters', pose_model))
        segment = YOLO(folder_paths.get_full_path_or_raise('flagship_segmenters', segmenter))
        poses, people, props, people_count = [], [], [], []
        cw, ch = face_transform['canvas']
        try:
            for start in range(0,n,8):
                comfy.model_management.throw_exception_if_processing_interrupted()
                rgb = (images[start:start+8,...,:3].detach().float().cpu().numpy().clip(0,1) * 255).astype(np.uint8)
                frames = [np.ascontiguousarray(frame[...,::-1]) for frame in rgb]
                bodies = pose.predict(frames, imgsz=640, device=str(device), conf=.3, verbose=False)
                objects = segment.predict(frames, imgsz=640, device=str(device), conf=.12, retina_masks=False, verbose=False)
                for local, (body, obj) in enumerate(zip(bodies,objects)):
                    i = start + local
                    people_count.append(len(body.boxes))
                    if not face_transform['detected'][i]:
                        poses.append(np.full((17,3),np.nan));people.append(np.full(4,np.nan));props.append(None)
                        continue
                    bx,by,bw,bh = face_transform['boxes'][i]
                    rx,ry,rw,rh = face_transform['face_rect'][i]
                    point = np.array([bx + (rx+rw/2)/cw*bw, by + (ry+rh/2)/ch*bh])
                    boxes = body.boxes.xyxy.cpu().numpy()
                    inside = [j for j,b in enumerate(boxes) if b[0] <= point[0] <= b[2] and b[1] <= point[1] <= b[3]]
                    if len(inside) != 1:
                        poses.append(np.full((17,3),np.nan));people.append(np.full(4,np.nan));props.append(None)
                        continue
                    j = inside[0]
                    joints = body.keypoints.data[j].cpu().numpy()
                    poses.append(joints);people.append(boxes[j]);props.append(held_object(obj,joints))
        finally:
            pose.to('cpu');segment.to('cpu')
        counts = Counter(p[1] for p in props if p is not None)
        name = counts.most_common(1)[0][0] if counts else None
        boxes = [p[2] if p is not None and p[1] == name else [float('nan')] * 4 for p in props]
        return ({'frames':n,'src_size':[w,h],'joints':np.stack(poses),'person_boxes':np.stack(people),'people_count':people_count,
                 'objects':{'name':name,'boxes':boxes}},)


class FlagshipCameraTargetFraming:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'targets': ('FLAGSHIP_CAMERA_TARGETS',),
            'mode': (['medium wide shot','insert shot','macro shot'],),
            'width': ('INT', {'default':320,'min':32,'max':4096,'step':32}),
            'height': ('INT', {'default':576,'min':32,'max':4096,'step':32}),
            'fallback_images': ('IMAGE', {'lazy': True})}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'frame'
    CATEGORY = 'Flagship/Camera'

    def check_lazy_status(self, images, targets, mode, width, height, fallback_images=None):
        try:
            target_boxes(targets,mode,width,height)
        except ValueError:
            if fallback_images is None:return ['fallback_images']
        return []

    def frame(self, images, targets, mode, width, height, fallback_images=None):
        n,h,w,_ = images.shape
        if targets['frames'] != n or tuple(targets['src_size']) != (w,h):
            raise ValueError('Measured framing targets do not match the source frames')
        try:
            boxes = target_boxes(targets,mode,width,height)
        except ValueError as error:
            print(f'[Flagship Camera] measured framing bypass: {error}; original camera branch retained')
            return (fallback_images,)
        print(f'[Flagship Camera] measured {mode}: {n} original frames; held target={targets["objects"]["name"]}')
        framed=resample_source(images,boxes,width,height)
        return (macro_focus(framed,targets,boxes) if mode=='macro shot' else framed,)
