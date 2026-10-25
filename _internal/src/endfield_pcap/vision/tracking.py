"""Recognized frames replace CD state; unreadable frames retain its estimate."""
from __future__ import annotations
from collections import deque
import statistics
from endfield_pcap.vision.pixels import Observation


class SlotTracker:
    def __init__(self):
        self.state='unknown'
        self.progress=None
        self.remaining=None
        self.last_frame=None
        self.last_valid=None
        self.samples=deque(maxlen=128)
        self.last_movement=None
        self.estimate_at=None
        self.estimate_progress=None
        self.held=False

    def invalid(self,now):
        self.samples.clear()
        self.held=self.last_valid is not None

    def feed(self,observation,now,frame_id):
        if frame_id==self.last_frame:
            if self.last_valid is None or now-self.last_valid>1: self.invalid(now)
            return self.payload(now)
        self.last_frame=frame_id
        if not observation.readable or (observation.progress is None and not observation.empty and not observation.dead):
            self.invalid(now)
            return self.payload(now)
        self.last_valid=now
        self.held=False
        desired=('empty' if observation.empty else 'dead' if observation.dead else 'ready' if observation.ready
                 else 'cooldown')
        if desired!=self.state:
            self.samples.clear()
        self.state=desired
        value=observation.progress
        old=self.progress
        if value is not None and (old is None or abs(value-old)>.001): self.last_movement=now
        self.progress=value
        self.remaining=None
        self.estimate_at=None
        self.estimate_progress=None
        if self.state!='cooldown' or value is None:
            self.samples.clear()
        else:
            # Pauses, jumps and reverse motion invalidate velocity immediately.
            if old is not None and (value<old-.015 or value-old>.2):
                self.samples.clear()
            self.samples.append((now,value))
            while self.samples and now-self.samples[0][0]>3:
                self.samples.popleft()
            if self.last_movement is not None and now-self.last_movement>.2:
                self.samples.clear()
            if self.samples and now-self.samples[0][0]>=.75:
                recent=[p for p in self.samples if now-p[0]<=.75]
                if len(recent)>1 and value-recent[0][1]>.003:
                    slopes=[(b[1]-a[1])/(b[0]-a[0]) for a,b in zip(self.samples,list(self.samples)[1:]) if b[0]>a[0] and b[1]>a[1]]
                    if slopes:
                        speed=statistics.median(slopes)
                        spread=statistics.median(abs(s-speed) for s in slopes)
                        if speed>.001 and spread<max(.002,speed*.3):
                            self.remaining=max(0,(1-value)/speed*1000)
                            self.estimate_at=now
                            self.estimate_progress=value
        return self.payload(now)

    def payload(self,now):
        stale=self.last_valid is None or now-self.last_valid>1
        progress=self.progress
        remaining=self.remaining
        if self.held and self.state=='cooldown' and remaining is not None and self.estimate_at is not None:
            elapsed=max(0,now-self.estimate_at)*1000
            if elapsed>=remaining:
                self.state='ready'
                self.progress=progress=1.
                self.remaining=remaining=0.
                self.estimate_at=None
            else:
                progress=self.estimate_progress+(1-self.estimate_progress)*elapsed/remaining
                remaining-=elapsed
        if self.state=='ready':
            progress=1.
            remaining=0.
        return dict(status=self.state,progress=progress,estimated_remaining_ms=remaining,
                    stale=stale,held=self.held)
