using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Runtime.History;

public sealed record BuffTrackKey(string Event, string SourceCharacter, string SourceActor, string TargetCharacter, string TargetActor);
public sealed record BuffDisplayState(double Start, double End, BigInteger? Stacks, double Expiry, bool Boundary);
public sealed record BuffEpisode(BuffTrackKey Key, double Start, double End, IReadOnlyList<BuffDisplayState> States, IReadOnlyList<EvidenceObject> Evidence);

/// <summary>Collapses report windows for display; does not infer combat effects or ownership.</summary>
public static partial class BuffDisplay
{
    private sealed record Window(double Start, double End, string Identity, EvidenceObject Evidence);
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : [];
    private static string Text(EvidenceValue value) => SettingsData.Truth(value) ? PythonDisplay.String(value) : "";
    private static double Number(EvidenceValue value) => value is EvidenceBoolean flag ? flag.Value ? 1 : 0 : SettingsData.Number(value, 0);
    private static BuffTrackKey Key(EvidenceObject row) => new(Text(row.Get("event_key")), Text(row.Get("source_character_key")), Text(row.Get("source_actor_id")), Text(row.Get("target_character_key")), Text(row.Get("target_actor_id")));
    public static IReadOnlyList<BuffEpisode> Build(IEnumerable<EvidenceObject> events)
    {
        List<BuffEpisode> result = [];
        foreach (var group in events.GroupBy(Key))
        {
            var rows = group.OrderBy(row => Number(row.Get("ts_ms_from_start"))).ToArray();
            Dictionary<string, string> roots = new(StringComparer.Ordinal);
            string Find(string uid)
            {
                roots.TryAdd(uid, uid); var root = uid;
                while (roots[root] != root) root = roots[root];
                while (roots[uid] != uid) { var next = roots[uid]; roots[uid] = root; uid = next; }
                return root;
            }
            foreach (var row in rows)
            {
                var aliases = row.Get("buff_uid_aliases") is EvidenceArray array ? array.Items : [];
                var ids = new[] { row.Get("buff_uid") }.Concat(aliases).Where(value => value is not EvidenceNull).Select(PythonDisplay.String).ToArray();
                foreach (var uid in ids.Skip(1)) roots[Find(uid)] = Find(ids[0]);
            }
            var windows = rows.Select((row, index) =>
            {
                var start = Number(row.Get("ts_ms_from_start")); var uid = row.Get("buff_uid");
                return new Window(start, start + Math.Max(0, Number(row.Get("duration_ms"))), uid is EvidenceNull or EvidenceText { Value.Length: 0 } ? $"unknown:{index}" : Find(PythonDisplay.String(uid)), row);
            }).ToArray();
            var stacking = rows.All(row => Text(row.Get("stacking_type")) == "Stack");
            var replace = rows.All(row => Text(row.Get("stacking_type")) is "Refresh" or "Unique" or "EnhanceAndRefresh");
            SortedSet<double> cuts = new(windows.SelectMany(window => new[] { window.Start, window.End }));
            var first = cuts.Min; var final = cuts.Max;
            foreach (var observation in rows.SelectMany(row => Rows(row.Get("buff_enable_observations"))))
            { var stamp = Number(observation.Get("at_ms")); if (first <= stamp && stamp <= final) cuts.Add(stamp); }
            bool Enabled(Window window, double stamp)
            {
                var observation = Rows(window.Evidence.Get("buff_enable_observations")).Where(row => Number(row.Get("at_ms")) <= stamp)
                    .OrderByDescending(row => Number(row.Get("at_ms"))).ThenByDescending(row => Number(row.Get("line_no"))).FirstOrDefault();
                return observation is null || SettingsData.Truth(observation.Get("enabled"));
            }
            List<BuffDisplayState> segments = []; var edges = cuts.ToArray();
            for (var index = 0; index + 1 < edges.Length; index++)
            {
                var start = edges[index]; var end = edges[index + 1];
                var active = windows.Where(window => window.Start <= start && start < window.End && Enabled(window, start)).ToArray();
                if (replace && active.Length > 0)
                { var latest = windows.Where(window => window.Start <= start).Max(window => window.Start); active = active.Where(window => window.Start == latest).ToArray(); }
                if (active.Length == 0) continue;
                var identities = active.Select(window => window.Identity).Distinct(StringComparer.Ordinal).ToArray();
                var known = identities.All(uid => !uid.StartsWith("unknown:", StringComparison.Ordinal));
                BigInteger? layers = stacking && known ? identities.Length : replace || identities.Length == 1 ? BigInteger.One : null;
                var limits = active.Select(window => window.Evidence.Get("stack_limit")).Where(SettingsData.Truth).Select(value => SettingsData.Integer(value, allowBoolean: true)).OfType<BigInteger>().ToArray();
                if (layers is { } count && limits.Length > 0) layers = BigInteger.Min(count, limits.Min());
                var expiryValues = active.Select(window => (window.Evidence.Get("buff_lifetime") as EvidenceObject)?.Get("expiry_ms_from_start") ?? EvidenceNull.Value).ToArray();
                var expiryKnown = expiryValues.All(value => value is not EvidenceNull);
                var legacy = active.All(window => !window.Evidence.Fields.ContainsKey("buff_lifetime"));
                var expiry = expiryKnown ? expiryValues.Max(Number) : active.Max(window => window.Evidence.Fields.TryGetValue("actual_end_ms_from_start", out var actual) ? Number(actual) : window.End);
                var boundary = !expiryKnown && !legacy || active.Any(window => SettingsData.Truth(window.Evidence.Get("end_is_observation_boundary")));
                BuffDisplayState state = new(start, end, layers, expiry, boundary);
                if (segments.Count > 0 && segments[^1] is var previous && previous.End == start && previous.Stacks == layers && previous.Expiry == expiry && previous.Boundary == boundary)
                    segments[^1] = previous with { End = end };
                else segments.Add(state);
            }
            List<BuffDisplayState> episode = [];
            void Finish()
            {
                if (episode.Count == 0) return;
                var start = episode[0].Start; var end = episode[^1].End;
                result.Add(new(group.Key, start, end, episode.ToArray(), windows.Where(window => window.Start < end && window.End > start).Select(window => window.Evidence).ToArray()));
                episode.Clear();
            }
            foreach (var state in segments) { if (episode.Count > 0 && episode[^1].End < state.Start) Finish(); episode.Add(state); }
            Finish();
        }
        return result;
    }
    public static string StateText(IReadOnlyList<BuffDisplayState> states, double? at = null)
    {
        if (states.Count == 0) return "";
        if (at is null)
        {
            var count = states.All(state => state.Stacks is not null) ? $"峰值 {states.Max(state => state.Stacks)} 层" : "层数未知";
            var final = states[^1]; return $"{count} · {(final.Boundary ? "观测至" : "结束于")} {(final.Expiry / 1000).ToString("F2", CultureInfo.InvariantCulture)}s";
        }
        var current = states.FirstOrDefault(state => state.Start <= at && at < state.End); if (current is null) return "未生效";
        var layers = current.Stacks is { } stacks ? $"{stacks} 层" : "层数未知";
        return layers + " · " + (current.Boundary ? "持续时间未知" : $"剩余 {(Math.Max(0, current.Expiry - at.Value) / 1000).ToString("F2", CultureInfo.InvariantCulture)}s");
    }
    [GeneratedRegex(@"\A[A-Za-z0-9_./-]+\z")] private static partial Regex CodeName();
    private static string Human(EvidenceValue value, string key = "")
    {
        var text = PythonDisplay.Strip(Text(value)); var bare = key.StartsWith("buff_", StringComparison.Ordinal) ? key[5..] : key;
        return text.Length == 0 || text.Contains('\ufffd') || text == key || text == bare || text.Contains('_') && CodeName().IsMatch(text) ? "" : text;
    }
    public static IReadOnlyDictionary<string, string> Names(ResourceFiles? resources)
    {
        Dictionary<string, string> names = new(StringComparer.Ordinal);
        if (resources?.ReadBytes(resources.PathFor("data/akedata/buff/manifest.json")) is not EvidenceArray rows) return names;
        foreach (var row in rows.Items.OfType<EvidenceObject>())
        { var key = Text(row.Get("id")); var name = Human(row.Get("name"), key); if (name.Length > 0) names[key] = name; }
        return names;
    }
    public static string Source(EvidenceObject row)
    {
        var key = Text(row.Get("source_character_key")); var fallback = Text(row.Get("source_character_name"));
        var owner = key.Length > 0 || fallback.Length > 0 ? TimelineSkills.CharacterName(key, fallback) : "";
        var skill = Text(row.Get("source_skill_key")); var label = skill.Length > 0 ? TimelineSkills.Label(skill).Name : ""; if (label == skill) label = "";
        var parts = new[] { owner, label, Human(row.Get("source_weapon_name")) }.Where(part => part.Length > 0).Distinct(StringComparer.Ordinal).ToArray();
        return parts.Length > 0 ? string.Join(" · ", parts) : "未知来源";
    }
    private static readonly HashSet<string> EffectLabels = new(["增伤", "独立增伤", "攻击提升", "攻击力提升", "暴击", "暴击率", "暴击伤害", "易伤", "脆弱", "减抗", "减防", "防御降低", "抗性降低", "连击增伤", "技能增伤", "受伤增加", "物理增伤", "法术增伤", "增幅", "承伤易伤", "物理脆弱", "碎甲", "加速", "缓速"], StringComparer.Ordinal);
    public static string Name(EvidenceObject row, IReadOnlyDictionary<string, string>? names = null)
    {
        var key = Text(row.Get("event_key"));
        foreach (var field in new[] { "buff_display_name", "buff_name" }) if (Human(row.Get(field), key) is { Length: > 0 } display) return display;
        if (names?.TryGetValue(key, out var manifest) == true) return manifest;
        var name = Human(row.Get("event_name"), key); var parts = name.Split('/').Select(PythonDisplay.Strip).Where(part => part.Length > 0).ToArray();
        if (parts.Length > 0 && !parts.All(EffectLabels.Contains)) return name;
        return Source(row) + (name.Length > 0 ? " · " + name : "");
    }
}
