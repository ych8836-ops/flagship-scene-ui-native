"""Continuous surface rasterization. Single-view holes remain explicitly unknown."""
import numpy as np
from numba import njit


@njit(cache=False)
def raster_mesh(points, colors, K, center, rotation, width, height, stride=2):
    points=points.astype(np.float32);colors=colors.astype(np.float32)
    center=center.astype(np.float32);rotation=rotation.astype(np.float32);K=K.astype(np.float32)
    h,w,_=points.shape
    zbuffer=np.full((height,width),np.inf,np.float32)
    rgb=np.zeros((height,width,3),np.float32)
    # Include the last row/column: otherwise the mesh leaves a source-edge strip.
    ys=np.unique(np.append(np.arange(0,h,stride),h-1))
    xs=np.unique(np.append(np.arange(0,w,stride),w-1))
    screen=np.zeros((h,w,3),np.float32)
    for iy in ys:
        for ix in xs:
            q=(points[iy,ix]-center)@rotation.T
            screen[iy,ix,0]=(q[0]/q[2]*K[0,0]+K[0,2])*width-.5
            screen[iy,ix,1]=(q[1]/q[2]*K[1,1]+K[1,2])*height-.5
            screen[iy,ix,2]=q[2]
    for yi in range(len(ys)-1):
        for xi in range(len(xs)-1):
            # Two consistently oriented triangles per source quad.
            for side in range(2):
                iy0,ix0=ys[yi],xs[xi]
                iy1,ix1=ys[yi+1],xs[xi+1] if side==0 else xs[xi]
                iy2,ix2=ys[yi] if side==0 else ys[yi+1],xs[xi+1]
                a=screen[iy0,ix0];b=screen[iy1,ix1];c=screen[iy2,ix2]
                za,zb,zc=a[2],b[2],c[2]
                # Do not stretch triangles across disocclusion boundaries.
                sza,szb,szc=points[iy0,ix0,2],points[iy1,ix1,2],points[iy2,ix2,2]
                if min(za,zb,zc)<=.01 or not np.isfinite(za+zb+zc):continue
                if max(sza,szb,szc)-min(sza,szb,szc)>.08*min(sza,szb,szc):continue
                den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
                if abs(den)<1e-8:continue
                x0=max(0,int(np.ceil(min(a[0],b[0],c[0])-1e-4)))
                x1=min(width-1,int(np.floor(max(a[0],b[0],c[0])+1e-4)))
                y0=max(0,int(np.ceil(min(a[1],b[1],c[1])-1e-4)))
                y1=min(height-1,int(np.floor(max(a[1],b[1],c[1])+1e-4)))
                for y in range(y0,y1+1):
                    for x in range(x0,x1+1):
                        aa=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den
                        bb=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den
                        cc=1-aa-bb
                        if min(aa,bb,cc)<-1e-5:continue
                        z=1/(aa/za+bb/zb+cc/zc)
                        if z>=zbuffer[y,x]:continue
                        zbuffer[y,x]=z
                        for ch in range(3):
                            rgb[y,x,ch]=(aa*colors[iy0,ix0,ch]/za+bb*colors[iy1,ix1,ch]/zb+cc*colors[iy2,ix2,ch]/zc)*z
    return zbuffer,rgb
