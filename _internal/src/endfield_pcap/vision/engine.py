"""Shared four-slot visual projection from a mapped frame."""
from __future__ import annotations
import time
from dataclasses import replace
from endfield_pcap.vision.layout import fitted_presets,normalize_config,game_area,crop
from endfield_pcap.vision.pixels import observe
from endfield_pcap.vision.tracking import SlotTracker


class VisionEngine:
    def __init__(self,config=None):
        self.config=normalize_config(config)
        self.trackers=[SlotTracker() for _ in range(4)]
        self.layout=None
        self.pending=None
        self.confirmations=0
        self.geometry=None
        self.region_identity=None
        self.diagnostics={}

    def analyze(self,pixels,client,now,frame_id):
        area=game_area(pixels,client)
        geometry=(pixels.shape[:2],tuple(area))
        available=fitted_presets(area)
        if self.config['regions']:
            available.append(('custom','custom',self.config['regions']))
        mode=self.config['layout']
        candidates=available if mode=='auto' else [row for row in available if row[0]==mode]
        scored=[]
        for name,identity,regions in candidates:
            if len(regions)!=4: continue
            observations=[observe(*(crop(pixels,area,row[key]) for key in ('energy','hp','portrait'))) for row in regions]
            readable=sum(o.readable for o in observations)
            score=sum(o.confidence for o in observations)+readable
            scored.append((score,readable,name,identity,regions,observations))
        scored.sort(key=lambda item:item[0],reverse=True)
        self.diagnostics={'candidates':len(scored)}
        if scored:
            score,readable,name,identity,regions,observations=scored[0]
            self.diagnostics.update(candidate=identity,score=round(score,3),readable_slots=readable,
                observations=[dict(slot=i,readable=o.readable,progress=round(o.progress,3) if o.progress is not None else None,
                    ready=o.ready,consumed=o.consumed,partial=o.partial,reason=o.reason) for i,o in enumerate(observations)])
        # Nearby variants of the same layout may observe the same bars. They
        # aren't evidence of an ambiguous keyboard/controller layout.
        other=next((row for row in scored[1:] if row[2]!=scored[0][2]),None) if scored else None
        # Two random scenery patches can resemble colored HP strips. A new
        # layout needs support from at least three slots (including empty-slot
        # geometry), with two actual readable bars. An already confirmed
        # layout can update one recognized slot while the others are obscured.
        same_region=bool(scored and scored[0][3]==self.region_identity and geometry==self.geometry)
        supported=sum(o.readable or o.empty for o in scored[0][5]) if scored else 0
        if (not scored or scored[0][1]<(1 if same_region else 2) or (supported<3 and not same_region)
                or (not same_region and mode=='auto' and other and scored[0][0]-other[0]<.1)):
            return self.invalid(now,'待校准：无法确认游戏 HUD 布局')
        _,_,name,identity,regions,observations=scored[0]
        candidate=(geometry,identity)
        if self.pending==candidate:
            self.confirmations+=1
        else:
            self.pending,self.confirmations=candidate,1
        if not same_region and self.confirmations<2:
            return self.invalid(now,'确认布局中',reset_layout=False)
        if identity!=self.region_identity or geometry!=self.geometry:
            self.trackers=[SlotTracker() for _ in range(4)]
            self.layout=name
            self.region_identity=identity
            self.geometry=geometry
        observations=[replace(o,readable=True) if o.empty and not o.readable else o for o in observations]
        slots=[dict(slot=i,**tracker.feed(observations[i],now,frame_id)) for i,tracker in enumerate(self.trackers)]
        return dict(frame_valid=True,status='识别中',layout=name,regions=regions,game_area=list(area),slots=slots,
                    diagnostics=self.diagnostics)

    def invalid(self,now,reason,reset_layout=True):
        if reset_layout:
            self.pending=None
            self.confirmations=0
        for tracker in self.trackers: tracker.invalid(now)
        return dict(frame_valid=False,status=reason,layout=self.layout,
                    slots=[dict(slot=i,**tracker.payload(now)) for i,tracker in enumerate(self.trackers)],
                    diagnostics=self.diagnostics)
