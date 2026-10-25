"""Native report transport, including nonzero 64-bit device and report handles."""
import ctypes as c
from ctypes import wintypes as w
import struct
from types import SimpleNamespace
from endfield_pcap.inputlog.backends.raw_input import RawInput,Header


def test_native_keyboard_handle_and_report_size_are_preserved():
    events=[]
    receiver=RawInput.__new__(RawInput)
    receiver.pressed=set();receiver.error=None
    receiver.received={'keyboard':0,'mouse':0,'hid':0}
    receiver.emit=lambda record_type,**fields:events.append((record_type,fields))
    receiver._device=lambda handle:f'device:{handle:x}'
    packet=bytes(Header(kind=1,size=c.sizeof(Header)+16,device=0x123456789,param=1))
    packet+=struct.pack('<HHHHII',2,0,0,49,0x100,0)
    handles=[]
    def read(handle,command,buffer,size,header_size):
        handles.append(handle.value)
        assert header_size==c.sizeof(Header)
        c.cast(size,c.POINTER(w.UINT))[0]=len(packet)
        if buffer is None:return 0
        c.memmove(buffer,packet,len(packet));return len(packet)
    receiver.user=SimpleNamespace(GetRawInputData=read,DefWindowProcW=lambda *a:0)
    receiver._message(1,0xff,1,0x987654321)
    assert receiver.error is None
    assert handles==[0x987654321]*2
    assert receiver.received['keyboard']==1
    assert events[0][1]['device']=='device:123456789'
    assert events[0][1]['phase']=='down'


def test_failed_native_report_read_is_not_silently_ignored():
    receiver=RawInput.__new__(RawInput);receiver.error=None
    receiver.user=SimpleNamespace(GetRawInputData=lambda *a:0xffffffff,DefWindowProcW=lambda *a:0)
    receiver._message(1,0xff,1,0x123456789)
    assert receiver.error
