using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Runtime.History;

public sealed record TimelineSkillLabel(string Name, string Category, string Group = "");
public sealed record TimelineSkill(string Owner, double Start, double End, string Name, string Category,
    string RawSkill, EvidenceObject? Cast, IReadOnlyList<EvidenceObject> Events)
{
    public string Key => PythonSortedJson.Serialize(new EvidenceArray([new EvidenceText(Category), new EvidenceText(RawSkill.Length > 0 ? RawSkill : Name)]), compact: true);
}
public sealed record TimelineSkillOption(string Key, string Name, string Category);
public sealed record TimelineSkillLane(string Id, string Name, IReadOnlyList<string> Skills);

/// <summary>Display identities and skill blocks use report evidence, independently of attribution.</summary>
public static partial class TimelineSkills
{
    private static readonly Lazy<EvidenceObject> Dictionary = new(() =>
    {
        using var stream = typeof(TimelineSkills).Assembly.GetManifestResourceStream("EndfieldLogs.SkillNames.json")
            ?? throw new InvalidDataException("缺少技能显示名称资源");
        using StreamReader reader = new(stream); return (EvidenceObject)EvidenceJson.Parse(reader.ReadToEnd());
    });
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : [];
    private static string Text(EvidenceValue value, string fallback = "") => value is EvidenceText { Value.Length: > 0 } text ? text.Value : fallback;
    private static double? Number(EvidenceValue value) => value is EvidenceNull ? null : SettingsData.Number(value, double.NaN) is var number && double.IsFinite(number) ? number : null;
    [GeneratedRegex(@"_attack_(\d+)")] private static partial Regex AttackNumber();
    [GeneratedRegex(@"_combo(?:_\d+)?_skill")] private static partial Regex Combo();
    [GeneratedRegex(@"_normal_skill|_skill$|_skill_\d+")] private static partial Regex Skill();
    [GeneratedRegex(@"_attack\d*(?:_|$)|_dash_attack|_plunging_attack|_power_attack")] private static partial Regex Attack();
    [GeneratedRegex(@"_(?:normal_skill|combo_skill|ultimate_skill|combo|attack\d*)$")] private static partial Regex Family();
    [GeneratedRegex(@"_attack(\d+)(?:_|$)")] private static partial Regex Segment();
    [GeneratedRegex(@"\A([a-z]+)(?:_?(\d+))?\z")] private static partial Regex Suffix();
    public static string CharacterName(string key, string fallback = "") => ((Dictionary.Value.Get("chars") as EvidenceObject)?.Get(key) as EvidenceObject)?.Get("n") is EvidenceText { Value.Length: > 0 } name ? name.Value : fallback.Length > 0 ? fallback : key;
    public static TimelineSkillLabel Label(string key, string fallback = "")
    {
        var data = Dictionary.Value; var index = (EvidenceObject)data.Get("skillIndex"); var groups = (EvidenceObject)data.Get("groups");
        var normalized = AttackNumber().Replace(key, "_attack$1"); var matched = ""; var group = "";
        if (groups.Fields.ContainsKey(key)) group = key;
        else
        {
            var parts = normalized.Split('_'); var candidates = Enumerable.Range(3, Math.Max(0, parts.Length - 2)).Reverse().Select(length => string.Join('_', parts.Take(length))).ToArray();
            foreach (var candidate in candidates) if (index.Get(candidate) is EvidenceText target) { matched = candidate; group = target.Value; break; }
            if (group.Length == 0) foreach (var candidate in candidates.Where(candidate => Family().IsMatch(candidate)))
            {
                var targets = index.Fields.Where(pair => pair.Key.StartsWith(candidate + "_", StringComparison.Ordinal)).Select(pair => Text(pair.Value)).Distinct().ToArray();
                if (targets.Length == 1) { matched = candidate; group = targets[0]; break; }
            }
        }
        if (group.Length == 0) return new(fallback.Length > 0 ? fallback : key.Length > 0 ? key : "未知技能",
            normalized.Contains("_ultimate_skill", StringComparison.Ordinal) ? "大招" : Combo().IsMatch(normalized) ? "连携" : Skill().IsMatch(normalized) ? "战技" : Attack().IsMatch(normalized) ? "普攻" : "其他");
        var row = (EvidenceArray)groups.Get(group); var suffix = matched.Length > 0 ? normalized[matched.Length..].TrimStart('_') : "";
        var action = ""; var attack = Segment().Match(normalized);
        if (attack.Success)
        {
            var segment = int.Parse(attack.Groups[1].Value); action = segment is >= 1 and <= 10 ? "①②③④⑤⑥⑦⑧⑨⑩"[(segment - 1)..segment] : $"第{segment}段";
        }
        else if (normalized.Contains("_power_attack", StringComparison.Ordinal)) action = "重击";
        else if (normalized.Contains("_plunging_attack", StringComparison.Ordinal)) action = "下落";
        else if (normalized.Contains("_dash_attack", StringComparison.Ordinal)) action = "闪避";
        var suffixes = new Dictionary<string, string> { ["projhit"] = "弹体命中", ["abilityrange"] = "范围", ["laser"] = "激光", ["total"] = "合计", ["seal"] = "印记", ["finisher"] = "收招", ["start"] = "起手", ["end"] = "收招", ["hit"] = "命中", ["explode"] = "爆炸", ["explosion"] = "爆炸", ["boom"] = "爆炸" };
        var match = Suffix().Match(suffix);
        if (match.Success && suffixes.TryGetValue(match.Groups[1].Value, out var detail)) suffix = detail + (match.Groups[2].Success ? "·" + match.Groups[2].Value : "");
        var details = new[] { action, suffix }.Where(value => value.Length > 0).ToArray();
        return new(Text(row.Items[0]) + (details.Length > 0 ? " · " + string.Join(" · ", details) : ""),
            Text(((EvidenceArray)data.Get("cats")).Items[(int)((EvidenceInteger)row.Items[1]).Value]), group);
    }
    private static string? Category(string raw, string category, bool recovers = false) => category == "普攻" ? raw.Contains("_power_attack", StringComparison.Ordinal) || recovers ? "重击" : null : category;
    public static IReadOnlyList<TimelineSkill> Build(EvidenceObject report)
    {
        var owners = Rows(report.Get("participants")).Select(row => Text(row.Get("character_key"))).ToHashSet(StringComparer.Ordinal);
        List<TimelineSkill> blocks = []; Dictionary<(string Owner, double Start), List<int>> casts = [];
        foreach (var cast in Rows(report.Get("casts")))
        {
            var owner = Text(cast.Get("character_key")); if (!owners.Contains(owner) || Text(cast.Get("skill_source")).Equals("summon", StringComparison.OrdinalIgnoreCase)) continue;
            var raw = Text(cast.Get("skill_key")); var label = Label(raw, Text(cast.Get("skill_name"), raw)); var category = Category(raw, label.Category, SettingsData.Truth(cast.Get("recovers_energy"))); if (category is null) continue;
            var start = Number(cast.Get("ts_ms_from_start")) ?? 0; var end = Math.Max(start, Number(cast.Get("end_ms_from_start")) ?? start);
            var observation = SettingsData.Make(("event_type", "cast"), ("lane_type", "skill"), ("event_key", raw), ("event_name", label.Name), ("source_character_key", owner), ("ts_ms_from_start", start));
            if (!casts.TryGetValue((owner, start), out var indexes)) casts[(owner, start)] = indexes = [];
            indexes.Add(blocks.Count); blocks.Add(new(owner, start, end, label.Name, category, raw, cast, [observation]));
        }
        Dictionary<string, int> grouped = new(StringComparer.Ordinal); var eventIndex = 0;
        foreach (var row in Rows(report.Get("timeline_events")))
        {
            var index = eventIndex++; var owner = Text(row.Get("source_character_key"));
            if (Text(row.Get("lane_type")) != "skill" || !owners.Contains(owner)) continue;
            var raw = Text(row.Get("event_key")); var label = Label(raw, Text(row.Get("event_name"), raw));
            var start = Number(row.Get("ts_ms_from_start")) ?? 0; var duration = Math.Max(0, Number(row.Get("duration_ms")) ?? 0);
            var actual = Number(row.Get("actual_start_ms_from_start"));
            var candidates = casts.GetValueOrDefault((owner, actual ?? start)) ?? [];
            var matches = candidates.Where(i => raw == blocks[i].RawSkill || label.Group.Length > 0 && label.Group == Label(blocks[i].RawSkill).Group).ToArray();
            if (matches.Length == 1)
            {
                if (Text(row.Get("event_type")) == "damage") { var block = blocks[matches[0]]; blocks[matches[0]] = block with { Events = [.. block.Events, row] }; }
                continue;
            }
            var category = Category(raw, label.Category); if (category is null) continue;
            if (actual is not null) { start = actual.Value; duration = Math.Max(0, (Number(row.Get("actual_end_ms_from_start")) ?? start) - start); }
            var group = Text(row.Get("event_type")) == "damage" ? Text(row.Get("event_group_key")) : "";
            var identity = actual is not null ? SettingsData.Value(new object[] { owner, "skill", raw, actual.Value }) : SettingsData.Value(new object[] { owner, "skill", group.Length > 0 ? group : index });
            var key = EvidenceJsonSignature.Sorted(identity);
            if (grouped.TryGetValue(key, out var found))
            {
                var block = blocks[found]; blocks[found] = block with { Start = Math.Min(block.Start, start), End = Math.Max(block.End, start + duration), Events = [.. block.Events, row] };
            }
            else { grouped[key] = blocks.Count; blocks.Add(new(owner, start, start + duration, label.Name, category, raw, null, [row])); }
        }
        return blocks.OrderBy(block => block.Start).ThenBy(block => block.Owner, PythonDisplay.CodePointComparer).ToArray();
    }
    public static IReadOnlyList<TimelineSkillOption> Options(IEnumerable<TimelineSkill> blocks, string owner) => blocks.Where(block => block.Owner == owner)
        .DistinctBy(block => block.Key).Select(block => new TimelineSkillOption(block.Key, block.Name, block.Category)).ToArray();
    public static IReadOnlyList<TimelineSkillLane> Defaults(IReadOnlyList<TimelineSkillOption> options) => new[]
    {
        new TimelineSkillLane("战技", "战技", options.Where(option => option.Category == "战技").Select(option => option.Key).ToArray()),
        new TimelineSkillLane("连携", "连携 / 终结", options.Where(option => option.Category is "连携" or "大招").Select(option => option.Key).ToArray()),
    }.Where(lane => lane.Skills.Count > 0).ToArray();
    public static IReadOnlyList<TimelineSkillLane> Resolve(IReadOnlyList<TimelineSkillOption> options, string owner, EvidenceValue? saved)
    {
        var normalized = SettingsCodec.LaneConfigs(new EvidenceObject(new Dictionary<string, EvidenceValue> { [owner] = saved ?? EvidenceNull.Value }));
        if (normalized.Get(owner) is not EvidenceArray rows) return Defaults(options);
        var lanes = rows.Items.OfType<EvidenceObject>().Select(row => new TimelineSkillLane(Text(row.Get("id")), Text(row.Get("name")), SettingsData.Strings(row.Get("skills")).ToArray())).ToList();
        var assigned = lanes.SelectMany(lane => lane.Skills).ToHashSet(StringComparer.Ordinal); var missing = options.Where(option => !assigned.Contains(option.Key)).Select(option => option.Key).ToArray();
        if (missing.Length > 0)
        {
            var index = lanes.FindIndex(lane => lane.Name == "其他");
            if (index >= 0) lanes[index] = lanes[index] with { Skills = [.. lanes[index].Skills, .. missing] };
            else { var id = "其他"; while (lanes.Any(lane => lane.Id == id)) id += "-new"; lanes.Add(new(id, "其他", missing)); }
        }
        return lanes;
    }
    public static EvidenceArray Encode(IEnumerable<TimelineSkillLane> lanes) => new(lanes.Select(lane => (EvidenceValue)SettingsData.Make(("id", lane.Id), ("name", lane.Name), ("skills", lane.Skills))).ToArray());
}
