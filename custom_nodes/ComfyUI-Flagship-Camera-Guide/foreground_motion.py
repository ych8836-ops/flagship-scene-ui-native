"""Catch fast hair/head changes that a quiet-body pose check can miss."""
import numpy as np
import torch
import torch.nn.functional as F
import comfy.model_management as mm


def foreground_change(images,targets):
    device=mm.get_torch_device();mm.free_memory(256*1024**2,device)
    n,h,w,_=images.shape;factor=224/max(h,w);gh,gw=max(2,round(h*factor)),max(2,round(w*factor))
    boxes=np.asarray(targets['person_boxes'],float);boxes=boxes[np.isfinite(boxes).all(1)]
    if not len(boxes):raise ValueError('Foreground motion needs measured source body bounds')
    left,top=np.quantile(boxes[:,:2],.02,axis=0);right,bottom=np.quantile(boxes[:,2:],.98,axis=0)
    x0,x1=max(0,int(left*gw/w)),min(gw,int(np.ceil(right*gw/w)))
    y0,y1=max(0,int(top*gh/h)),min(gh,int(np.ceil(bottom*gh/h)))
    if x1<=x0 or y1<=y0:raise ValueError('Foreground motion bounds are empty')
    parts=[]
    for start in range(0,n,8):
        mm.throw_exception_if_processing_interrupted()
        rgb=images[start:start+8,...,:3].movedim(-1,1).to(device=device,dtype=torch.float32)
        parts.append(F.interpolate(rgb,(gh,gw),mode='area')[:,:,y0:y1,x0:x1])
    video=torch.cat(parts);delta=(video[1:]-video[:-1]).abs().mean(1).flatten(1)
    return float(torch.quantile(torch.quantile(delta,.95,dim=1),.9))
