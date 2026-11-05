using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Runtime.History;

/// <summary>Optional exact-ID display references; never reconstructs combat or animation time.</summary>
public static class SkillFrameReference
{
    public static EvidenceObject Rules(ResourceFiles? resources)
    {
        if (resources is null || !File.Exists(resources.PathFor("data/local_semantics/skill_frame_rules.json"))) return SettingsData.Make(("skills", new EvidenceObject(new Dictionary<string, EvidenceValue>())));
        var rules = resources.ReadRelative("data/local_semantics/skill_frame_rules.json") as EvidenceObject;
        if (rules is null || BattleEvidence.Number(rules.Get("schema_version")) != 1 || BattleEvidence.Number(rules.Get("frames_per_second")) != 30)
            throw new InvalidDataException("不支持的技能帧配置格式");
        return rules;
    }

    public static EvidenceObject? For(TimelineSkill skill, EvidenceObject rules)
    {
        if (skill.Cast is { } cast && BattleEvidence.Number(cast.Get("ts_ms_from_start")) is { } start && BattleEvidence.Number(cast.Get("end_ms_from_start")) is { } end && end >= start) return null;
        if (skill.Events.Any(row => BattleEvidence.Number(row.Get("actual_start_ms_from_start")) == skill.Start && BattleEvidence.Number(row.Get("actual_end_ms_from_start")) == skill.End)) return null;
        var key = skill.Cast?.Get("skill_key") is EvidenceText { Value.Length: > 0 } raw ? raw.Value : skill.Events.FirstOrDefault()?.Get("event_key") is EvidenceText name ? name.Value : "";
        if ((rules.Get("skills") as EvidenceObject)?.Get(key) is not EvidenceObject rule) return null;
        var anchor = skill.Events.Where(row => row.Get("event_type") is EvidenceText { Value: "damage" }).Select(row => BattleEvidence.Number(row.Get("ts_ms_from_start"))).Where(value => value is not null).Min();
        var duration = BattleEvidence.Number(rule.Get("duration_frames"));
        var fields = rule.Fields.ToDictionary(); fields["skill_key"] = new EvidenceText(key);
        fields["anchor_ms"] = anchor is { } at ? new EvidenceReal(at) : EvidenceNull.Value;
        fields["end_ms"] = anchor is { } hit && duration is > 0 ? new EvidenceReal(hit + duration.Value * 1000 / 30) : EvidenceNull.Value;
        return new(fields);
    }
}
