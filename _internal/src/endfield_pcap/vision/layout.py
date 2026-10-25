"""Normalized HUD regions. Reference measurements are data, not executable templates."""
from __future__ import annotations
import math
import numpy as np


def normalize_config(value):
    value = value if isinstance(value,dict) else {}
    mode = value.get('layout','auto')
    rows = value.get('regions',[])
    clean = []
    if isinstance(rows,list) and len(rows)==4:
        for row in rows:
            item = {}
            for key in ('energy','hp','portrait'):
                rect = row.get(key) if isinstance(row,dict) else None
                if isinstance(rect,list) and len(rect)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in rect):
                    x,y,w,h = rect
                    if 0<=x<1 and 0<=y<1 and w>0 and h>0 and x+w<=1 and y+h<=1:
                        item[key] = list(map(float,rect))
            clean.append(item)
    valid = len(clean)==4 and all(len(r)==3 for r in clean)
    try:
        target=max(0,int(value.get('target_hwnd',0) or 0))
    except (TypeError,ValueError,OverflowError):
        target=0
    return dict(layout=mode if mode in ('auto','keyboard','gamepad','gamepad_expanded','custom') else 'auto',
                regions=clean if valid else [],target_hwnd=target)


def presets():
    # All coordinates refer to the game image at 2048×1152, never desktop coordinates.
    keyboard = [(45,1053,89,4),(169,1053,90,4),(294,1053,89,4),(419,1053,89,4)]
    pad = [(117,1017,88,2),(203,923,89,2),(289,1017,89,2),(203,1103,89,2)]
    result = {}
    for name,positions in (('keyboard',keyboard),('gamepad',pad),('gamepad_expanded',pad)):
        rows=[]
        for i,(x,y,w,h) in enumerate(positions):
            if name=='gamepad_expanded':
                dx,dy=((-8.5,0),(0,-8.5),(8.5,0),(0,8.5))[i]
                x,y=x+dx,y+dy
            hp=(x,y+(4 if name=='keyboard' else 5),w,7)
            portrait=(x+w/2-13,y-56,26,26)
            rows.append({key:[r[0]/2048,r[1]/1152,r[2]/2048,r[3]/1152]
                         for key,r in (('energy',(x,y,w,h)),('hp',hp),('portrait',portrait))})
        result[name]=rows
    return result


def fitted_presets(area):
    """Keep HUD geometry uniform and anchored at the lower left on other aspect ratios.

    Canvas scaling varies with the game's display settings. Test the width/height
    scales and the old proportional layout against actual HUD evidence, rather
    than stretching every bar into whatever happens to be behind it.
    """
    _,_,width,height=area
    result=[]
    seen=set()
    for scale in (min(width/2048,height/1152),height/1152,width/2048):
        if round(scale,6) in seen: continue
        seen.add(round(scale,6))
        for name,rows in presets().items():
            fitted=[]
            for row in rows:
                fitted.append({key:[x*2048*scale/width,
                    1+(y*1152-1152)*scale/height,w*2048*scale/width,h*1152*scale/height]
                    for key,(x,y,w,h) in row.items()})
            result.append((name,f'{name}:{scale:.6f}',fitted))
    if abs(width/height-2048/1152)>.01:
        result.extend((name,name+':stretch',rows) for name,rows in presets().items())
    return result


def game_area(pixels,client):
    """Conservative symmetric black-band detection on sparse samples; no full-frame copy."""
    x,y,w,h=client
    sample=pixels[y:y+h:max(1,h//180),x:x+w:max(1,w//320),:3]
    if sample.size==0:
        return client
    rows=np.max(sample,axis=(1,2))>14
    cols=np.max(sample,axis=(0,2))>14
    ry=np.flatnonzero(rows);cx=np.flatnonzero(cols)
    if not len(ry) or not len(cx):
        return client
    top,bottom=ry[0]/len(rows),(len(rows)-1-ry[-1])/len(rows)
    left,right=cx[0]/len(cols),(len(cols)-1-cx[-1])/len(cols)
    # Only clear symmetric bars are cropped. Dark scenes are not a new viewport.
    if .015<top<.22 and abs(top-bottom)<.015:
        trim=round(min(top,bottom)*h); y+=trim; h-=2*trim
    if .015<left<.3 and abs(left-right)<.015:
        trim=round(min(left,right)*w); x+=trim; w-=2*trim
    return x,y,w,h


def crop(pixels,area,rect):
    x,y,w,h=area
    rx,ry,rw,rh=rect
    left,top=round(x+rx*w),round(y+ry*h)
    right,bottom=round(x+(rx+rw)*w),round(y+(ry+rh)*h)
    return pixels[max(0,top):min(len(pixels),max(top+1,bottom)),
                  max(0,left):min(pixels.shape[1],max(left+1,right)),:3].copy()
