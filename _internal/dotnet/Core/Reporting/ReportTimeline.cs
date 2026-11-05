using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record ReportTimelineProjection(IReadOnlyList<ReportHitInput> Hits, IReadOnlyList<EvidenceObject> Events,
    IReadOnlyList<EvidenceObject> RoleSkillStats, IReadOnlyList<EvidenceObject> Casts, IReadOnlyList<EvidenceObject> AtbEvents,
    IReadOnlyList<EvidenceObject>? Windows = null);

/// <summary>Presentation coordinates, observed casts and skill groups; never changes damage or evidence timestamps.</summary>
public sealed class ReportTimeline(SkillIdentityCatalog identities, Func<string, string?> characterName,
    Func<string, string?> skillName, Func<string, string?> family, IReadOnlyDictionary<string, EvidenceObject> buffRoots)
{
    private static readonly Regex CastChild = new(@"(?:projhit|abilityrange|indicator|blocked|_bomb|_field|_sheep)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex ExportNoise = new(@"(_projhit|_abilityrange|_abilityentity|_absorb|_indicator|_blocked|_listener|_aura|_marker)");
    private static readonly Regex Numeric = new(@"\A.*_skill_\d+\z");
    private static readonly Regex Family = new(@"\A(.*?_(?:ultimate_skill|normal_skill|combo_skill))");
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static BigInteger Int(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static IReadOnlyList<EvidenceValue> Items(EvidenceValue value) => (value as EvidenceArray)?.Items ?? [];
    private static EvidenceValue Copy(EvidenceValue value) => BuffEvidence.Clone(value);
    private static Dictionary<string, EvidenceValue> Fields(EvidenceObject row) => (Dictionary<string, EvidenceValue>)row.Fields;
    private static EvidenceObject Obj(IEnumerable<(string Key, EvidenceValue Value)> fields) => new(fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));
    private static string EventKey(EvidenceObject hit) => Text(CatalogValues.Or(hit.Get("skill_family_key"), hit.Get("skill_key")));
    private string CharacterName(string key) => characterName(key) is { Length: > 0 } name ? name : key;
    private string SkillName(string key) => skillName(key) is { Length: > 0 } name ? name : key;
    private static EvidenceObject EmptySides() => BuffEvidence.Object(("attacker", new EvidenceArray([])), ("defender", new EvidenceArray([])));

    public static ReportTimeline Load(ResourceFiles files)
    {
        var ids = new SkillResourceCatalog(files).CreateIdentityCatalog();
        CharacterResourceCatalog characters = new(files);
        DisplayNameCatalog names = new(files, characters, ids);
        SkillProfileCatalog profiles = new(files, characters, ids);
        return new(ids, names.Character, names.Skill, key => profiles.ForHit(key)?.Family, new BuffRootCatalog(files).Roots);
    }

    public static IReadOnlyList<ReportHitInput> AssignGroups(IReadOnlyList<ReportHitInput> source)
        => AssignGroupsCore(source, ownsHits: false);

    internal static IReadOnlyList<ReportHitInput> AssignGroupsOwned(IReadOnlyList<ReportHitInput> source)
        => AssignGroupsCore(source, ownsHits: true);

    private static IReadOnlyList<ReportHitInput> AssignGroupsCore(IReadOnlyList<ReportHitInput> source, bool ownsHits)
    {
        var hits = ownsHits ? source.ToArray() : source.Select(hit => hit with { Evidence = (EvidenceObject)Copy(hit.Evidence) }).ToArray();
        Dictionary<(string Character, string Skill, string Target), (BigInteger Last, int Index)> groups = [];
        foreach (var hit in hits.OrderBy(hit => Int(hit.Evidence.Get("ts_ms"))))
        {
            var row = hit.Evidence;
            var skill = EventKey(row);
            if (skill.Length == 0) { Fields(row)["timeline_group_key"] = EvidenceNull.Value; continue; }
            var target = Text(row.Get("target_enemy_key"));
            var key = (Text(row.Get("character_key")), skill, target);
            var time = Int(row.Get("ts_ms"));
            var lowerSkill = Text(row.Get("skill_key")).ToLowerInvariant();
            var gap = Text(row.Get("skill_family_key")).ToLowerInvariant().Contains("_ultimate_skill", StringComparison.Ordinal)
                || lowerSkill.Contains("_ultimate_skill", StringComparison.Ordinal) || lowerSkill.Contains("_ult_attack", StringComparison.Ordinal) ? 5000 : 1200;
            var index = groups.TryGetValue(key, out var previous) ? previous.Index + (time - previous.Last > gap ? 1 : 0) : 1;
            groups[key] = (time, index);
            Fields(row)["timeline_group_key"] = new EvidenceText($"{skill}::{(target.Length == 0 ? "unknown-target" : target)}::{index}");
        }
        return hits;
    }

    public IReadOnlyList<EvidenceObject> SkillStats(IReadOnlyList<ReportHitInput> hits, IReadOnlyList<string> roster)
    {
        Dictionary<(string Character, string Skill, string Cast), EvidenceObject> casts = [];
        for (var index = 0; index < hits.Count; index++)
        {
            var hit = hits[index].Evidence;
            var character = Text(hit.Get("character_key"));
            if (character.Length == 0) continue;
            var skill = EventKey(hit);
            if (skill.Length == 0) skill = "unknown_skill";
            var castKey = CatalogValues.Truth(hit.Get("timeline_group_key")) ? Text(hit.Get("timeline_group_key")) : $"{skill}::hit-{index}";
            var key = (character, skill, castKey);
            if (!casts.TryGetValue(key, out var cast)) casts[key] = cast = BuffEvidence.Object(("total_damage", new EvidenceInteger(0)));
            Fields(cast)["character_name"] = new EvidenceText(CatalogValues.Truth(hit.Get("character_name")) ? Text(hit.Get("character_name")) : CharacterName(character));
            Fields(cast)["skill_name"] = new EvidenceText(CatalogValues.Truth(hit.Get("skill_name")) ? Text(hit.Get("skill_name")) : SkillName(skill));
            Fields(cast)["total_damage"] = new EvidenceInteger(Int(cast.Get("total_damage")) + Int(hit.Get("hit_value")));
        }
        Dictionary<(string Character, string Skill), EvidenceObject> skills = [];
        foreach (var (key, cast) in casts)
        {
            var skillKey = (key.Character, key.Skill);
            if (!skills.TryGetValue(skillKey, out var skill)) skills[skillKey] = skill = BuffEvidence.Object(
                ("character_key", new EvidenceText(key.Character)), ("skill_key", new EvidenceText(key.Skill)),
                ("total_damage", new EvidenceInteger(0)), ("max_damage", new EvidenceInteger(0)), ("cast_count", new EvidenceInteger(0)));
            var damage = Int(cast.Get("total_damage"));
            Fields(skill)["character_name"] = Copy(cast.Get("character_name"));
            Fields(skill)["skill_name"] = Copy(cast.Get("skill_name"));
            Fields(skill)["total_damage"] = new EvidenceInteger(Int(skill.Get("total_damage")) + damage);
            Fields(skill)["max_damage"] = new EvidenceInteger(BigInteger.Max(Int(skill.Get("max_damage")), damage));
            Fields(skill)["cast_count"] = new EvidenceInteger(Int(skill.Get("cast_count")) + 1);
        }
        List<EvidenceObject> result = [];
        foreach (var character in roster)
            foreach (var skill in skills.Where(pair => pair.Key.Character == character).Select(pair => pair.Value)
                         .OrderByDescending(row => Int(row.Get("total_damage"))).ThenBy(row => Text(row.Get("skill_key")), PythonDisplay.CodePointComparer))
            {
                Fields(skill)["avg_damage"] = new EvidenceReal(PythonDecimalRounding.Round(PythonIntegerDivision.Divide(Int(skill.Get("total_damage")),
                    BigInteger.Max(Int(skill.Get("cast_count")), 1)), 2));
                result.Add(skill);
            }
        return result;
    }

    private string CastFamily(EvidenceObject cast)
    {
        var skill = Text(cast.Get("skill"));
        if (skill.Length == 0 || Text(cast.Get("skill_source")).ToLowerInvariant() == "summon" || CastChild.IsMatch(skill)) return "";
        skill = identities.CanonicalPacketSkill(skill);
        if (ActorIdentity.IsGenericRuntimeSkill(skill) || Numeric.IsMatch(skill)) skill = identities.CanonicalSkill(skill, Text(cast.Get("source_character_key"))) ?? skill;
        return identities.FamilyKey(skill, family(skill));
    }

    public ReportTimelineProjection Build(IReadOnlyList<ReportHitInput> source, ReportSourceInput sources, ReportLifecycleResult lifecycle,
        IReadOnlyList<EvidenceObject> participants, IReadOnlyList<string> roster, IReadOnlyList<EvidenceObject> windows, IReadOnlyList<EvidenceObject> records)
        => BuildCore(source, sources, lifecycle, participants, roster, windows, records, ownsHits: false);

    internal ReportTimelineProjection BuildOwned(IReadOnlyList<ReportHitInput> source, ReportSourceInput sources, ReportLifecycleResult lifecycle,
        IReadOnlyList<EvidenceObject> participants, IReadOnlyList<string> roster, IReadOnlyList<EvidenceObject> windows, IReadOnlyList<EvidenceObject> records)
        => BuildCore(source, sources, lifecycle, participants, roster, windows, records, ownsHits: true);

    private ReportTimelineProjection BuildCore(IReadOnlyList<ReportHitInput> source, ReportSourceInput sources, ReportLifecycleResult lifecycle,
        IReadOnlyList<EvidenceObject> participants, IReadOnlyList<string> roster, IReadOnlyList<EvidenceObject> windows, IReadOnlyList<EvidenceObject> records, bool ownsHits)
    {
        if (lifecycle.Window is not { } window) return new([], [], [], [], []);
        // Private calculation values are read only during projection. Its final export
        // detaches shared descendants; public projection retains independent copies here.
        EvidenceValue Copy(EvidenceValue value) => ownsHits ? value : ReportTimeline.Copy(value);
        var hits = ownsHits ? AssignGroupsOwned(source) : AssignGroups(source);
        var castIndex = sources.Casts.Select(cast => (Cast: cast, Character: Text(cast.Get("source_character_key")), Family: CastFamily(cast)))
            .Where(row => row.Character.Length > 0 && row.Family.Length > 0).GroupBy(row => (row.Character, row.Family))
            .ToDictionary(group => group.Key, group => group.Select(row => row.Cast).OrderBy(cast => Int(cast.Get("ts_ms"))).ToArray());
        List<EvidenceObject> events = [];
        EvidenceValue Offset(BigInteger? time, bool clamp = false) => time is { } value ? new EvidenceInteger(lifecycle.OffsetMs(value, clamp)) : EvidenceNull.Value;
        foreach (var input in hits)
        {
            var hit = input.Evidence;
            var time = Int(hit.Get("ts_ms"));
            var candidates = castIndex.GetValueOrDefault((Text(hit.Get("character_key")), EventKey(hit).ToLowerInvariant())) ?? [];
            // The newest cast within [-50, 12000]ms wins, independent of its recorded end.
            var lo = 0; var hi = candidates.Length;
            while (lo < hi) { var mid = (lo + hi) / 2; if (Int(candidates[mid].Get("ts_ms")) <= time + 50) lo = mid + 1; else hi = mid; }
            var cast = lo > 0 && time - Int(candidates[lo - 1].Get("ts_ms")) <= 12000 ? candidates[lo - 1] : null;
            BigInteger? start = cast is null ? null : Int(cast.Get("ts_ms"));
            BigInteger? end = cast?.Get("end_ts_ms") is EvidenceValue endValue && endValue is not EvidenceNull ? Int(endValue) : null;
            var targetFields = new[] { "target_defense", "target_defense_source", "target_resistance_points", "target_resistance_points_source", "target_resistance_scalars",
                "target_resistance_source", "target_stats_snapshot_ts_ms", "target_stats_snapshot_line_no", "target_stats_invalid_attr_types" };
            var contributions = hit.Get("rdps_contributions") as EvidenceObject;
            events.Add(BuffEvidence.Object(
                ("ts_ms_from_start", Offset(time, true)), ("lane_type", new EvidenceText("skill")),
                ("source_character_key", Copy(hit.Get("character_key"))), ("source_character_name", Copy(hit.Get("character_name"))),
                ("target_character_key", Copy(hit.Get("target_enemy_key"))), ("target_character_name", Copy(hit.Get("target_enemy_name"))),
                ("event_type", new EvidenceText("damage")), ("event_key", Copy(CatalogValues.Or(hit.Get("skill_family_key"), hit.Get("skill_key")))), ("event_group_key", Copy(hit.Get("timeline_group_key"))),
                ("event_name", Copy(hit.Get("skill_name"))), ("value", Copy(hit.Get("hit_value"))),
                ("damage_element", Copy(hit.Get("damage_element"))), ("damage_school", Copy(hit.Get("damage_school"))),
                ("value_source", Copy(hit.Get("damage_value_source"))), ("packet_hit_value", Copy(hit.Get("packet_hit_value"))),
                ("packet_raw_value", Copy(hit.Get("packet_raw_value"))), ("packet_final_value", Copy(hit.Get("packet_final_value"))),
                ("overkill_damage", Copy(hit.Get("overkill_damage"))), ("rdps_basis_value", Copy(hit.Get("rdps_basis_value"))), ("rdps_basis_source", Copy(hit.Get("rdps_basis_source"))),
                ("rdps_contributions", new EvidenceArray(contributions?.Fields.OrderBy(pair => pair.Key, PythonDisplay.CodePointComparer).Select(pair =>
                    (EvidenceValue)BuffEvidence.Object(("character_key", new EvidenceText(pair.Key)), ("character_name", new EvidenceText(CharacterName(pair.Key))),
                        ("value", new EvidenceReal(PythonDecimalRounding.Round(pair.Value is EvidenceReal number ? number.Value : (double)Int(pair.Value), 4))))).ToArray() ?? [])),
                ("packet_modifier_uids", Copy(CatalogValues.Or(hit.Get("packet_modifier_uids"), EmptySides()))),
                ("packet_attr_details", Copy(CatalogValues.Or(hit.Get("packet_attr_details"), EmptySides()))), ("packet_attr_conflict", new EvidenceBoolean(CatalogValues.Truth(hit.Get("packet_attr_conflict")))),
                ("target_actor_id", Copy(hit.Get("target_actor_id"))), ("target_entity", new EvidenceObject(targetFields.Where(hit.Fields.ContainsKey).ToDictionary(key => key, key => Copy(hit.Get(key)), StringComparer.Ordinal))),
                ("poise_damage", Copy(hit.Get("poise_damage"))), ("hit_context", BuffEvidence.Object(("critical", Copy(hit.Get("critical_context"))))),
                ("duration_ms", EvidenceNull.Value), ("actual_start_ms_from_start", Offset(start)), ("actual_end_ms_from_start", Offset(end)),
                ("actual_duration_ms", start is { } s && end is { } e ? new EvidenceInteger(BigInteger.Max(e - s, 1)) : EvidenceNull.Value), ("important", new EvidenceBoolean(true))));
        }
        var participantKeys = participants.Select(row => Text(row.Get("character_key"))).ToHashSet(StringComparer.Ordinal);
        var damaging = hits.SelectMany(hit => new[] { hit.Evidence.Get("skill_family_key"), hit.Evidence.Get("skill_key") }
            .Where(CatalogValues.Truth).Select(key => (Text(hit.Evidence.Get("character_key")), Text(key)))).ToHashSet();
        Dictionary<(string, string), BigInteger> lastEmitted = [];
        List<EvidenceObject> exported = [];
        Dictionary<string, List<(BigInteger Time, int Index)>> castStarts = new(StringComparer.Ordinal);
        foreach (var cast in sources.Casts.OrderBy(row => Int(row.Get("ts_ms"))))
        {
            var character = Text(cast.Get("source_character_key"));
            var skill = Text(cast.Get("skill"));
            if (character.Length == 0 || !participantKeys.Contains(character) || skill.Length == 0) continue;
            if (ActorIdentity.IsGenericRuntimeSkill(skill) || Numeric.IsMatch(skill))
            {
                var canonical = identities.CanonicalSkill(skill, character);
                if (string.IsNullOrEmpty(canonical)) continue;
                skill = canonical;
            }
            var time = Int(cast.Get("ts_ms"));
            var familyMatch = Family.Match(skill);
            if (familyMatch.Success && time >= window.StartMs && time <= window.EndMs)
            {
                var key = familyMatch.Groups[1].Value;
                var binding = (character, key);
                if (!damaging.Contains(binding) && (!lastEmitted.TryGetValue(binding, out var previous) || time - previous >= 3000))
                {
                    lastEmitted[binding] = time;
                    var fields = new[] { "target_character_key", "target_character_name", "event_group_key", "value", "damage_element", "damage_school", "value_source",
                        "packet_hit_value", "packet_raw_value", "packet_final_value", "overkill_damage", "rdps_basis_value", "rdps_basis_source", "poise_damage", "duration_ms" }
                        .Select(key => (key, (EvidenceValue)EvidenceNull.Value)).ToList();
                    fields.AddRange([("ts_ms_from_start", Offset(time, true)), ("lane_type", new EvidenceText("skill")), ("source_character_key", new EvidenceText(character)),
                        ("source_character_name", new EvidenceText(CharacterName(character))), ("event_type", new EvidenceText("cast")), ("event_key", new EvidenceText(key)),
                        ("event_name", new EvidenceText(SkillName(key))), ("rdps_contributions", new EvidenceArray([])), ("packet_modifier_uids", EmptySides()),
                        ("packet_attr_details", EmptySides()), ("important", new EvidenceBoolean(true))]);
                    events.Add(Obj(fields));
                }
            }
            if (ExportNoise.IsMatch(skill) || time < window.StartMs - 10_000 || time > window.EndMs) continue;
            exported.Add(BuffEvidence.Object(("ts_ms_from_start", Offset(time)), ("end_ms_from_start", cast.Get("end_ts_ms") is EvidenceNull ? EvidenceNull.Value : Offset(Int(cast.Get("end_ts_ms")))),
                ("character_key", new EvidenceText(character)), ("skill_key", new EvidenceText(skill)), ("skill_name", new EvidenceText(SkillName(skill))),
                ("skill_source", Copy(CatalogValues.Or(cast.Get("skill_source"), EvidenceNull.Value))), ("dynamic_bb_events", Copy(CatalogValues.Or(cast.Get("dynamic_bb_events"), new EvidenceArray([])))),
                ("recovers_energy", new EvidenceBoolean(false))));
            if (!castStarts.TryGetValue(character, out var starts)) castStarts[character] = starts = [];
            starts.Add((time, exported.Count - 1));
        }
        foreach (var gain in sources.AtbEvents.Where(row => row.Get("reason") is EvidenceText { Value: "AddValue" }
                     && row.Get("delta") is EvidenceReal delta && delta.Value > 0))
        {
            if (!castStarts.TryGetValue(Text(gain.Get("character_key")), out var starts)) continue;
            var time = Int(gain.Get("ts_ms"));
            var lo = 0; var hi = starts.Count;
            while (lo < hi) { var mid = (lo + hi) / 2; if (starts[mid].Time <= time) lo = mid + 1; else hi = mid; }
            if (lo > 0 && time - starts[lo - 1].Time <= 1500) Fields(exported[starts[lo - 1].Index])["recovers_energy"] = new EvidenceBoolean(true);
        }
        var displayedWindows = AppendBuffs(events, windows, records, lifecycle, ownsHits);
        var ordered = events.OrderBy(row => Int(row.Get("ts_ms_from_start"))).ThenBy(row => Text(row.Get("lane_type")), PythonDisplay.CodePointComparer)
            .ThenBy(row => Text(row.Get("event_name")), PythonDisplay.CodePointComparer).ToArray();
        var atb = sources.AtbEvents.Where(row => Int(row.Get("ts_ms")) >= window.StartMs - 10_000 && Int(row.Get("ts_ms")) <= window.EndMs)
            .Select(row =>
            {
                var fields = row.Fields.Where(pair => pair.Key != "ts_ms").ToDictionary(pair => pair.Key, pair => Copy(pair.Value), StringComparer.Ordinal);
                fields["ts_ms_from_start"] = Offset(Int(row.Get("ts_ms")));
                return new EvidenceObject(fields);
            }).ToArray();
        return new(hits, ordered, SkillStats(hits, roster), exported, atb, displayedWindows);
    }

    private IReadOnlyList<EvidenceObject> AppendBuffs(List<EvidenceObject> events, IReadOnlyList<EvidenceObject> windows, IReadOnlyList<EvidenceObject> records, ReportLifecycleResult lifecycle, bool ownsEvidence)
    {
        EvidenceValue Copy(EvidenceValue value) => ownsEvidence ? value : ReportTimeline.Copy(value);
        var battle = lifecycle.Window!;
        // Evaluation creates a new window root and never changes the input descendants.
        var current = windows.Select(window => ownsEvidence ? window : (EvidenceObject)Copy(window)).ToArray();
        Dictionary<(string Uid, string Event, BigInteger Time), EvidenceObject> observed = [];
        foreach (var row in records) observed[(Text(row.Get("uid")), Text(row.Get("event_key")), Int(row.Get("ts_ms")))] = row;
        for (var index = 0; index < current.Length; index++)
        {
            var window = current[index];
            var start = Int(window.Get("start_ts_ms")); var end = Int(window.Get("end_ts_ms"));
            var visibleStart = BigInteger.Max(start, battle.StartMs); var visibleEnd = BigInteger.Min(end, battle.EndMs);
            if (visibleEnd < visibleStart) continue;
            var evaluated = EffectWindowEvaluation.At(window, new((long)visibleStart));
            current[index] = evaluated.Window;
            observed.TryGetValue((Text(window.Get("uid")), Text(window.Get("event_key")), start), out var record);
            var rawDuration = record?.Get("raw_duration_ms") ?? EvidenceNull.Value;
            BigInteger? expiry = record?.Get("end_ts_ms") is EvidenceValue endValue && endValue is not EvidenceNull ? Int(endValue) : null;
            if (expiry is null && rawDuration is not EvidenceNull && EffectIdentity.CompareKeys(rawDuration, new EvidenceInteger(0)) > 0) expiry = start + Int(rawDuration);
            EvidenceValue Offset(BigInteger value) => new EvidenceInteger(lifecycle.OffsetMs(value, clamp: false));
            var copyKeys = new[] { "source_character_key", "source_character_name", "target_character_key", "target_character_name", "target_player_key", "target_enemy_key",
                "event_key", "event_name", "source_actor_id", "target_actor_id", "stack_limit" };
            var fields = copyKeys.Select(key => (key, Copy(window.Get(key)))).ToList();
            var stacking = CatalogValues.Or(window.Get("stacking_type"), buffRoots.GetValueOrDefault(Text(window.Get("event_key")))?.Get("stackingSettings") is EvidenceObject settings
                ? settings.Get("stackingType") : EvidenceNull.Value);
            fields.AddRange([("ts_ms_from_start", new EvidenceInteger(lifecycle.OffsetMs(visibleStart))), ("lane_type", new EvidenceText("buff")), ("event_type", new EvidenceText("buff")),
                ("buff_uid", Copy(window.Get("uid"))), ("buff_uid_aliases", Copy(CatalogValues.Or(window.Get("uid_aliases"), new EvidenceArray([])))),
                ("buff_enable_observations", new EvidenceArray(Items(window.Get("enable_observations")).Cast<EvidenceObject>().Select(row => (EvidenceValue)BuffEvidence.Object(
                    ("at_ms", Offset(Int(row.Get("ts_ms")))), ("line_no", Copy(row.Get("line_no"))), ("enabled", Copy(row.Get("enabled"))))).ToArray())),
                ("stacking_type", Copy(stacking)), ("snapshot_update", new EvidenceBoolean(CatalogValues.Truth(window.Get("snapshot_update")))),
                ("end_is_observation_boundary", new EvidenceBoolean(CatalogValues.Truth(window.Get("end_is_observation_boundary")))),
                ("buff_lifetime", BuffEvidence.Object(("expiry_ms_from_start", expiry is { } value ? Offset(value) : EvidenceNull.Value), ("raw_duration_ms", Copy(rawDuration)),
                    ("source", new EvidenceText(record?.Get("end_ts_ms") is EvidenceValue explicitEnd && explicitEnd is not EvidenceNull ? "BUFF_END" : expiry is not null ? "duration" : "unknown")))),
                ("value", EvidenceNull.Value), ("rdps_contributions", new EvidenceArray([])),
                ("duration_ms", new EvidenceInteger(BigInteger.Max(lifecycle.OffsetMs(visibleEnd, false) - lifecycle.OffsetMs(visibleStart, false), 1))),
                ("actual_start_ms_from_start", Offset(start)), ("actual_end_ms_from_start", Offset(end)),
                ("actual_duration_ms", new EvidenceInteger(BigInteger.Max(lifecycle.OffsetMs(end, false) - lifecycle.OffsetMs(start, false), 1))),
                ("effects", new EvidenceArray(evaluated.Effects.Select(Copy).ToArray())),
                ("dynamic_effects", Copy(CatalogValues.Or(window.Get("dynamic_effects"), new EvidenceArray([])))), ("important", new EvidenceBoolean(true))]);
            events.Add(Obj(fields));
        }
        return current;
    }
}
