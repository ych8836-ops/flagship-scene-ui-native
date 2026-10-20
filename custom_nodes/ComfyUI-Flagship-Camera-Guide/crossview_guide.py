"""Adapter for the pinned CrossView-Warp training-format conditioning."""
from pathlib import Path
import json
import cv2
import numpy as np
import torch
import folder_paths
import comfy.model_management as mm
from .vendor.crossview_warp_node import CrossViewWarp
from .camera_timing import camera_progress


class FlagshipCrossViewGuide:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'geometry_file':('STRING',),
            'width':('INT',{'default':448,'min':32,'max':4096,'step':32}),
            'height':('INT',{'default':800,'min':32,'max':4096,'step':32}),
            'start_azimuth':('FLOAT',{'default':0,'min':-180,'max':180}),
            'end_azimuth':('FLOAT',{'default':45,'min':-180,'max':180}),
            'start_elevation':('FLOAT',{'default':0,'min':-85,'max':85}),
            'end_elevation':('FLOAT',{'default':0,'min':-85,'max':85}),
            'start_distance':('FLOAT',{'default':1,'min':.1,'max':3}),
            'end_distance':('FLOAT',{'default':1,'min':.1,'max':3}),
            'speed':(['very slow','slow','moderate','fast','very fast'],),
            'easing':(['linear','ease in','ease out','ease in out','snap settle'],)}}
    RETURN_TYPES=('IMAGE',)
    FUNCTION='build'
    CATEGORY='Flagship/Camera'

    def build(self,images,geometry_file,width,height,start_azimuth,end_azimuth,start_elevation,end_elevation,
              start_distance,end_distance,speed,easing):
        directory=(Path(folder_paths.get_output_directory())/'CameraGeometry').resolve()
        path=(directory/Path(geometry_file).name).resolve()
        if path.parent!=directory or path.suffix!='.npz':raise ValueError('Camera geometry must be a local CameraGeometry .npz file')
        n=len(images)
        with np.load(path,allow_pickle=False) as data:
            if len(data['points'])!=n:raise ValueError('Camera geometry and source must have the same frame count')
            depths=torch.from_numpy(np.stack([cv2.resize(z,(width,height),interpolation=cv2.INTER_LINEAR) for z in data['points'][...,2]]))
            intrinsics=torch.from_numpy(data['intrinsics'].copy())
        rgb=images[...,:3].detach().float().cpu().numpy()
        frames=torch.from_numpy(np.stack([cv2.resize(im,(width,height),interpolation=cv2.INTER_AREA) for im in rgb]))
        start=np.array([start_azimuth,start_elevation,start_distance],float)
        end=np.array([end_azimuth,end_elevation,end_distance],float)
        moving=not np.array_equal(start,end)
        keys=[]
        if moving:
            for i in range(n):
                p=start+(end-start)*camera_progress(i/max(n-1,1),speed,easing)
                keys.append({'f':i+1,'az':float(p[0]),'el':float(p[1]),'dist':float(p[2])})
        mm.throw_exception_if_processing_interrupted()
        result=CrossViewWarp().build(frames,azimuth=start_azimuth,elevation=start_elevation,distance=start_distance,
            hfov=0,vertical_shift=0,depth_ratio=6,smooth_depth=False,invert_depth=False,roll_lock=True,
            pivot_override=False,keep_source_aim=True,use_keyframes=moving,frame_count=n,keyframes=json.dumps(keys),
            moge_geometry={'depth':depths,'intrinsics':intrinsics})[0]
        mm.throw_exception_if_processing_interrupted()
        return (result,)
