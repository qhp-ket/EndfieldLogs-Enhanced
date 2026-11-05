using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class BattlePresentationSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var rules = (EvidenceObject)EvidenceJson.Parse("""{"skills":{"skill":{"duration_frames":60}}}""");
        var hit = (EvidenceObject)EvidenceJson.Parse("""{"event_type":"damage","event_key":"skill","ts_ms_from_start":100}""");
        TimelineSkill skill = new("a", 0, 5, "test", "战技", "skill", null, [hit]);
        var reference = SkillFrameReference.For(skill, rules)!;
        check(BattleEvidence.Number(reference.Get("anchor_ms")) == 100 && BattleEvidence.Number(reference.Get("end_ms")) == 2100 && skill.Start == 0 && skill.End == 5, "Fallback is first-hit plus configured frames and preserves canonical interval");
        check(SkillFrameReference.For(skill with { Cast = (EvidenceObject)EvidenceJson.Parse("""{"skill_key":"skill","ts_ms_from_start":0,"end_ms_from_start":0}""") }, rules) is null, "Complete zero-length lifecycle remains authoritative");
        check(SkillFrameReference.For(skill with { Events = [new EvidenceObject(hit.Fields.ToDictionary(pair => pair.Key, pair => pair.Key == "event_key" ? (EvidenceValue)new EvidenceText("skill_proj") : pair.Value))] }, rules) is null, "Projectile keys never inherit a parent's frame rule");
        var noHit = SkillFrameReference.For(skill with { Events = [(EvidenceObject)EvidenceJson.Parse("""{"event_key":"skill","event_type":"cast"}""")] }, rules)!;
        check(noHit.Get("anchor_ms") is EvidenceNull && noHit.Get("end_ms") is EvidenceNull, "No hit never invents a drawn interval");
        var report = (EvidenceObject)EvidenceJson.Parse("""{"participants":[{"character_key":"a","total_damage":200}],"role_skill_stats":[{"character_key":"a","skill_key":"unknown","skill_name":"记录技能","cast_count":3,"total_damage":50,"avg_damage":16.5,"max_damage":30}]}""");
        var before = PythonSortedJson.Serialize(report); var row = SkillComposition.Build(report).Single();
        check(BattleEvidence.Number(row.Get("damage_percent")) == 25 && BattleEvidence.Number(row.Get("cast_count")) == 3 && BattleEvidence.Number(row.Get("avg_damage")) == 16.5, "Composition uses participant damage denominator and keeps supplied cast statistics");
        check(SkillComposition.Build(report, "b").Count == 0 && before == PythonSortedJson.Serialize(report), "Composition filter is read-only");
        var temporary = Directory.CreateTempSubdirectory("endfield-frame-rules-");
        try
        {
            ResourceFiles resources = new(temporary.FullName); check(((EvidenceObject)SkillFrameReference.Rules(resources).Get("skills")).Fields.Count == 0, "Missing optional frame resource has no fallback");
            var path = resources.PathFor("data/local_semantics/skill_frame_rules.json"); Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.WriteAllText(path, "{\"schema_version\":2,\"frames_per_second\":30}");
            var rejected = false; try { SkillFrameReference.Rules(resources); } catch (InvalidDataException) { rejected = true; }
            check(rejected, "Unsupported frame schema is reported");
        }
        finally { temporary.Delete(true); }
    }
}
