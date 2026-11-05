using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Runtime.History;

public sealed record EnergySegment(double Start, double End, double StartValue, double EndValue, double Rate, double Capacity);
public sealed record EnergySeries(IReadOnlyList<EvidenceObject> Samples, IReadOnlyList<EnergySegment> Segments,
    double? Capacity, double? InitialValue, IReadOnlyList<string> Notes);
public sealed record ControlSegment(double Start, double End, string Character, string Name, string Evidence);

/// <summary>Shared energy observations and explicit estimates. They never modify combat results.</summary>
public static class EnergyObservations
{
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : [];
    private static string Text(EvidenceValue value) => value is EvidenceText text ? text.Value : "";
    private static double? Number(EvidenceValue value) => value is EvidenceBoolean flag ? flag.Value ? 1 : 0
        : SettingsData.Number(value, double.NaN) is var number && double.IsFinite(number) ? number : null;
    private static IReadOnlyList<EvidenceObject> Observations(EvidenceObject snapshot) => Rows(snapshot.Get("atb_events"))
        .Where(row => Number(row.Get("ts_ms_from_start")) is not null).Select(row =>
        { var values = row.Fields.ToDictionary(); values["time_ms"] = new EvidenceReal(Number(row.Get("ts_ms_from_start"))!.Value); return new EvidenceObject(values); })
        .OrderBy(row => Number(row.Get("time_ms"))).ThenBy(row => Number(row.Get("line_no")) ?? 0).ToArray();
    public static IReadOnlyList<ControlSegment> Control(EvidenceObject snapshot)
    {
        var observations = Observations(snapshot).Where(row => SettingsData.Truth(row.Get("character_key"))).ToArray();
        if (observations.Length == 0) return [];
        var end = Math.Max(Number((snapshot.Get("battle") as EvidenceObject)?.Get("duration_ms") ?? EvidenceNull.Value) ?? 0, Number(observations[^1].Get("time_ms"))!.Value);
        List<ControlSegment> result = []; var first = Number(observations[0].Get("time_ms"))!.Value;
        if (first > 0) result.Add(new(0, first, "", "未知", "首次主控观测之前，没有切换证据"));
        for (var index = 0; index < observations.Length; index++)
        {
            var row = observations[index]; var start = Math.Max(0, Number(row.Get("time_ms"))!.Value);
            var stop = index + 1 < observations.Length ? Math.Min(end, Number(observations[index + 1].Get("time_ms"))!.Value) : end;
            if (stop <= start) continue;
            var key = Text(row.Get("character_key"));
            if (result.Count > 0 && result[^1].Character == key && result[^1].End == start) result[^1] = result[^1] with { End = stop };
            else result.Add(new(start, stop, key, TimelineSkills.CharacterName(key), "ATB owner 主控观测；色块延续至下一次观测，不是精确切换时刻"));
        }
        return result;
    }
    public static EnergySeries Build(EvidenceObject snapshot, EvidenceObject? rules = null)
    {
        var samples = Observations(snapshot).Where(row => Number(row.Get("value")) is not null).Select(row =>
        { var values = row.Fields.ToDictionary(); values["value"] = new EvidenceReal(Number(row.Get("value"))!.Value); return new EvidenceObject(values); }).ToArray();
        if (samples.Length == 0) return new([], [], null, null, ["没有技力锚点，无法推算初始值"]);
        rules ??= SettingsData.Empty();
        var battle = snapshot.Get("battle") as EvidenceObject; var stageId = battle is null ? "" : Text(battle.Get("dungeon_context_id"));
        var stage = (rules.Get("stages") as EvidenceObject)?.Get(stageId) as EvidenceObject ?? SettingsData.Empty();
        var knownCapacity = Number(stage.Get("capacity")); if (knownCapacity < samples.Max(row => Number(row.Get("value"))!.Value)) knownCapacity = null;
        var capacity = knownCapacity is > 0 ? knownCapacity.Value : double.PositiveInfinity;
        List<(double Time, double Cost)> costs = []; List<(double Start, double End)> pauses = []; HashSet<string> missing = [];
        foreach (var cast in Rows(snapshot.Get("casts")))
        {
            var stamp = Number(cast.Get("ts_ms_from_start")); if (stamp is null) continue;
            var skill = Text(cast.Get("skill_key")); var rule = (rules.Get("skills") as EvidenceObject)?.Get(skill) as EvidenceObject;
            if (rule is not null && Number(rule.Get("cost")) is { } cost)
            { if (cost > 0) { costs.Add((stamp.Value, cost)); pauses.Add((stamp.Value, stamp.Value + 500)); } }
            else if (skill.EndsWith("_normal_skill", StringComparison.Ordinal)) missing.Add("部分战技消耗未知");
            if (skill.EndsWith("_ultimate_skill", StringComparison.Ordinal))
            {
                var stop = Number(cast.Get("end_ms_from_start"));
                if (stop is { } final && final >= stamp.Value) pauses.Add((stamp.Value, final)); else missing.Add("部分终结技恢复暂停终点未知");
            }
        }
        var end = Math.Max(battle is null ? 0 : Number(battle.Get("duration_ms")) ?? 0, Number(samples[^1].Get("time_ms"))!.Value);
        List<EnergySegment> segments = []; var lastRecovery = Number(stage.Get("base_recovery_per_second"));
        for (var index = 0; index < samples.Length; index++)
        {
            var point = samples[index]; var start = Number(point.Get("time_ms"))!.Value;
            var stop = index + 1 < samples.Length ? Number(samples[index + 1].Get("time_ms"))!.Value : end;
            var recovery = Number(point.Get("recovery_speed")); if (recovery is not null) lastRecovery = recovery; else recovery = lastRecovery;
            if (stop <= start) continue;
            if (recovery is null) { missing.Add("恢复速度未知的区间不补画；不套用普通关卡 8/s"); continue; }
            SortedSet<double> boundaries = [start, stop]; Dictionary<double, double> deductions = [];
            foreach (var (stamp, cost) in costs) if (start < stamp && stamp < stop) { boundaries.Add(stamp); deductions[stamp] = deductions.GetValueOrDefault(stamp) + cost; }
            foreach (var (left, right) in pauses) { if (start < left && left < stop) boundaries.Add(left); if (start < right && right < stop) boundaries.Add(right); }
            var value = Number(point.Get("value"))!.Value; var edges = boundaries.ToArray();
            for (var edge = 0; edge + 1 < edges.Length; edge++)
            {
                var left = edges[edge]; var right = edges[edge + 1]; value = Math.Max(0, value - deductions.GetValueOrDefault(left));
                var rate = pauses.Any(pause => pause.Start <= left && left < pause.End) ? 0 : recovery.Value;
                var final = Math.Max(0, Math.Min(capacity, value + rate * (right - left) / 1000));
                segments.Add(new(left, right, value, final, rate, capacity)); value = final;
            }
        }
        if (knownCapacity is null) missing.Add("本关技力上限未知，未按普通关卡 300 截断；图形纵轴不是上限");
        if (Number(samples[0].Get("time_ms")) > 0) missing.Add("初始技力未知，不从普通关卡初始值补画");
        var notes = new[] { "实心点为实测；虚线为自然恢复及已知战技消耗推算，锚点到来即校正", "闪避、动态返还、脱战与恢复暂停可能缺失；推算不能当作精确实测" }.Concat(missing.Order(PythonDisplay.CodePointComparer)).ToArray();
        return new(samples, segments, knownCapacity, samples.Where(row => Number(row.Get("time_ms")) == 0).Select(row => Number(row.Get("value"))).FirstOrDefault(), notes);
    }
    public static (double? Value, string Evidence) At(EnergySeries series, double stamp)
    {
        var point = series.Samples.LastOrDefault(row => Number(row.Get("time_ms")) <= stamp);
        if (point is null) return (null, "未知（首次技力观测之前）");
        if (Math.Abs(Number(point.Get("time_ms"))!.Value - stamp) < .5) return (Number(point.Get("value")), "实测");
        var segment = series.Segments.LastOrDefault(row => row.Start <= stamp);
        if (segment is null) return (null, "未知");
        if (stamp < segment.Start || stamp > segment.End) return (null, "未知（超出观测/推算范围）");
        return (Math.Max(0, Math.Min(segment.Capacity, segment.StartValue + segment.Rate * (stamp - segment.Start) / 1000)), "估算（缺失状态可能影响数值）");
    }
    public static EvidenceObject Rules(ResourceFiles resources) => resources.ReadRelative("data/local_semantics/team_energy_rules.json") as EvidenceObject ?? SettingsData.Empty();
}
