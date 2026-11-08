using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public static class StructuredSkill
{
    public static void Accept(TraceEvent item, int evidenceIndex, SkillObservationState skills, PacketObservationState packets)
    {
        if (item.Type is not ("skill_cast" or "atb" or "poise")) throw new InvalidDataException("Expected skill/resource event");
        foreach (var key in new[] { "owner_id", "skill_inst_id", "attacker_id" })
            if (item.Data.Get(key) is not EvidenceNull && (item.Data.Get(key) is not EvidenceText id || id.Value.Length == 0 || id.Value.Any(unit => unit is < '0' or > '9')))
                throw new InvalidDataException("Instance identities must be decimal strings");
        if (item.Type == "skill_cast" && (item.Data.Get("phase") is not EvidenceText { Value: "start" or "end" } || !item.Data.Fields.ContainsKey("skill_inst_id")))
            throw new InvalidDataException("Expected skill phase and instance");
        foreach (var key in new[] { "owner", "attacker", "skill", "skill_source", "source", "original_source" })
            if (item.Data.Get(key) is not (EvidenceNull or EvidenceText)) throw new InvalidDataException("Expected skill/resource label");
        var data = TraceModel.Data(item);
        string L(string key, string fallback = "unknown") => SkillWire.Label(data, key, fallback);
        var time = item.CapturedAtMs;
        if (item.Type == "skill_cast")
        {
            var instance = SkillWire.IdentityToken(data.Get("skill_inst_id"));
            if (L("phase") == "start")
            {
                var owner = L("owner", "?"); var skill = L("skill", "unknown_skill");
                skills.BeginCast(new(time, evidenceIndex, skill, owner, SkillWire.IdentityToken(data.Get("owner_id")), instance,
                    L("skill_source"), ActorIdentity.CharacterKey(owner, skill)));
            }
            else skills.EndCast(instance, evidenceIndex, time);
        }
        else if (item.Type == "atb")
        {
            var tick = SkillWire.Integer(data.Get("client_tick_ms")) ?? 0;
            skills.Observe(new AtbObservation(time, evidenceIndex, ActorIdentity.CharacterKey(L("owner", "?")),
                SkillWire.IdentityToken(data.Get("owner_id")), SkillWire.ProjectedNumber(data.Get("value")),
                SkillWire.ProjectedNumber(data.Get("delta")), SkillWire.ProjectedNumber(data.Get("recovery_speed")),
                TraceFields.OptionalFloat(tick.ToString(CultureInfo.InvariantCulture)), L("reason"), L("source"), L("original_source")));
        }
        else
        {
            var source = SkillWire.Integer(data.Get("source_int")); var original = SkillWire.Integer(data.Get("original_source_int"));
            var observation = PacketObservationState.PoiseObservation(evidenceIndex, time, L("modify_type"),
                SkillWire.ProjectedNumber(data.Get("value")), SkillWire.ProjectedNumber(data.Get("current_value")),
                L("source"), source is { IsZero: false } ? source : null, L("original_source"), original is { IsZero: false } ? original : null);
            if (observation is not null) packets.PoiseDamage.Add(observation);
        }
    }
}
