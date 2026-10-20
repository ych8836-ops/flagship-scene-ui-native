"""Depth-guided camera controls for native ComfyUI and SDK adapters."""
from pathlib import Path
import json
import hashlib
import numpy as np
import torch
import torch.nn.functional as F
import cv2
import folder_paths
from .mesh_raster import raster_mesh
from .source_framing import FlagshipCameraSourceFraming
from .target_framing import FlagshipCameraVisibleTargets, FlagshipCameraTargetFraming
from .multiangle import FlagshipMultiAngle, parse_path, sample_path, radius_scale
from .multiangle_zoom import FlagshipMultiAngleSourceZoom
from .lip_repair import FlagshipCameraLipRepairGuard, FlagshipCameraLipRepairSwitch, FlagshipCameraProtectProps
from .camera_timing import camera_progress
from .layered_dolly import FlagshipCameraDollyLayers, FlagshipCameraLayeredDolly
from .crossview_guide import FlagshipCrossViewGuide
from .orbit_control import FlagshipCameraOrbitEligibility
from .motion_control import FlagshipCameraMotionEligibility
from .wide_composite import FlagshipCameraWideComposite
from .motion_views import FlagshipCameraMotionViews

WEB_DIRECTORY = "./web"
if 'flagship_segmenters' not in folder_paths.folder_names_and_paths:
    folder_paths.add_model_folder_path('flagship_segmenters',str(Path(folder_paths.models_dir)/'flagship_segmenters'))


class FlagshipSaveGeometry:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geometry": ("MOGE_GEOMETRY",), "name": ("STRING", {"default": "camera_source"})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "Flagship/Camera"

    def save(self, geometry, name):
        if not name.replace('_', '').isalnum():
            raise ValueError('Geometry name must be a simple identifier')
        target = Path(folder_paths.get_output_directory()) / 'CameraGeometry' / (name + '.npz')
        target.parent.mkdir(parents=True, exist_ok=True)
        arrays = {key: value.detach().float().cpu().numpy() if value.dtype != torch.bool else value.cpu().numpy()
                  for key, value in geometry.items() if isinstance(value, torch.Tensor)}
        with target.with_suffix('.tmp').open('wb') as stream:
            np.savez(stream, **arrays)
        target.with_suffix('.tmp').replace(target)
        return {"ui": {"text": [str(target)]}, "result": (str(target),)}


def optical_rotation(mode,degrees,fraction):
    theta=np.deg2rad(degrees*fraction*(1 if mode in ('pan_left','tilt_up') else -1))
    c,s=np.cos(theta),np.sin(theta)
    if mode in ('pan_left','pan_right'):return np.array([[c,0.,s],[0.,1.,0.],[-s,0.,c]])
    if mode in ('tilt_up','tilt_down'):return np.array([[1.,0.,0.],[0.,c,s],[0.,-s,c]])
    raise ValueError('Source projection supports optical-center pan/tilt only, never orbit or dolly.')


def camera_matrix(pivot, yaw, elevation, radius=None):
    """World-to-camera rotation for OpenCV x-right/y-down/z-forward coordinates."""
    radius = float(np.linalg.norm(pivot)) if radius is None else float(radius)
    y, e = np.deg2rad([yaw, elevation])
    center = pivot + radius * np.array([-np.sin(y)*np.cos(e), -np.sin(e), -np.cos(y)*np.cos(e)])
    forward = (pivot - center) / radius
    right = np.cross(np.array([0., 1., 0.]), forward)
    # Exact overhead uses the limiting camera-right direction, avoiding a singular look-at.
    if np.linalg.norm(right) < 1e-5:
        right = np.array([np.cos(y), 0., -np.sin(y)])
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    return center, np.stack([right, down, forward])


def splat(points, colors, intrinsics, center, rotation, width, height, lo, hi):
    pts = (points.reshape(-1, 3) - center) @ rotation.T
    good = np.isfinite(pts).all(1) & (pts[:, 2] > .01)
    pts = pts[good]; rgb = colors.reshape(-1, 3)[good]
    u = np.rint((pts[:, 0] / pts[:, 2] * intrinsics[0, 0] + intrinsics[0, 2])*width - .5).astype(np.int32)
    v = np.rint((pts[:, 1] / pts[:, 2] * intrinsics[1, 1] + intrinsics[1, 2])*height - .5).astype(np.int32)
    # 3x3 point footprints remove raster sampling gaps. Nearest depth always wins.
    xx = (u[:, None] + np.array([-1,0,1,-1,0,1,-1,0,1])).reshape(-1)
    yy = (v[:, None] + np.array([-1,-1,-1,0,0,0,1,1,1])).reshape(-1)
    zz = np.repeat(pts[:, 2], 9); cc = np.repeat(rgb, 9, axis=0)
    inside = (xx>=0)&(xx<width)&(yy>=0)&(yy<height)
    xx, yy, zz, cc = xx[inside], yy[inside], zz[inside], cc[inside]
    order = np.argsort(zz, kind='stable')
    flat = yy[order]*width + xx[order]
    _, first = np.unique(flat, return_index=True)
    picked = order[first]; pix = yy[picked]*width+xx[picked]
    disparity = np.zeros(height*width, np.float32)
    result = np.zeros((height*width,3),np.float32)
    disparity[pix] = np.clip((1/zz[picked]-lo)/(hi-lo),0,1)
    result[pix] = cc[picked]
    holes = np.ones(height*width,np.uint8);holes[pix]=0
    disparity=disparity.reshape(height,width);result=result.reshape(height,width,3);holes=holes.reshape(height,width)
    # Navier-Stokes depth inpainting created false wavy contours in the generated wall.
    # Extend local samples into tiny raster gaps; use a static back-wall plane only
    # for genuinely unseen large regions. This is still a guide, not recovered geometry.
    from scipy.ndimage import distance_transform_edt
    distance,indices=distance_transform_edt(holes,return_indices=True)
    nearest=disparity[indices[0],indices[1]]
    uvx,uvy=np.meshgrid((np.arange(width)+.5)/width,(np.arange(height)+.5)/height)
    rays=np.stack([(uvx-intrinsics[0,2])/intrinsics[0,0],(uvy-intrinsics[1,2])/intrinsics[1,1],np.ones_like(uvx)],-1)@rotation
    source_z=points[...,2];background_z=np.quantile(source_z[np.isfinite(source_z)],.95)
    t=(background_z-center[2])/np.where(abs(rays[...,2])<1e-5,1e-5,rays[...,2])
    plane=np.clip((1/np.maximum(t,.01)-lo)/(hi-lo),0,1)
    filled=np.where((distance>3)&(t>.01),plane,nearest).astype(np.float32)
    disparity=np.where(holes,cv2.GaussianBlur(filled,(0,0),1.),disparity)
    preview=cv2.inpaint(np.uint8(result*255),holes,5,cv2.INPAINT_TELEA).astype(np.float32)/255
    return disparity, preview, holes


def mesh_project(points, colors, intrinsics, center, rotation, width, height, lo, hi,make_preview=True,floor_y=None):
    z,rgb=raster_mesh(points,colors,intrinsics,center,rotation,width,height)
    holes=~np.isfinite(z)
    disparity=np.clip((1/np.maximum(z,.01)-lo)/(hi-lo),0,1).astype(np.float32)
    from scipy.ndimage import distance_transform_edt
    _,indices=distance_transform_edt(holes,return_indices=True)
    # Mesh triangles already cover visible surfaces continuously. Remaining holes
    # are true disocclusions, not sampled-point stripes, so smooth nearest extension
    # no longer engraves raster lines into the guide.
    filled=disparity[indices[0],indices[1]]
    _,labels=cv2.connectedComponents(holes.astype(np.uint8),connectivity=4)
    exterior_ids=np.unique(np.concatenate([labels[0],labels[-1],labels[:,0],labels[:,-1]]))
    exterior=holes & np.isin(labels,exterior_ids[exterior_ids!=0])
    if floor_y is not None:
        from scipy.ndimage import binary_fill_holes
        silhouette=binary_fill_holes(cv2.morphologyEx((~holes).astype(np.uint8),cv2.MORPH_CLOSE,np.ones((5,5),np.uint8)))
        exterior=holes & ~silhouette
    ux,uy=np.meshgrid((np.arange(width)+.5)/width,(np.arange(height)+.5)/height)
    rays=np.stack([(ux-intrinsics[0,2])/intrinsics[0,0],(uy-intrinsics[1,2])/intrinsics[1,1],np.ones_like(ux)],-1)@rotation
    source_z=points[...,2];back_z=np.quantile(source_z[np.isfinite(source_z)],.95)
    axis=2 if floor_y is None else 1
    plane_position=back_z if floor_y is None else floor_y
    t=(plane_position-center[axis])/np.where(abs(rays[...,axis])<1e-5,1e-5,rays[...,axis])
    plane=np.clip((1/np.maximum(t,.01)-lo)/(hi-lo),0,1)
    filled=np.where(exterior & (t>.01),plane,filled).astype(np.float32)
    disparity=np.where(holes,cv2.GaussianBlur(filled,(0,0),2.),disparity)
    disparity=cv2.medianBlur(disparity,3)
    missing=holes.astype(np.uint8)
    preview=(cv2.inpaint(np.uint8(np.clip(rgb,0,1)*255),missing,5,cv2.INPAINT_TELEA).astype(np.float32)/255
             if make_preview else np.clip(rgb,0,1))
    return disparity,preview,missing


class FlagshipGeometryCamera:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geometry_file": ("STRING", {"default": "camera_source.npz"}),
            "mode": (["orbit_left", "orbit_right", "pan_left", "pan_right", "tilt_up", "tilt_down", "top_down"],),
            "degrees": ("FLOAT", {"default": 35., "min": 0., "max": 360.}),
            "width": ("INT", {"default": 384, "min": 64, "max": 2048}),
            "height": ("INT", {"default": 688, "min": 64, "max": 2048})},
            "optional":{"projection":(["mesh","points"],{"default":"mesh"}),
                        "first_frame_only":("BOOLEAN",{"default":False}),"depth_only":("BOOLEAN",{"default":False}),
                        "speed":(["very slow","slow","moderate","fast","very fast"],{"default":"slow"}),
                        "easing":(["linear","ease in","ease out","ease in out","snap settle"],{"default":"linear"})}}
    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK")
    RETURN_NAMES = ("depth_guide", "reprojection_preview", "unseen_mask")
    FUNCTION = "render"
    CATEGORY = "Flagship/Camera"

    def render(self, geometry_file, mode, degrees, width, height,projection='mesh',first_frame_only=False,depth_only=False,speed='slow',easing='linear'):
        path = Path(folder_paths.get_output_directory())/'CameraGeometry'/Path(geometry_file).name
        key = hashlib.sha256(f'v8_optical_source:{path.stat().st_mtime_ns}:{mode}:{degrees}:{width}:{height}:{projection}:{first_frame_only}:{depth_only}:{speed}:{easing}'.encode()).hexdigest()[:16]
        cache = path.parent/('guide_'+key+'.npz')
        if cache.exists():
            with np.load(cache,allow_pickle=False) as data:
                depth=np.repeat(data['depth'][...,None].astype(np.float32)/65535,3,-1)
                return torch.from_numpy(depth),torch.from_numpy(data['rgb'].astype(np.float32)/255),torch.from_numpy(data['holes'].astype(np.float32))
        with np.load(path, allow_pickle=False) as data:
            points=data['points'];colors=data['image'];intrinsics=data['intrinsics']
            floor_y=float(data['scene_floor_y'].ravel()[0]) if 'scene_floor_y' in data else None
        n,h,w,_=points.shape
        z=points[...,2]
        center_depth=np.nanmedian(np.where(np.isfinite(z[:,int(h*.25):int(h*.7),int(w*.35):int(w*.65)]),
            z[:,int(h*.25):int(h*.7),int(w*.35):int(w*.65)], np.nan))
        pivot=np.array([0.,0.,center_depth])
        radius=None
        if mode=='top_down':
            # Orbiting around the torso at the original radius put the camera
            # almost against the head. Keep the source working distance above
            # the top of the performer instead of flying through their hair.
            head_y=points[:,int(h*.05):int(h*.3),int(w*.3):int(w*.7),1]
            radius=float(np.linalg.norm(pivot))+max(0.,-float(np.nanquantile(head_y,.05)))
        valid=z[np.isfinite(z)&(z>.01)]
        if mode=='top_down':
            c,r=camera_matrix(pivot,0,degrees,radius=radius)
            target_z=(points[...,0]-c[0])*r[2,0]+(points[...,1]-c[1])*r[2,1]+(points[...,2]-c[2])*r[2,2]
            valid=target_z[np.isfinite(target_z)&(target_z>.01)]
        lo,hi=np.quantile(1/valid,[.001,.999])
        depths=[];previews=[];holes=[]
        if first_frame_only and mode!='top_down':raise ValueError('Single-frame guide is only valid for the fixed top-down keyframe stage')
        rendered_count=1 if first_frame_only else n
        for i in range(rendered_count):
            fraction=camera_progress(i/max(n-1,1),speed,easing)
            yaw=degrees*fraction if mode=='orbit_left' else -degrees*fraction if mode=='orbit_right' else 0
            elevation=degrees if mode=='top_down' else 0
            center,rotation=camera_matrix(pivot,yaw,elevation,radius=radius)
            if mode in ('pan_left','pan_right','tilt_up','tilt_down'):
                center=np.zeros(3)
                rotation=optical_rotation(mode,degrees,fraction)
            if projection=='mesh':d,p,m=mesh_project(points[i],colors[i],intrinsics[i],center,rotation,width,height,lo,hi,make_preview=not depth_only,floor_y=floor_y)
            else:d,p,m=splat(points[i],colors[i],intrinsics[i],center,rotation,width,height,lo,hi)
            depths.append(np.repeat(d[...,None],3,axis=-1));previews.append(p);holes.append(m.astype(np.float32))
        print(f'[Flagship Geometry] {mode}: {rendered_count} guide frames from {n} source frames, requested {degrees:.1f} degrees; unseen pixels {np.mean(holes):.1%}')
        depth=np.stack(depths);preview=np.stack(previews);missing=np.stack(holes)
        np.savez(cache,depth=np.uint16(depth[...,0]*65535),rgb=np.uint8(preview*255),holes=np.uint8(missing))
        return torch.from_numpy(depth),torch.from_numpy(preview),torch.from_numpy(missing)


class FlagshipDepthRackFocus:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"images":("IMAGE",),"geometry_file":("STRING",{"default":"camera_source.npz"}),
            "blur_pixels":("FLOAT",{"default":14.,"min":0.,"max":40.})},
            "optional":{"face_transform":("H3FACEXFORM",),
                        "direction":(["near to far","far to near"],{"default":"near to far"})}}
    RETURN_TYPES=("IMAGE",)
    FUNCTION='apply'
    CATEGORY='Flagship/Camera'

    def apply(self,images,geometry_file,blur_pixels,face_transform=None,direction='near to far'):
        if direction not in ('near to far','far to near'):
            raise ValueError('Unknown rack-focus direction')
        import comfy.model_management
        import torch.nn.functional as F
        with np.load(Path(folder_paths.get_output_directory())/'CameraGeometry'/Path(geometry_file).name,allow_pickle=False) as data:
            z=data['depth'].copy()
        if len(z)!=len(images):raise ValueError('Depth/video frame count mismatch: never retime lips to match geometry')
        disparity=1/np.maximum(z,.01)
        valid=disparity[np.isfinite(disparity)]
        far=float(np.quantile(valid,.1))
        h,w=disparity.shape[1:]
        # This diagnostic source has a centered face near the upper fifth of the frame.
        # Do not focus on the closer door jamb instead of the performer.
        face_depth=disparity[:,int(h*.08):int(h*.28),int(w*.38):int(w*.65)]
        near=float(np.median(face_depth[np.isfinite(face_depth)]))
        if face_transform is not None:
            face_values=[]
            cw,ch=face_transform['canvas'];sw,sh=face_transform['src_size']
            for i,(box,rect) in enumerate(zip(face_transform['boxes'],face_transform['face_rect'])):
                if not face_transform['detected'][i]:continue
                bx,by,bw,bh=box;rx,ry,rw,rh=rect
                x0=int((bx+(rx+rw*.2)/cw*bw)/sw*w);x1=int((bx+(rx+rw*.8)/cw*bw)/sw*w)
                y0=int((by+(ry+rh*.2)/ch*bh)/sh*h);y1=int((by+(ry+rh*.8)/ch*bh)/sh*h)
                values=disparity[i,max(0,y0):min(h,y1),max(0,x0):min(w,x1)]
                if values.size:face_values.append(values[np.isfinite(values)])
            if not face_values:raise ValueError('No visible tracked face to select the near focus plane')
            near=float(np.median(np.concatenate(face_values)))
        if near<=far:raise ValueError('This source lacks separated face/background depth planes')
        device=comfy.model_management.get_torch_device()
        # Fixed trajectory/normalization across the clip avoids focus flicker from per-frame quantiles.
        results=[]
        levels=[0.,blur_pixels*.25,blur_pixels*.5,blur_pixels]
        for i in range(len(images)):
            x=images[i:i+1,...,:3].movedim(-1,1).to(device)
            d=torch.from_numpy(disparity[i:i+1,None]).to(device)
            d=F.interpolate(d,size=x.shape[-2:],mode='bilinear',align_corners=False)
            t=np.clip((i/max(len(images)-1,1)-.1)/.8,0,1);t=t*t*(3-2*t)
            if direction=='far to near':t=1-t
            focus=near*(1-t)+far*t
            coc=((d-focus).abs()/max(near-far,1e-5)).clamp(0,1)*3
            output=torch.zeros_like(x)
            for level,sigma in enumerate(levels):
                if sigma<.01:b=x
                else:
                    radius=int(np.ceil(sigma*2));v=torch.arange(-radius,radius+1,device=device,dtype=x.dtype)
                    k=torch.exp(-.5*(v/sigma)**2);k=k/k.sum()
                    b=F.conv2d(F.pad(x,(radius,radius,0,0),mode='replicate'),k.view(1,1,1,-1).expand(3,1,1,-1),groups=3)
                    b=F.conv2d(F.pad(b,(0,0,radius,radius),mode='replicate'),k.view(1,1,-1,1).expand(3,1,-1,1),groups=3)
                output+=b*(1-(coc-level).abs()).clamp(0,1)
            results.append(output.movedim(1,-1).cpu())
        return (torch.cat(results),)


class FlagshipPrepareCameraGeometry:
    @classmethod
    def INPUT_TYPES(cls):
        segmenters=['None']+[n for n in folder_paths.get_filename_list('flagship_segmenters') if n.endswith('.pt')]
        return {"required":{"geometry":("MOGE_GEOMETRY",),"name":("STRING",{"default":"camera_live"}),
                            "stabilize_static_border":("BOOLEAN",{"default":False})},
                "optional":{"foreground_only":("BOOLEAN",{"default":False}),"segmenter":(segmenters,{"default":"None"})}}
    RETURN_TYPES=("STRING",)
    FUNCTION='prepare'
    CATEGORY='Flagship/Camera'

    def prepare(self,geometry,name,stabilize_static_border,foreground_only=False,segmenter='None'):
        if not stabilize_static_border and not foreground_only:return FlagshipSaveGeometry().save(geometry,name)['result']
        arrays={k:v.detach().float().cpu().numpy().copy() for k,v in geometry.items() if isinstance(v,torch.Tensor)}
        images=arrays['image'];z=arrays['depth'];n,h,w=z.shape
        if stabilize_static_border:
            static=images.std(axis=0).max(-1)<.025
            border=np.zeros((h,w),bool);border[:,:int(w*.18)]=True;border[:,int(w*.88):]=True
            mask=static&border
            if mask.sum()/max(border.sum(),1)<.8:
                raise ValueError('Depth-guided camera correction currently requires a locked source camera with static side backgrounds. Disable SDK camera corrections to use prompt direction only.')
            baseline=np.median(z,axis=0)
            for i in range(n):z[i]*=np.median(baseline[mask]/np.maximum(z[i][mask],.01))
            columns=np.median(z,axis=(0,1))
            for i in range(n):z[i][mask]=np.broadcast_to(columns,(h,w))[mask]
        K=np.median(arrays['intrinsics'],axis=0)
        u,v=np.meshgrid((np.arange(w)+.5)/w,(np.arange(h)+.5)/h)
        arrays['points']=np.stack([(u-K[0,2])/K[0,0]*z,(v-K[1,2])/K[1,1]*z,z],-1).astype(np.float32)
        arrays['intrinsics']=np.repeat(K[None],n,axis=0);arrays['depth']=z
        if foreground_only:
            if segmenter=='None':raise ValueError('A local person segmenter is required for the overhead correction')
            from ultralytics import YOLO
            from scipy.ndimage import binary_fill_holes
            import comfy.model_management
            model=YOLO(folder_paths.get_full_path_or_raise('flagship_segmenters',segmenter))
            device=comfy.model_management.get_torch_device()
            masks=[]
            for i,frame in enumerate(images):
                result=model.predict(np.uint8(frame[...,::-1]*255),device=str(device),imgsz=640,conf=.25,retina_masks=True,verbose=False)[0]
                if result.masks is None:raise ValueError(f'No person segmentation in source frame {i}; overhead correction stopped')
                labels=result.boxes.cls.cpu().numpy().astype(int)
                people=np.flatnonzero(labels==0)
                if not len(people):raise ValueError('The current overhead correction is verified for person footage only')
                boxes=result.boxes.xyxy.cpu().numpy()
                j=max(people,key=lambda j:(boxes[j,2]-boxes[j,0])*(boxes[j,3]-boxes[j,1]))
                selected=[j]+[int(k) for k in np.flatnonzero(labels==67) if boxes[j,0]<=((boxes[k,0]+boxes[k,2])/2)<=boxes[j,2] and boxes[j,1]<=((boxes[k,1]+boxes[k,3])/2)<=boxes[j,3]]
                matte=result.masks.data[selected].amax(0).cpu().numpy()>.5
                matte=cv2.resize(matte.astype(np.uint8),(w,h),interpolation=cv2.INTER_NEAREST)
                matte=cv2.dilate(np.uint8(binary_fill_holes(matte)),np.ones((5,5),np.uint8)).astype(bool)
                masks.append(matte)
            model.to('cpu')
            subject=np.stack(masks)
            floor=float(np.quantile(arrays['points'][subject][:,1],.999))+.02*float(np.median(z[subject]))
            arrays['points'][~subject]=np.nan;arrays['depth'][~subject]=np.nan
            arrays['subject_mask']=subject;arrays['scene_floor_y']=np.array([floor],np.float32)
        return FlagshipSaveGeometry().save({k:torch.from_numpy(v) for k,v in arrays.items()},name)['result']


class FlagshipCameraSourceWarp:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"source_images":("IMAGE",),"generated_images":("IMAGE",),
            "geometry_file":("STRING",),"mode":(["pan_left","pan_right","tilt_up","tilt_down"],),
            "degrees":("FLOAT",{"default":7.,"min":0.,"max":90.})},
            "optional":{"speed":(["very slow","slow","moderate","fast","very fast"],{"default":"slow"}),
                "easing":(["linear","ease in","ease out","ease in out","snap settle"],{"default":"linear"}),
                "feather_pixels":("INT",{"default":4,"min":0,"max":64})}}
    RETURN_TYPES=("IMAGE",)
    FUNCTION='warp'
    CATEGORY='Flagship/Camera'

    def warp(self,source_images,generated_images,geometry_file,mode,degrees,speed='slow',easing='linear',feather_pixels=4):
        from comfy.model_management import get_torch_device
        n=len(source_images)
        if n!=len(generated_images):
            raise ValueError('Camera source projection requires matching frame counts; never retime source speech.')
        path=Path(folder_paths.get_output_directory())/'CameraGeometry'/Path(geometry_file).name
        with np.load(path,allow_pickle=False) as data:intrinsics=data['intrinsics'].copy()
        if intrinsics.ndim==2:intrinsics=intrinsics[None]
        if len(intrinsics) not in (1,n) or not np.isfinite(intrinsics).all():
            raise ValueError('Source projection received incompatible camera intrinsics.')
        sh,sw=source_images.shape[1:3];h,w=generated_images.shape[1:3]
        device=get_torch_device()
        yy,xx=torch.meshgrid(torch.arange(h,device=device,dtype=torch.float32),torch.arange(w,device=device,dtype=torch.float32),indexing='ij')
        opaque=torch.ones((1,1,sh,sw),device=device,dtype=torch.float32)
        output=[]
        for i in range(n):
            k=intrinsics[0 if len(intrinsics)==1 else i].astype(np.float64)
            ks=k.copy();ks[0,:]*=sw;ks[1,:]*=sh;ks[0,2]-=.5;ks[1,2]-=.5
            kt=k.copy();kt[0,:]*=w;kt[1,:]*=h;kt[0,2]-=.5;kt[1,2]-=.5
            rotation=optical_rotation(mode,degrees,camera_progress(i/max(n-1,1),speed,easing))
            inverse=torch.as_tensor(np.linalg.inv(kt@rotation@np.linalg.inv(ks)),device=device,dtype=torch.float32)
            z=inverse[2,0]*xx+inverse[2,1]*yy+inverse[2,2]
            denominator=torch.where(z.abs()>1e-8,z,torch.full_like(z,1e-8))
            gx=(inverse[0,0]*xx+inverse[0,1]*yy+inverse[0,2])/denominator
            gy=(inverse[1,0]*xx+inverse[1,1]*yy+inverse[1,2])/denominator
            grid=torch.stack(((gx+.5)/sw*2-1,(gy+.5)/sh*2-1),dim=-1)[None]
            source=source_images[i:i+1,...,:3].movedim(-1,1).to(device=device,dtype=torch.float32)
            projected=F.grid_sample(torch.cat((source,opaque),dim=1),grid,mode='bilinear',padding_mode='zeros',align_corners=False)
            valid=((projected[:,3:4]>=.9999)&(z[None,None]>0)).float()
            if feather_pixels:
                r=int(feather_pixels)
                alpha=F.avg_pool2d(valid,2*r+1,stride=1,padding=r,count_include_pad=False)*valid
            else:alpha=valid
            generated=generated_images[i:i+1,...,:3].movedim(-1,1).to(device=device,dtype=torch.float32)
            result=projected[:,:3]*alpha+generated*(1-alpha)
            output.append(result.clamp(0,1).movedim(1,-1).cpu())
        print(f'[Flagship Camera] original pixels preserved through {mode}: {n} frames; unseen borders use generation')
        return (torch.cat(output),)


class FlagshipMultiAngleGuide:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geometry_file": ("STRING",),
            "path_json": ("STRING", {"multiline": True, "forceInput": False}),
            "width": ("INT", {"default": 384, "min": 64, "max": 2048}),
            "height": ("INT", {"default": 688, "min": 64, "max": 2048})},
            "optional": {"depth_only": ("BOOLEAN", {"default": True})}}
    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("depth_guide", "reprojection_preview", "unseen_mask", "camera_values")
    FUNCTION = "render"
    CATEGORY = "Flagship/Camera"

    def render(self, geometry_file, path_json, width, height, depth_only=True):
        directory = (Path(folder_paths.get_output_directory())/'CameraGeometry').resolve()
        path = (directory/Path(geometry_file).name).resolve()
        if not path.is_relative_to(directory):
            raise ValueError('Geometry must be inside CameraGeometry')
        spec = parse_path(path_json)
        with np.load(path, allow_pickle=False) as data:
            points, colors, intrinsics = data['points'], data['image'], data['intrinsics']
            floor_y = float(data['scene_floor_y'].ravel()[0]) if 'scene_floor_y' in data else None
        n, h, w, _ = points.shape
        z = points[..., 2]
        roi = z[:, int(h*.25):int(h*.7), int(w*.35):int(w*.65)]
        valid = z[np.isfinite(z) & (z > .01)]
        if not len(valid):
            raise ValueError('No visible positive scene depth')
        pivot_z = np.nanmedian(np.where(np.isfinite(roi) & (roi > .01), roi, np.nan))
        if not np.isfinite(pivot_z):
            pivot_z = np.median(valid)
        pivot = np.array([0., 0., pivot_z])
        lo, hi = np.quantile(1/valid, [.001, .999])
        hi = max(hi, lo+1e-6)
        values = sample_path(spec, np.linspace(0, 1, n)) if spec['enabled'] else np.tile([0., 0., 5.], (n, 1))
        depth, previews, masks, report = [], [], [], []
        for i, (azimuth, elevation, zoom) in enumerate(values):
            radius = pivot_z*(radius_scale(zoom) if spec['zoom_mode'] == 'dolly' else 1)
            # Easy positive azimuth is screen-right; the older renderer uses left-positive yaw.
            center, rotation = camera_matrix(pivot, -azimuth, elevation, radius=radius)
            k = intrinsics[0 if len(intrinsics) == 1 else i].copy()
            if spec['zoom_mode'] == 'optical':
                k[0, 0] /= radius_scale(zoom)
                k[1, 1] /= radius_scale(zoom)
            d, rgb, missing = mesh_project(points[i], colors[i], k, center, rotation,
                width, height, lo, hi, make_preview=not depth_only, floor_y=floor_y)
            depth.append(np.repeat(d[..., None], 3, axis=-1))
            previews.append(rgb)
            masks.append(missing.astype(np.float32))
            report.append({'frame': i, 'rotate': float(azimuth), 'vertical': float(elevation),
                'zoom': float(zoom), 'camera_center': center.tolist(),
                'focal_multiplier': float(1/radius_scale(zoom) if spec['zoom_mode'] == 'optical' else 1),
                'unseen_fraction': float(np.mean(missing))})
        print(f'[Flagship MultiAngle] {n} frames, {len(spec["keyframes"])} angles; unseen {np.mean(masks):.1%}')
        return (torch.from_numpy(np.stack(depth)), torch.from_numpy(np.stack(previews)),
                torch.from_numpy(np.stack(masks)), json.dumps(report))


NODE_CLASS_MAPPINGS = {"FlagshipCameraVisibleTargets": FlagshipCameraVisibleTargets, "FlagshipCameraTargetFraming": FlagshipCameraTargetFraming,
                       "FlagshipCrossViewGuide": FlagshipCrossViewGuide,
                       "FlagshipCameraOrbitEligibility": FlagshipCameraOrbitEligibility,
                       "FlagshipCameraMotionEligibility": FlagshipCameraMotionEligibility, "FlagshipCameraWideComposite": FlagshipCameraWideComposite,
                       "FlagshipCameraMotionViews": FlagshipCameraMotionViews,
                       "FlagshipCameraProtectProps": FlagshipCameraProtectProps,
                       "FlagshipCameraDollyLayers": FlagshipCameraDollyLayers, "FlagshipCameraLayeredDolly": FlagshipCameraLayeredDolly,
                       "FlagshipCameraLipRepairGuard": FlagshipCameraLipRepairGuard, "FlagshipCameraLipRepairSwitch": FlagshipCameraLipRepairSwitch,
                       "FlagshipMultiAngle": FlagshipMultiAngle, "FlagshipMultiAngleGuide": FlagshipMultiAngleGuide,"FlagshipMultiAngleSourceZoom": FlagshipMultiAngleSourceZoom,"FlagshipSaveGeometry": FlagshipSaveGeometry,"FlagshipGeometryCamera": FlagshipGeometryCamera,
                       "FlagshipDepthRackFocus":FlagshipDepthRackFocus,"FlagshipPrepareCameraGeometry":FlagshipPrepareCameraGeometry,
                       "FlagshipCameraSourceWarp":FlagshipCameraSourceWarp,
                       "FlagshipCameraSourceFraming":FlagshipCameraSourceFraming}
