"""Small ROI color/geometry evidence; never OCR or character recognition."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Observation:
    readable: bool = False
    progress: float | None = None
    ready: bool = False
    consumed: bool = False
    dead: bool = False
    empty: bool = False
    confidence: float = 0.
    partial: bool = False
    reason: str = ''


def observe(energy,hp,portrait):
    if min(energy.size,hp.size,portrait.size)==0 or energy.shape[1]<12:
        return Observation()
    values=energy.astype(np.int16)
    maximum=values.max(axis=2);minimum=values.min(axis=2)
    # White or bright colored fill; a dimmed full bar alone cannot prove consumption.
    bright=(minimum>145) | ((maximum>205)&(minimum>80)) | ((values.mean(axis=2)>165)&(maximum>220))
    columns=np.mean(bright,axis=0)>.45
    # Bridge one-pixel compression/noise gaps, without treating isolated highlights as fill.
    for i in range(1,len(columns)-1):
        if columns[i-1] and columns[i+1]: columns[i]=True
    # The one-pixel outline/rounded cap is not part of the fill. Requiring
    # column zero to be bright made otherwise full bars stay at zero forever.
    edge=max(1,int(np.ceil(len(columns)*.03)))
    first=np.flatnonzero(columns)
    start=int(first[0]) if len(first) and first[0]<=edge else 0
    leading=start
    for value in columns[start:]:
        if not value: break
        leading+=1
    progress=1. if leading>=len(columns)-edge else leading/len(columns)
    h=hp.astype(np.int16)
    chroma=h.max(axis=2)-h.min(axis=2)
    # HP fill has a horizontal cyan/red strip. Arbitrary colored scenery and
    # a uniform grey background cannot establish a HUD by themselves.
    colored=(chroma>45)&(h.max(axis=2)>95)&(h.min(axis=2)<155)
    hp_fraction=float(np.mean(np.any(colored,axis=0)))
    # A visible horizontal neutral rail is required even when the bar is empty.
    rail=np.mean((maximum>30)&(maximum<170))
    hp_rows=np.mean(colored,axis=1)
    neutral=float(np.mean((maximum-minimum<80)|(minimum>145)))
    # Low HP and HUD tint vary by slot. Neutral color isn't required: a red
    # cooldown rail remains valid when the adjacent HP strip is visible.
    horizontal=float(np.mean(np.std(values,axis=0)<38))
    hp_evidence=bool(hp_fraction>.012 and np.max(hp_rows)>.01 and horizontal>.7
                     and (neutral>.7 or np.mean(bright)>.1))
    p=portrait.astype(np.int16)
    white=(p.min(axis=2)>170)&((p.max(axis=2)-p.min(axis=2))<60)
    yy,xx=np.indices(white.shape)
    nx=xx/max(1,white.shape[1]-1);ny=yy/max(1,white.shape[0]-1)
    diagonal=(abs(nx-ny)<.075)|(abs(nx+ny-1)<.075)
    death_shape=float(white[diagonal].mean())>.55 and float(white[~diagonal].mean())<.28
    readable=bool(hp_evidence or (death_shape and rail>.65))
    dead=bool(readable and hp_fraction<.015 and death_shape)
    # This is only an empty-slot candidate. The engine must first establish
    # the layout from other slots with actual HP/death evidence.
    empty=bool(rail>.85 and hp_fraction==0 and p.max()<22)
    confidence=min(1.,hp_fraction*2+.35*float(rail>.5)) if readable else 0.
    # A bright prefix followed by a darker suffix is positive cooldown
    # evidence even if capture missed the completely empty frame. Uniform
    # dimming has no such edge and must never consume a latched ready state.
    level=values.mean(axis=(0,2))
    partial=bool(readable and edge+2<leading<len(columns)-edge
                 and level[start:leading].mean()-level[leading+1:].mean()>45
                 and np.mean(~columns[leading:])>.8)
    ready=bool(readable and progress>=.965 and int(columns.sum())>=len(columns)-2*edge)
    consumed=bool(readable and progress<.08 and columns.mean()<.08 and rail>.65 and maximum.mean()<100)
    # Finding the HUD/HP strip isn't the same as recognizing CD state.
    # Uniform dimming or a middle highlight supplies no reliable fill value.
    recognized=bool(readable and (ready or consumed or partial or dead))
    return Observation(recognized,progress if recognized else None,ready,consumed,
        dead,empty,confidence if recognized else 0.,partial,
        'hp_strip' if recognized and hp_evidence else 'death_mark' if recognized else
        'ambiguous_energy' if readable else 'missing_hp_or_rail')
