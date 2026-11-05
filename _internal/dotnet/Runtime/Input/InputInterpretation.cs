using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

public sealed record InputRule(string Action, int? Slot, IReadOnlyList<string> Keys, string Gesture);
public sealed record InputInterpretationSettings(int HoldMs, IReadOnlyList<InputRule> Bindings, bool ShowOther, bool ShowMotion, bool ShowAxes)
{
    public static IReadOnlyList<InputRule> DefaultBindings()
    {
        List<InputRule> rows = [];
        for (var slot = 0; slot < 4; slot++)
        {
            var key = "K:" + (49 + slot).ToString(CultureInfo.InvariantCulture);
            rows.Add(new("skill", slot, [key], "tap_hold")); rows.Add(new("ultimate", slot, ["K:ALT", key], "press"));
            rows.Add(new("switch", slot, ["K:" + (112 + slot).ToString(CultureInfo.InvariantCulture)], "press"));
            rows.Add(new("skill", slot, ["P:LB", "P:" + new[] { "WEST", "NORTH", "EAST", "SOUTH" }[slot]], "tap_hold"));
        }
        rows.Add(new("combo", null, ["K:69"], "press")); rows.Add(new("combo", null, ["P:RB"], "press")); rows.Add(new("switch", null, ["K:81"], "press"));
        for (var slot = 0; slot < 4; slot++) rows.Add(new("switch", slot, ["P:" + new[] { "LEFT", "UP", "RIGHT", "DOWN" }[slot]], "press"));
        return rows;
    }
    public static InputInterpretationSettings Normalize(EvidenceValue? source = null)
    {
        var data = TraceData.Obj(source ?? EvidenceNull.Value);
        var threshold = TraceData.Int(data.Fields.GetValueOrDefault("hold_ms") ?? new EvidenceInteger(280));
        var hold = threshold is { } number ? (int)BigInteger.Clamp(number, 1, 10000) : 280;
        List<InputRule> rules = [];
        if (data.Get("bindings") is EvidenceArray rows)
        {
            foreach (var value in rows.Items.Take(128))
            {
                if (value is not EvidenceObject row || row.Get("action") is not EvidenceText action || action.Value is not ("skill" or "ultimate" or "combo" or "switch" or "other")
                    || row.Get("keys") is not EvidenceArray { Items.Count: >= 1 and <= 8 } keys
                    || !keys.Items.All(key => key is EvidenceText text && text.Value.EnumerateRunes().Count() is >= 1 and <= 40)) continue;
                rules.Add(new(action.Value, row.Get("slot") is EvidenceInteger { Value: var slot } && slot >= 0 && slot < 4 ? (int)slot : null,
                    keys.Items.Cast<EvidenceText>().Select(key => key.Value).Distinct(StringComparer.Ordinal).ToArray(),
                    row.Get("gesture") is EvidenceText { Value: "tap_hold" } ? "tap_hold" : "press"));
            }
        }
        else rules.AddRange(DefaultBindings());
        return new(hold, rules, TraceData.Truth(data.Get("show_other")), TraceData.Truth(data.Get("show_motion")), TraceData.Truth(data.Get("show_axes")));
    }
    public EvidenceObject ToEvidence() => TraceData.Make(("hold_ms", HoldMs), ("bindings", new EvidenceArray(Bindings.Select(rule =>
        TraceData.Make(("action", rule.Action), ("slot", rule.Slot), ("keys", rule.Keys), ("gesture", rule.Gesture))).ToArray())),
        ("show_other", ShowOther), ("show_motion", ShowMotion), ("show_axes", ShowAxes));
}

public sealed record InputIntention(string Action, int? Slot, string Device, IReadOnlyList<string> Keys, BigInteger StartWallNs, BigInteger EndWallNs,
    double DurationMs, string Rule, bool Interrupted, string Reason)
{
    public EvidenceObject ToEvidence() => TraceData.Make(("action", Action), ("slot", Slot), ("device", Device), ("keys", Keys),
        ("start_wall_ns", StartWallNs), ("end_wall_ns", EndWallNs), ("duration_ms", DurationMs), ("rule", Rule), ("interrupted", Interrupted), ("reason", Reason));
}

public sealed record ProjectedInputIntention(InputIntention Intention, double StartMs, double EndMs, string? CharacterKey, string SlotLabel)
{
    public EvidenceObject ToEvidence()
    {
        var fields = Intention.ToEvidence().Fields.ToDictionary(); fields["start_ms"] = new EvidenceReal(StartMs); fields["end_ms"] = new EvidenceReal(EndMs);
        fields["character_key"] = CharacterKey is null ? EvidenceNull.Value : new EvidenceText(CharacterKey); fields["slot_label"] = new EvidenceText(SlotLabel);
        return new(fields);
    }
    public string Tooltip => $"{SlotLabel} · {Intention.Action switch { "skill" => "战技输入", "ultimate" => "终结技输入", "combo" => "连携输入", "switch" => "切换输入", _ => "其他输入" }}（输入意图，不代表成功释放）\n"
        + Intention.Device + " · " + string.Join(" + ", Intention.Keys) + "\n"
        + (StartMs / 1000).ToString("F3", CultureInfo.InvariantCulture) + "s → " + (EndMs / 1000).ToString("F3", CultureInfo.InvariantCulture) + "s · "
        + Intention.DurationMs.ToString("F1", CultureInfo.InvariantCulture) + "ms\n" + Intention.Rule
        + (Intention.Interrupted ? "\n中断：" + Intention.Reason : "");
}

/// <summary>Offline input intentions. Holds and combinations never establish a successful combat action.</summary>
public sealed class InputInterpreter(EvidenceValue? settings = null)
{
    private sealed record Pending(InputRule Binding, string Device, EvidenceObject Start);
    private readonly InputInterpretationSettings settings = InputInterpretationSettings.Normalize(settings);
    private readonly Dictionary<string, HashSet<string>> held = new(StringComparer.Ordinal);
    private readonly List<Pending> pending = [];
    private readonly List<InputIntention> actions = [];
    private readonly HashSet<string> baselineKeys = new(StringComparer.Ordinal);
    private EvidenceObject? last;
    public IReadOnlyList<InputIntention> Actions => actions.Select(action => action with { Keys = action.Keys.ToArray() }).ToArray();
    public EvidenceObject? Last => last is null ? null : (EvidenceObject)EvidenceJson.Clone(last);
    public void Feed(EvidenceObject value)
    {
        var e = (EvidenceObject)EvidenceJson.Clone(value); last = e; var type = TraceData.S(e.Get("type"));
        if (type is "interrupt" or "gap" or "end")
        { Interrupt(e, TraceData.S(e.Fields.GetValueOrDefault("reason") ?? new EvidenceText(type)), e.Get("device") is EvidenceNull ? null : TraceData.S(e.Get("device"))); return; }
        if (type == "focus" && !TraceData.Truth(e.Get("active"))) { Interrupt(e, "focus_lost"); return; }
        if (type == "baseline")
        {
            var device = e.Get("device") is EvidenceNull ? null : TraceData.S(e.Get("device")); Interrupt(e, "baseline", device);
            if (device is null)
            {
                held.Clear(); baselineKeys.Clear();
                if (e.Get("keyboard_vks") is EvidenceArray codes) baselineKeys.UnionWith(codes.Items.Select(TraceData.S));
            }
            foreach (var (key, state) in TraceData.Obj(e.Get("states")).Fields)
                held[key] = state is EvidenceArray states ? states.Items.Select(TraceData.S).ToHashSet(StringComparer.Ordinal) : [];
            return;
        }
        var phase = TraceData.S(e.Get("phase")); if (type != "input" || phase is not ("down" or "up" or "repeat")) return;
        var code = TraceData.S(e.Fields.GetValueOrDefault("code") ?? new EvidenceText(""));
        if (TraceData.Truth(e.Get("mapped_device")) && code.StartsWith("J:", StringComparison.Ordinal)) return;
        var source = TraceData.S(e.Fields.GetValueOrDefault("device") ?? new EvidenceText("unknown"));
        if (!held.TryGetValue(source, out var keys)) held[source] = keys = new(StringComparer.Ordinal);
        if (baselineKeys.Contains(code)) { if (phase == "up") baselineKeys.Remove(code); return; }
        if (phase == "repeat") return;
        if (phase == "up")
        {
            keys.Remove(code);
            foreach (var item in pending.Where(item => item.Device == source && item.Binding.Keys.Contains(code)).ToArray()) Finish(item, e);
            return;
        }
        if (!keys.Add(code)) return;
        var matching = settings.Bindings.Where(binding => binding.Keys.Contains(code) && binding.Keys.All(keys.Contains)).OrderByDescending(binding => binding.Keys.Count);
        HashSet<string> claimed = new(StringComparer.Ordinal);
        foreach (var binding in matching)
        {
            var combination = binding.Keys.ToHashSet(StringComparer.Ordinal);
            if (combination.Overlaps(claimed) || pending.Any(item => item.Device == source && combination.IsProperSubsetOf(item.Binding.Keys))) continue;
            pending.RemoveAll(item => item.Device == source && item.Binding.Keys.All(combination.Contains));
            pending.Add(new(binding, source, e)); claimed.UnionWith(combination);
        }
    }
    private static BigInteger Number(EvidenceValue value) => TraceData.Int(value) ?? throw new FormatException("输入事件时间无效");
    private void Finish(Pending item, EvidenceObject end, bool interrupted = false, string reason = "")
    {
        pending.Remove(item); var start = item.Start; var startWall = Number(start.Get("wall_ns"));
        var endWall = Number(end.Fields.GetValueOrDefault("wall_ns") ?? end.Fields.GetValueOrDefault("start_wall_ns") ?? start.Get("wall_ns"));
        var endMono = end.Fields.GetValueOrDefault("mono_ns") ?? end.Get("start_mono_ns");
        var delta = start.Get("mono_ns") is not EvidenceNull && endMono is not EvidenceNull ? Number(endMono) - Number(start.Get("mono_ns")) : endWall - startWall;
        var duration = Math.Max(0, PythonIntegerDivision.Divide(delta, 1_000_000)); var action = item.Binding.Action; var rule = "组合成立 / 按下";
        if (item.Binding.Gesture == "tap_hold")
        { action = duration >= settings.HoldMs ? "ultimate" : "skill"; rule = action == "ultimate" ? $"长按 ≥ {settings.HoldMs}ms（参考值）" : "短按松开"; }
        actions.Add(new(action, item.Binding.Slot, item.Device, item.Binding.Keys.ToArray(), startWall, endWall, duration, rule, interrupted, reason));
    }
    public void Interrupt(EvidenceObject value, string reason, string? device = null)
    {
        foreach (var item in pending.Where(item => device is null || item.Device == device).ToArray()) Finish(item, value, true, reason);
        if (device is null) { held.Clear(); baselineKeys.Clear(); } else held.Remove(device);
    }
    public IReadOnlyList<InputIntention> Close() { if (last is not null) Interrupt(last, "incomplete_file"); return Actions; }
    public static IReadOnlyList<ProjectedInputIntention> Project(IEnumerable<InputIntention> actions, double startWallMs, double durationMs,
        IReadOnlyDictionary<int, string>? slots = null, double offsetMs = 0)
    {
        List<ProjectedInputIntention> result = [];
        foreach (var action in actions)
        {
            var start = PythonIntegerDivision.Divide(action.StartWallNs, BigInteger.One) / 1e6 - startWallMs + offsetMs;
            var end = PythonIntegerDivision.Divide(action.EndWallNs, BigInteger.One) / 1e6 - startWallMs + offsetMs;
            if (end < 0 || start > durationMs) continue;
            result.Add(new(action with { Keys = action.Keys.ToArray() }, start, end, action.Slot is { } slot ? slots?.GetValueOrDefault(slot) : null,
                action.Slot is { } position ? $"角色槽位{position + 1}" : "全局"));
        }
        return result;
    }
}
