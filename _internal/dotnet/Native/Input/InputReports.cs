using System.Buffers.Binary;
using System.Globalization;

namespace EndfieldLogs.Native.Input;

public sealed record NativeInputReport(string Type, IReadOnlyDictionary<string, object?> Fields)
{
    public static NativeInputReport Create(string type, params (string Key, object? Value)[] pairs) => new(type, FieldsOf(pairs));
    public static Dictionary<string, object?> FieldsOf(params (string Key, object? Value)[] pairs) => pairs.ToDictionary(p => p.Key, p => p.Value);
}

/// <summary>Windows x64 RAWINPUT payload decoder; device discovery and clocks belong to the receiver.</summary>
public sealed class RawInputDecoder(Action<NativeInputReport> emit)
{
    private readonly HashSet<(string Device, ushort Scan, int Flags)> pressed = [];
    public static string KeyCode(int vk) => vk switch
    { 0x10 or 0xa0 or 0xa1 => "SHIFT", 0x11 or 0xa2 or 0xa3 => "CTRL", 0x12 or 0xa4 or 0xa5 => "ALT", 0x5b or 0x5c => "WIN", _ => vk.ToString(CultureInfo.InvariantCulture) };
    public void Disconnect(string device) => pressed.RemoveWhere(key => key.Device == device);
    public void Decode(uint type, string device, ReadOnlySpan<byte> data)
    {
        if (type == 1 && data.Length >= 16)
        {
            var scan = BinaryPrimitives.ReadUInt16LittleEndian(data); var flags = BinaryPrimitives.ReadUInt16LittleEndian(data[2..]);
            var vk = BinaryPrimitives.ReadUInt16LittleEndian(data[6..]); if (vk == 255) return;
            var key = (device, scan, flags & 6); var up = (flags & 1) != 0; var repeat = !up && pressed.Contains(key);
            if (up) pressed.Remove(key); else pressed.Add(key);
            emit(NativeInputReport.Create("input", ("device", device), ("backend", "raw_input"), ("kind", "key"), ("code", "K:" + KeyCode(vk)),
                ("phase", up ? "up" : repeat ? "repeat" : "down"), ("value", up ? 0 : 1),
                ("raw", NativeInputReport.FieldsOf(("vk", vk), ("scan", scan), ("flags", flags),
                    ("message", BinaryPrimitives.ReadUInt32LittleEndian(data[8..])), ("extra", BinaryPrimitives.ReadUInt32LittleEndian(data[12..]))))));
        }
        else if (type == 0 && data.Length >= 24)
        {
            var flags = BinaryPrimitives.ReadUInt16LittleEndian(data); var buttons = BinaryPrimitives.ReadUInt16LittleEndian(data[4..]);
            var value = BinaryPrimitives.ReadInt16LittleEndian(data[6..]); var x = BinaryPrimitives.ReadInt32LittleEndian(data[12..]);
            var y = BinaryPrimitives.ReadInt32LittleEndian(data[16..]); var extra = BinaryPrimitives.ReadUInt32LittleEndian(data[20..]);
            if (x != 0 || y != 0 || (flags & 1) != 0)
                Emit("motion", "M:MOVE", new[] { x, y }, null, NativeInputReport.FieldsOf(("flags", flags), ("extra", extra)));
            for (var button = 0; button < 5; button++)
                for (var up = 0; up <= 1; up++)
                    if ((buttons & (1 << (button * 2 + up))) != 0) Emit("button", "M:" + (button + 1), 1 - up, up == 0 ? "down" : "up");
            if ((buttons & 0x400) != 0) Emit("wheel", "M:WHEEL", value);
            if ((buttons & 0x800) != 0) Emit("wheel", "M:HWHEEL", value);
        }
        void Emit(string kind, string code, object value, string? phase = null, object? raw = null)
        {
            var fields = NativeInputReport.FieldsOf(("device", device), ("backend", "raw_input"), ("kind", kind), ("code", code), ("value", value));
            if (phase is not null) fields["phase"] = phase; if (raw is not null) fields["raw"] = raw; emit(new("input", fields));
        }
    }
}

/// <summary>SDL3 event ABI decoder. Native handles and device baselines are owned by SdlInputSource.</summary>
public static class SdlInputDecoder
{
    public static readonly IReadOnlyList<string> Buttons = Array.AsReadOnly(new[]
    { "SOUTH", "EAST", "WEST", "NORTH", "BACK", "GUIDE", "START", "LSTICK", "RSTICK", "LB", "RB", "UP", "DOWN", "LEFT", "RIGHT", "MISC1", "RP1", "LP1", "RP2", "LP2", "TOUCHPAD" });
    public static NativeInputReport? Decode(ReadOnlySpan<byte> raw, bool mapped)
    {
        if (raw.Length < 128) throw new InvalidDataException("SDL3 事件缓冲区不完整");
        var type = BinaryPrimitives.ReadUInt32LittleEndian(raw); var stamp = BinaryPrimitives.ReadUInt64LittleEndian(raw[8..]); var id = BinaryPrimitives.ReadUInt32LittleEndian(raw[16..]);
        if (!(type is >= 0x600 and <= 0x608 or >= 0x650 and <= 0x65e) || type is 0x605 or 0x606 or 0x653 or 0x654 or 0x608 or 0x65a) return null;
        var fields = NativeInputReport.FieldsOf(("device", $"sdl:{id}"), ("backend", "sdl3"), ("native_time_ns", stamp),
            ("association", $"{id}:{stamp}"), ("event_type", type)); var index = raw[20];
        string kind, code; object value;
        if (type is 0x600 or 0x650)
        { kind = "axis"; code = $"{(type == 0x650 ? "P" : "J")}:AXIS{index}"; value = BinaryPrimitives.ReadInt16LittleEndian(raw[24..]); }
        else if (type is 0x603 or 0x604 or 0x651 or 0x652)
        { kind = "button"; code = type >= 0x650 && index < Buttons.Count ? "P:" + Buttons[index] : $"J:BUTTON{index}"; fields["phase"] = raw[21] != 0 ? "down" : "up"; value = raw[21] != 0 ? 1 : 0; }
        else if (type == 0x602) { kind = "hat"; code = $"J:HAT{index}"; value = raw[21]; }
        else if (type == 0x659)
        {
            kind = "sensor"; code = $"P:SENSOR{BinaryPrimitives.ReadInt32LittleEndian(raw[20..])}";
            value = new[] { (double)BinaryPrimitives.ReadSingleLittleEndian(raw[24..]), (double)BinaryPrimitives.ReadSingleLittleEndian(raw[28..]), (double)BinaryPrimitives.ReadSingleLittleEndian(raw[32..]) };
            fields["sensor_time_ns"] = BinaryPrimitives.ReadUInt64LittleEndian(raw[40..]);
        }
        else if (type is 0x656 or 0x657 or 0x658)
        {
            kind = "touch"; code = $"P:TOUCH{BinaryPrimitives.ReadInt32LittleEndian(raw[20..])}:{BinaryPrimitives.ReadInt32LittleEndian(raw[24..])}";
            value = new[] { (double)BinaryPrimitives.ReadSingleLittleEndian(raw[28..]), (double)BinaryPrimitives.ReadSingleLittleEndian(raw[32..]), (double)BinaryPrimitives.ReadSingleLittleEndian(raw[36..]) };
            fields["phase"] = type == 0x656 ? "down" : type == 0x658 ? "up" : "motion";
        }
        else { kind = "other"; code = $"SDL:{type:x}"; value = raw[20..128].ToArray().Select(b => (int)b).ToArray(); }
        fields["kind"] = kind; fields["code"] = code; fields["value"] = value; fields["mapped_device"] = mapped; return new("input", fields);
    }
}
