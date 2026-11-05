using System.Buffers.Binary;
using System.Runtime.InteropServices;

namespace EndfieldLogs.Native.Input;

/// <summary>SDL3 raw joystick and mapped gamepad source; all calls stay on the worker's control thread.</summary>
public sealed unsafe class SdlInputSource : IDisposable
{
    private readonly nint library;
    private readonly Action<NativeInputReport> emit;
    private readonly Dictionary<uint, nint> joysticks = [], gamepads = [];
    private bool initialized, disposed;
    private readonly byte[] buffer = new byte[128];
    private nint Fn(string name) => NativeLibrary.GetExport(library, "SDL_" + name);
    private string Error() => Text(((delegate* unmanaged[Cdecl]<nint>)Fn("GetError"))());
    private static string Text(nint value) => value == 0 ? "" : Marshal.PtrToStringUTF8(value) ?? "";
    public SdlInputSource(string path, Action<NativeInputReport> emit)
    {
        this.emit = emit; library = NativeLibrary.Load(Path.GetFullPath(path));
        try
        {
            foreach (var hint in new[] { "SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "SDL_JOYSTICK_HIDAPI", "SDL_JOYSTICK_HIDAPI_PS5", "SDL_JOYSTICK_HIDAPI_PS4" })
            {
                var key = Marshal.StringToCoTaskMemUTF8(hint); var value = Marshal.StringToCoTaskMemUTF8("1");
                try { ((delegate* unmanaged[Cdecl]<nint, nint, byte>)Fn("SetHint"))(key, value); }
                finally { Marshal.FreeCoTaskMem(key); Marshal.FreeCoTaskMem(value); }
            }
            if (((delegate* unmanaged[Cdecl]<uint, byte>)Fn("Init"))(0x6200) == 0) throw new IOException(Error()); initialized = true;
            int count = 0; var ids = ((delegate* unmanaged[Cdecl]<int*, uint*>)Fn("GetJoysticks"))(&count);
            try { for (var at = 0; at < count; at++) Open(ids[at]); }
            finally { ((delegate* unmanaged[Cdecl]<void*, void>)Fn("free"))(ids); }
        }
        catch { Dispose(); throw; }
    }
    private void Open(uint id)
    {
        if (joysticks.ContainsKey(id)) return;
        var pointer = ((delegate* unmanaged[Cdecl]<uint, nint>)Fn("OpenJoystick"))(id);
        if (pointer == 0) { emit(NativeInputReport.Create("error", ("backend", "sdl3"), ("message", Error()))); return; }
        joysticks[id] = pointer;
        var mapped = ((delegate* unmanaged[Cdecl]<uint, byte>)Fn("IsGamepad"))(id) != 0;
        if (mapped)
        { var pad = ((delegate* unmanaged[Cdecl]<uint, nint>)Fn("OpenGamepad"))(id); if (pad != 0) gamepads[id] = pad; }
        emit(NativeInputReport.Create("device", ("device", $"sdl:{id}"), ("backend", "sdl3"), ("mapped", mapped),
            ("name", Text(((delegate* unmanaged[Cdecl]<nint, nint>)Fn("GetJoystickName"))(pointer))),
            ("vendor", ((delegate* unmanaged[Cdecl]<nint, ushort>)Fn("GetJoystickVendor"))(pointer)),
            ("product", ((delegate* unmanaged[Cdecl]<nint, ushort>)Fn("GetJoystickProduct"))(pointer)),
            ("serial", Text(((delegate* unmanaged[Cdecl]<nint, nint>)Fn("GetJoystickSerial"))(pointer)))));
        Dictionary<string, object?> values = [];
        var buttons = ((delegate* unmanaged[Cdecl]<nint, int>)Fn("GetNumJoystickButtons"))(pointer);
        for (var at = 0; at < buttons; at++) if (((delegate* unmanaged[Cdecl]<nint, int, byte>)Fn("GetJoystickButton"))(pointer, at) != 0) values[$"J:BUTTON{at}"] = 1;
        var axes = ((delegate* unmanaged[Cdecl]<nint, int>)Fn("GetNumJoystickAxes"))(pointer);
        for (var at = 0; at < axes; at++) values[$"J:AXIS{at}"] = ((delegate* unmanaged[Cdecl]<nint, int, short>)Fn("GetJoystickAxis"))(pointer, at);
        if (gamepads.TryGetValue(id, out var gamepad))
        {
            for (var sensor = 1; sensor < 7; sensor++)
                if (((delegate* unmanaged[Cdecl]<nint, int, byte>)Fn("GamepadHasSensor"))(gamepad, sensor) != 0
                    && ((delegate* unmanaged[Cdecl]<nint, int, byte, byte>)Fn("SetGamepadSensorEnabled"))(gamepad, sensor, 1) == 0)
                    emit(NativeInputReport.Create("error", ("backend", "sdl3"), ("message", Error())));
            for (var at = 0; at < SdlInputDecoder.Buttons.Count; at++)
                if (((delegate* unmanaged[Cdecl]<nint, int, byte>)Fn("GetGamepadButton"))(gamepad, at) != 0) values["P:" + SdlInputDecoder.Buttons[at]] = 1;
            for (var at = 0; at < 6; at++) values[$"P:AXIS{at}"] = ((delegate* unmanaged[Cdecl]<nint, int, short>)Fn("GetGamepadAxis"))(gamepad, at);
        }
        emit(NativeInputReport.Create("backend_baseline", ("device", $"sdl:{id}"), ("values", values)));
    }
    public void Pump()
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        fixed (byte* data = buffer)
            for (var at = 0; at < 8192; at++)
            {
                if (((delegate* unmanaged[Cdecl]<byte*, byte>)Fn("PollEvent"))(data) == 0) break;
                var type = BinaryPrimitives.ReadUInt32LittleEndian(buffer); var id = BinaryPrimitives.ReadUInt32LittleEndian(buffer.AsSpan(16));
                if (type is 0x605 or 0x653) Open(id);
                else if (type is 0x606 or 0x654)
                { Close(id); emit(NativeInputReport.Create("device_change", ("device", $"sdl:{id}"), ("connected", false))); }
                else if (SdlInputDecoder.Decode(buffer, gamepads.ContainsKey(id)) is { } report) emit(report);
            }
    }
    private void Close(uint id)
    {
        if (gamepads.Remove(id, out var pad)) ((delegate* unmanaged[Cdecl]<nint, void>)Fn("CloseGamepad"))(pad);
        if (joysticks.Remove(id, out var stick)) ((delegate* unmanaged[Cdecl]<nint, void>)Fn("CloseJoystick"))(stick);
    }
    public void Dispose()
    {
        if (disposed) return; disposed = true;
        try { foreach (var id in joysticks.Keys.ToArray()) Close(id); if (initialized) ((delegate* unmanaged[Cdecl]<void>)Fn("Quit"))(); }
        finally { NativeLibrary.Free(library); }
    }
}
