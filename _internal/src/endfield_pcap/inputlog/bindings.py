"""Portable per-battle input source and independent display preferences."""
from __future__ import annotations
import math
import json
import os
from pathlib import Path


def read_binding(value, trace):
    value = value if isinstance(value, dict) else {}
    source = value.get('path')
    path = (Path(trace).parent/str(source)).resolve() if isinstance(source,str) and source else None
    sources = value.get('paths')
    paths = ([(Path(trace).parent / item).resolve() for item in sources if isinstance(item, str) and item]
             if isinstance(sources, list) else [path] if path else [])
    paths = list(dict.fromkeys(paths))
    def finite(key, default):
        number=value.get(key,default)
        return float(number) if type(number) in (int,float) and math.isfinite(number) else default
    slots=value.get('manual_slots',{})
    slots={int(k):v for k,v in slots.items() if str(k) in ('0','1','2','3') and isinstance(v,str)} if isinstance(slots,dict) else {}
    return dict(path=path, paths=paths, visible=value.get('visible') is True, offset_ms=finite('offset_ms',0.),
                start_override=finite('start_override',None), manual_slots=slots,
                manual=value.get('manual') is True)


def write_binding(trace, path, *, paths=None, visible=False, offset_ms=0., start_override=None, manual_slots=None, manual=False):
    def relative(item):
        if not item: return None
        try: return os.path.relpath(Path(item).resolve(),Path(trace).resolve().parent)
        except ValueError: return str(Path(item).resolve())  # Another Windows drive.
    result=dict(path=relative(path),visible=bool(visible),offset_ms=offset_ms,start_override=start_override,
                manual_slots={str(k):v for k,v in (manual_slots or {}).items()},manual=bool(manual))
    if paths and len(paths)>1:
        result['paths']=[relative(item) for item in paths]
    return result


def relocate_bindings(bindings, old, new):
    from endfield_pcap.history.files import relocate_key
    from endfield_pcap.inputlog.storage import companion
    result={}
    old_input, new_input=companion(old), companion(new)
    for key,value in bindings.items():
        moved=relocate_key(key,old,new)
        try: base=Path(json.loads(key)[0])
        except (ValueError,TypeError,IndexError): base=old
        current=read_binding(value,base)
        original_paths=current['paths']
        def relocate(path):
            if path:
                prefix=old_input.name.removesuffix('.input.jsonl')
                if path==old_input.resolve(): path=new_input
                elif path.parent==old_input.resolve().parent and path.name.startswith(prefix+'.part-'):
                    path=new_input.with_name(new_input.name.removesuffix('.input.jsonl')+path.name[len(prefix):])
            return path
        paths=[relocate(path) for path in current.pop('paths')]
        path=relocate(current.pop('path'))
        if moved!=key or paths!=original_paths:
            # Other battles in this continuous recording can select the renamed sidecar too.
            value=write_binding(new if moved!=key else base,path,paths=paths,**current)
        result[moved]=value
    return result
