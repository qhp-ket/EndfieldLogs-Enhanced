using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class HitObservationCases
{
    private static EvidenceObject Hit(DamageHit hit)=>HitReportEvidence.Project(hit);

    internal static object Project(HitObservationState state, PacketObservationState packets, BuffInstanceState? buffs = null)
    {
        Dictionary<string, object?> result = new()
        {
        ["hits"] = state.Hits.Select(Hit).ToArray(),
        ["unresolved"] = state.Unresolved.Select(hit => new Dictionary<string, object?>
        {
            ["line_no"] = hit.LineNumber, ["ts_ms"] = hit.TimestampMs, ["source_actor"] = hit.SourceActor,
            ["attacker_actor"] = hit.AttackerActor, ["target_actor"] = hit.TargetActor, ["raw_skill_key"] = hit.RawSkill,
            ["packet_hit_value"] = hit.PacketHit, ["reason"] = hit.Reason,
        }).ToArray(),
        ["indices"] = state.HitsBySequence.ToDictionary(pair => pair.Key, pair => state.Hits.IndexOf(pair.Value)),
        ["enemies"] = state.EnemyCounts, ["hp"] = state.LastEnemyHp, ["roster"] = state.Roster,
        ["participants"] = state.Participants.ToDictionary(pair => pair.Key, pair => new Dictionary<string, object?>
        {
            ["character_key"] = pair.Value.Character, ["character_name"] = pair.Value.Name,
            ["total_damage"] = pair.Value.Damage, ["max_hit"] = pair.Value.Maximum,
            ["crit_hits"] = pair.Value.CriticalHits, ["hit_count"] = pair.Value.Count,
        }),
        ["skills"] = state.Skills.Values.Select(skill => new Dictionary<string, object?>
        {
            ["character_key"] = skill.Character, ["character_name"] = skill.CharacterName,
            ["skill_key"] = skill.Skill, ["skill_name"] = skill.Name, ["total_damage"] = skill.Damage,
            ["max_damage"] = skill.Maximum, ["hit_count"] = skill.Count, ["cast_count"] = skill.CastCount,
        }).ToArray(),
        ["baselines"] = packets.BaselinesByCharacter, ["modifier_last_seen"] = packets.ModifierLastSeenByUid,
        ["loadouts"] = state.Loadouts, ["suits"] = state.ActiveSuits.ToDictionary(pair => pair.Key, pair => pair.Value.Order(StringComparer.Ordinal).ToArray()),
            ["weapons"] = state.ActiveWeapons,
        };
        if (buffs is not null)
        {
            int? Index(BuffRecord? record) => record is null ? null : buffs.Records.IndexOf(record) is var index && index >= 0 ? index : null;
            result["buffs"] = new Dictionary<string, object?>
            {
                ["records"] = buffs.Records.Select(BuffInstanceCases.RecordFields).ToArray(),
                ["active"] = buffs.ActiveByUid.ToDictionary(pair => pair.Key, pair => Index(pair.Value)),
                ["pending"] = Index(buffs.PendingRecord),
                ["pending_modifiers"] = buffs.PendingModifiers.ToDictionary(pair => pair.Key, pair => pair.Value.Select(row => new Dictionary<string, object?>
                {
                    ["attr_type"] = row.AttributeType, ["bb_key"] = row.BlackboardKey, ["use_key"] = row.UseKey, ["value"] = row.Value,
                }).ToArray()),
                ["unresolved"] = buffs.UnresolvedActions.Select(row => row.Evidence).ToArray(),
            };
        }
        return result;
    }

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config"]!.ToJsonString());
            static Dictionary<string, string> TextMap(EvidenceValue value) => value is EvidenceObject obj
                ? obj.Fields.ToDictionary(pair => pair.Key, pair => ((EvidenceText)pair.Value).Value, StringComparer.Ordinal) : [];
            var names = TextMap(config.Get("names"));
            var profiles = config.Get("identity_profiles") is EvidenceObject identityProfiles ? identityProfiles.Fields.ToDictionary(pair => pair.Key,
                pair => new RuntimeBuffDamageProfile(((EvidenceObject)((EvidenceObject)pair.Value).Get("actions")).Fields.ToDictionary(action => action.Key,
                    action => (IReadOnlyList<DamageUnitIdentity>)((EvidenceArray)action.Value).Items.Cast<EvidenceObject>().Select(unit => new DamageUnitIdentity(
                        (unit.Get("damageAttribute") as EvidenceText)?.Value, (unit.Get("element") as EvidenceText)?.Value,
                        (unit.Get("index") as EvidenceInteger)?.Value)).ToArray()))) : [];
            SkillIdentityCatalog identities = new(TextMap(config.Get("skills")), TextMap(config.Get("buffs")), profiles);
            var definitions = config.Get("units") as EvidenceObject;
            IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> Units(string key)
            {
                var canonical = identities.CanonicalPacketSkill(key);
                if (definitions?.Get(canonical) is not EvidenceObject actions) return new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>();
                return actions.Fields.ToDictionary(pair => TraceFields.OptionalInteger(pair.Key)!.Value,
                    pair => (IReadOnlyList<SkillDamageUnit>)((EvidenceArray)pair.Value).Items.Cast<EvidenceObject>().Select(unit => new SkillDamageUnit(
                        unit.Get("index"), (unit.Get("element") as EvidenceText)?.Value ?? "",
                        (unit.Get("damage_attribute_type") as EvidenceText)?.Value ?? "",
                        (unit.Get("damage_decorate_mask") as EvidenceInteger)?.Value, (unit.Get("damage_decorate_mask_source") as EvidenceText)?.Value,
                        unit.Get("damage_calculation") as EvidenceObject)).ToArray());
            }
            SkillHitProfile? Profile(string key)
            {
                if ((config.Get("profiles") as EvidenceObject)?.Get(key) is not EvidenceObject profile) return null;
                return new((profile.Get("group_type") as EvidenceInteger)?.Value, (profile.Get("family_skill_key") as EvidenceText)?.Value);
            }
            EntityObservationState entities = new();
            PacketObservationState packets = new();
            HitObservationState state = new(identities, Units, Profile, key => names.GetValueOrDefault(key),
                key => names.GetValueOrDefault(key), key => names.GetValueOrDefault(key), entities, packets);
            if (config.Get("loadouts") is EvidenceObject loadouts)
                foreach (var (key, item) in loadouts.Fields) state.Loadouts[key] = (EvidenceObject)item;
            if (config.Get("suits") is EvidenceObject suits)
                foreach (var (key, item) in suits.Fields) state.ActiveSuits[key] = ((EvidenceArray)item).Items.Cast<EvidenceText>().Select(text => text.Value).ToHashSet(StringComparer.Ordinal);
            foreach (var (key, item) in TextMap(config.Get("weapons"))) state.ActiveWeapons[key] = item;
            BuffInstanceState? buffs = null;
            BuffPacketObservations? buffPackets = null;
            HitBuffLifecycleObservations? lifecycle = null;
            if (config.Get("mixed") is EvidenceBoolean { Value: true })
            {
                static Dictionary<string, EvidenceObject> Objects(EvidenceValue value) => value is EvidenceObject obj
                    ? obj.Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value) : [];
                var numbers = TextMap(config.Get("buffs"));
                buffs = new(new PacketBuffCatalog(Objects(config.Get("numeric")), new Dictionary<string, IReadOnlyList<EvidenceObject>>(), numbers),
                    Objects(config.Get("roots")), numbers, key => key is null ? null : names.GetValueOrDefault(key),
                    key => key is null ? null : names.GetValueOrDefault(key), state.Party);
                buffPackets = new(buffs);
                lifecycle = new(state, buffs);
            }
            JsonArray steps = [];
            foreach (var operation in test["operations"]!.AsArray())
            {
                var line = operation!["line"]!.GetValue<string>();
                var number = operation["number"]!.GetValue<int>();
                var time = operation["time"]!.GetValue<long>();
                var handled = entities.Observe(line, number, time) || buffPackets?.Observe(line, number, time) == true
                    || buffs?.ObserveBlackboard(line) == true || packets.Observe(line, number, time)
                    || (lifecycle is null ? state.Observe(line, number, time) : lifecycle.Observe(line, number, time));
                if (state.Hits.Any(hit => !ReferenceEquals(hit.Packet, packets.HitsBySequence.GetValueOrDefault(hit.Identity.Sequence))
                    && ReferenceEquals(state.HitsBySequence[hit.Identity.Sequence], hit)))
                    throw new InvalidOperationException("Packet evidence does not belong to the indexed hit");
                steps.Add(FieldCases.Canonical(new Dictionary<string, object?> { ["handled"] = handled, ["state"] = Project(state, packets, buffs) }));
            }
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = steps,
                ["passed"] = JsonNode.DeepEquals(steps, test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Hit observation differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
