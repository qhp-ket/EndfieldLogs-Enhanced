using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class TimelineSkillSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var report = (EvidenceObject)EvidenceJson.Parse("""{"participants":[{"character_key":"a"}],"casts":[{"character_key":"a","skill_key":"unknown_normal_skill","ts_ms_from_start":10,"end_ms_from_start":50}],"timeline_events":[{"event_type":"damage","lane_type":"skill","source_character_key":"a","event_key":"unknown_normal_skill","actual_start_ms_from_start":10,"ts_ms_from_start":20,"value":15},{"event_type":"damage","lane_type":"skill","source_character_key":"a","event_key":"unknown_combo_skill","ts_ms_from_start":100,"value":10},{"event_type":"damage","lane_type":"skill","source_character_key":"a","event_key":"unknown_ultimate_skill","ts_ms_from_start":150,"value":10},{"event_type":"damage","lane_type":"skill","source_character_key":"a","event_key":"unknown_power_attack","ts_ms_from_start":160,"value":10}]}""");
        var before = PythonSortedJson.Serialize(report); var blocks = TimelineSkills.Build(report);
        check(blocks.Count == 4 && blocks[0].Start == 10 && blocks[0].End == 50 && blocks[0].Events.Count == 2, "A matching hit joins its cast without creating another interval");
        var options = TimelineSkills.Options(blocks, "a"); var defaults = TimelineSkills.Resolve(options, "a", null);
        check(defaults.Count == 2 && defaults[0].Name == "战技" && defaults[0].Skills.Count == 1 && defaults[1].Skills.Count == 2, "Default tracks contain battle skill and combined combo/ultimate");
        var explicitEmpty = TimelineSkills.Resolve(options, "a", new EvidenceArray([]));
        check(explicitEmpty.Count == 1 && explicitEmpty[0].Name == "其他" && explicitEmpty[0].Skills.Count == 4, "An explicit empty preference preserves all unassigned evidence in Other");
        var stale = TimelineSkills.Encode([new("kept", "保留", ["absent-skill", options[0].Key]), new("其他", "占位", [])]);
        var resolved = TimelineSkills.Resolve(options, "a", stale);
        check(resolved[0].Skills.Contains("absent-skill") && resolved[^1].Id == "其他-new" && resolved[^1].Skills.Count == 3, "Absent skill preferences survive and fallback IDs avoid collisions");
        check(TimelineSkills.Options(blocks, "absent").Count == 0 && before == PythonSortedJson.Serialize(report), "Role options come only from evidenced blocks and never mutate the report");
    }
}
