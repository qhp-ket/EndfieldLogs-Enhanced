"""SDL3 adapter retaining raw joystick controls and associated mapped events."""
from __future__ import annotations
import ctypes as c
import struct
from endfield_pcap.runtime.paths import bundle_root

BUTTONS = ('SOUTH','EAST','WEST','NORTH','BACK','GUIDE','START','LSTICK','RSTICK',
           'LB','RB','UP','DOWN','LEFT','RIGHT','MISC1','RP1','LP1','RP2','LP2','TOUCHPAD')


class SDLInput:
    def __init__(self, emit):
        self.emit, self.joysticks, self.gamepads = emit, {}, {}
        self.lib = c.CDLL(str(bundle_root()/'native/SDL3.dll'))
        self._bind('SDL_SetHint', c.c_bool, c.c_char_p,c.c_char_p)
        self._bind('SDL_Init',c.c_bool,c.c_uint32)
        self._bind('SDL_PollEvent',c.c_bool,c.c_void_p)
        self._bind('SDL_GetError',c.c_char_p)
        for name in ('SDL_OpenJoystick','SDL_OpenGamepad'):
            self._bind(name,c.c_void_p,c.c_uint32)
        for name in ('SDL_CloseJoystick','SDL_CloseGamepad'):
            self._bind(name,None,c.c_void_p)
        for name in ('SDL_GetJoystickName','SDL_GetGamepadName'):
            self._bind(name,c.c_char_p,c.c_void_p)
        self._bind('SDL_IsGamepad',c.c_bool,c.c_uint32)
        self._bind('SDL_GetJoysticks',c.POINTER(c.c_uint32),c.POINTER(c.c_int))
        self._bind('SDL_free',None,c.c_void_p)
        self._bind('SDL_Quit',None)
        self._bind('SDL_GetNumJoystickButtons',c.c_int,c.c_void_p)
        self._bind('SDL_GetJoystickButton',c.c_bool,c.c_void_p,c.c_int)
        self._bind('SDL_GetNumJoystickAxes',c.c_int,c.c_void_p)
        self._bind('SDL_GetJoystickAxis',c.c_int16,c.c_void_p,c.c_int)
        self._bind('SDL_GetGamepadButton',c.c_bool,c.c_void_p,c.c_int)
        self._bind('SDL_GetGamepadAxis',c.c_int16,c.c_void_p,c.c_int)
        self._bind('SDL_GamepadHasSensor',c.c_bool,c.c_void_p,c.c_int)
        self._bind('SDL_SetGamepadSensorEnabled',c.c_bool,c.c_void_p,c.c_int,c.c_bool)
        for name in ('SDL_GetJoystickVendor','SDL_GetJoystickProduct'):
            self._bind(name,c.c_uint16,c.c_void_p)
        self._bind('SDL_GetJoystickSerial',c.c_char_p,c.c_void_p)
        for hint in (b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS',b'SDL_JOYSTICK_HIDAPI',
                     b'SDL_JOYSTICK_HIDAPI_PS5',b'SDL_JOYSTICK_HIDAPI_PS4'):
            self.lib.SDL_SetHint(hint,b'1')
        if not self.lib.SDL_Init(0x2000 | 0x200 | 0x4000):
            raise RuntimeError(self.lib.SDL_GetError().decode('utf8','replace'))
        count = c.c_int()
        ids = self.lib.SDL_GetJoysticks(c.byref(count))
        try:
            for index in range(count.value):
                self._open(ids[index])
        finally:
            self.lib.SDL_free(ids)
        self.buffer = c.create_string_buffer(128)

    def _bind(self,name,ret,*args):
        fn = getattr(self.lib,name)
        fn.restype,fn.argtypes = ret,list(args)

    def _open(self,identity):
        if identity in self.joysticks:
            return
        pointer = self.lib.SDL_OpenJoystick(identity)
        if not pointer:
            self.emit('error',backend='sdl3',message=self.lib.SDL_GetError().decode('utf8','replace'))
            return
        self.joysticks[identity] = pointer
        mapped = bool(self.lib.SDL_IsGamepad(identity))
        if mapped:
            pad = self.lib.SDL_OpenGamepad(identity)
            if pad:
                self.gamepads[identity] = pad
        name = self.lib.SDL_GetJoystickName(pointer)
        self.emit('device',device=f'sdl:{identity}',backend='sdl3',mapped=mapped,
                  name=name.decode('utf8','replace') if name else '',
                  vendor=self.lib.SDL_GetJoystickVendor(pointer),product=self.lib.SDL_GetJoystickProduct(pointer),
                  serial=(self.lib.SDL_GetJoystickSerial(pointer) or b'').decode('utf8','replace'))
        values={f'J:BUTTON{i}':1 for i in range(max(0,self.lib.SDL_GetNumJoystickButtons(pointer)))
                if self.lib.SDL_GetJoystickButton(pointer,i)}
        values.update({f'J:AXIS{i}':self.lib.SDL_GetJoystickAxis(pointer,i)
                       for i in range(max(0,self.lib.SDL_GetNumJoystickAxes(pointer)))})
        if identity in self.gamepads:
            pad=self.gamepads[identity]
            for sensor in range(1,7):
                if self.lib.SDL_GamepadHasSensor(pad,sensor) and not self.lib.SDL_SetGamepadSensorEnabled(pad,sensor,True):
                    self.emit('error',backend='sdl3',message=self.lib.SDL_GetError().decode('utf8','replace'))
            values.update({'P:'+name:1 for i,name in enumerate(BUTTONS) if self.lib.SDL_GetGamepadButton(pad,i)})
            values.update({f'P:AXIS{i}':self.lib.SDL_GetGamepadAxis(pad,i) for i in range(6)})
        self.emit('backend_baseline',device=f'sdl:{identity}',values=values)

    def pump(self):
        for _ in range(8192):
            if not self.lib.SDL_PollEvent(self.buffer):
                break
            raw = self.buffer.raw
            typ,_,stamp,identity = struct.unpack_from('<IIQI',raw)
            if typ in (0x605,0x653):
                self._open(identity)
                continue
            if typ in (0x606,0x654):
                if identity in self.gamepads:
                    self.lib.SDL_CloseGamepad(self.gamepads.pop(identity))
                if identity in self.joysticks:
                    self.lib.SDL_CloseJoystick(self.joysticks.pop(identity))
                self.emit('device_change',device=f'sdl:{identity}',connected=False)
                continue
            if not (0x600 <= typ <= 0x608 or 0x650 <= typ <= 0x65e):
                continue
            if typ in (0x608,0x65a):
                continue  # End-of-report markers have no control value.
            fields = dict(device=f'sdl:{identity}',backend='sdl3',native_time_ns=stamp,
                          association=f'{identity}:{stamp}',event_type=typ)
            index = raw[20]
            if typ in (0x600,0x650):
                fields.update(kind='axis',code=f'{"P" if typ==0x650 else "J"}:AXIS{index}',
                              value=struct.unpack_from('<h',raw,24)[0])
            elif typ in (0x603,0x604,0x651,0x652):
                mapped = typ >= 0x650
                fields.update(kind='button',code='P:'+BUTTONS[index] if mapped and index<len(BUTTONS)
                    else f'J:BUTTON{index}',phase='down' if raw[21] else 'up',value=int(bool(raw[21])))
            elif typ == 0x602:
                fields.update(kind='hat',code=f'J:HAT{index}',value=raw[21])
            elif typ == 0x659:
                fields.update(kind='sensor',code=f'P:SENSOR{struct.unpack_from("<i",raw,20)[0]}',
                              value=list(struct.unpack_from('<fff',raw,24)),sensor_time_ns=struct.unpack_from('<Q',raw,40)[0])
            elif typ in (0x656,0x657,0x658):
                pad,finger,x,y,pressure=struct.unpack_from('<iifff',raw,20)
                fields.update(kind='touch',code=f'P:TOUCH{pad}:{finger}',value=[x,y,pressure],
                              phase={0x656:'down',0x657:'motion',0x658:'up'}[typ])
            else:
                # Preserve touch, sensors, trackballs, battery and future controls losslessly.
                fields.update(kind='other',code=f'SDL:{typ:x}',value=list(raw[20:128]))
            fields['mapped_device'] = identity in self.gamepads
            self.emit('input',**fields)

    def close(self):
        for pointer in self.gamepads.values():
            self.lib.SDL_CloseGamepad(pointer)
        for pointer in self.joysticks.values():
            self.lib.SDL_CloseJoystick(pointer)
        self.lib.SDL_Quit()
