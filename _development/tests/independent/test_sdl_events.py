"""Native SDL event memory layouts, including unmapped axes and simultaneous reports."""
import ctypes
import struct
from endfield_pcap.inputlog.backends.sdl import SDLInput


def test_sdl_batch_preserves_raw_mapped_axes_touch_and_sensor_controls():
    events=[]
    def frame(typ,body):
        return struct.pack('<IIQI',typ,0,1000000000,17)+body+b'\0'*(108-len(body))
    frames=[frame(0x600,struct.pack('<B3xh',0,-12345)),
            frame(0x650,struct.pack('<B3xh',0,-12345)),
            frame(0x651,bytes([9,1])),frame(0x652,bytes([9,0])),
            frame(0x602,bytes([0,3])),
            frame(0x657,struct.pack('<iifff',0,2,.3,.4,.8)),
            frame(0x659,struct.pack('<ifff4xQ',2,1.,2.,3.,123456))]
    class Library:
        def SDL_PollEvent(self,buffer):
            if not frames:return False
            ctypes.memmove(buffer,frames.pop(0),128)
            return True
    adapter=SDLInput.__new__(SDLInput)
    adapter.lib=Library();adapter.buffer=ctypes.create_string_buffer(128)
    adapter.gamepads={17:object()};adapter.emit=lambda record_type,**fields:events.append(fields)
    adapter.pump()
    assert len(events)==7 and not frames
    assert events[0]['value']==events[1]['value']==-12345
    assert events[0]['code']=='J:AXIS0' and events[1]['code']=='P:AXIS0'
    assert events[0]['association']==events[1]['association']
    assert [r['phase'] for r in events[2:4]]==['down','up']
    assert events[4]['value']==3
    assert events[5]['code']=='P:TOUCH0:2' and len(events[5]['value'])==3
    assert events[6]['value']==[1.,2.,3.] and events[6]['sensor_time_ns']==123456
