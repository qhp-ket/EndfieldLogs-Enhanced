using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Allocation;

/// <summary>Derive a resistance baseline only when entity stats and observed persistent changes prove it.</summary>
public sealed class AllocationResistance(IReadOnlyDictionary<string, EvidenceObject> roots)
{
    public AllocationResistance(BuffRootCatalog roots) : this(roots.Roots) { }
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static BigInteger Coordinate(EvidenceValue value, BigInteger fallback) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(fallback)));
    private static (BigInteger, BigInteger) Stamp(EvidenceObject row, string time, string line, BigInteger timeFallback = default, BigInteger lineFallback = default) =>
        (Coordinate(row.Get(time), timeFallback), Coordinate(row.Get(line), lineFallback));
    private static IEnumerable<EvidenceObject> Objects(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([]))).Cast<EvidenceObject>();
    private static EvidenceObject Object(EvidenceValue value) => CatalogValues.Or(value, BuffEvidence.Object()) as EvidenceObject ?? throw new InvalidDataException("Resistance field must be an object");
    private static EffectSignature Instance(EvidenceObject row, string time, string line) => new([new EvidenceText(Text(row.Get("uid"))), row.Get(time), row.Get(line)]);

    public void Resolve(HitAllocation state)
    {
        var hit = state.Hit;
        if (state.EffectiveResistance is not null || state.ResistanceRows.Count != 0 || state.ResistanceAttribute is null
            || hit.Get("packet_attribute_report_present") is not EvidenceBoolean { Value: true }
            || CatalogValues.Truth(hit.Get("packet_attribute_report_unresolved")) || state.UnresolvedStackZones.Contains("res")) return;
        var initial = BuffEvidence.OptionalFloat(Object(hit.Get("target_resistance_points")).Get(state.Element ?? "None"));
        var actor = Text(hit.Get("target_actor_id"));
        if (initial is null || hit.Get("target_stats_snapshot_ts_ms") is not EvidenceInteger time
            || hit.Get("target_stats_snapshot_line_no") is not EvidenceInteger line || actor.Length == 0
            || CatalogValues.Truth(hit.Get("rdps_unresolved_target_binding"))) return;
        var baseline = (time.Value, line.Value);
        var current = ((BigInteger)state.TimestampMs, (BigInteger)state.LineNumber);
        var known = baseline.CompareTo(current) <= 0;
        double points = 0;
        var persistent = false;
        HashSet<EffectSignature> covered = [];
        for (var index = 0; index < state.Windows.Count; index++)
        {
            var window = state.Windows[index];
            if (Text(window.Get("target_actor_id")) != actor || !EvidenceJson.PythonEquals(window.Get("target_character_key"), new EvidenceText(state.Target))) continue;
            var specs = Objects(window.Get("dynamic_effects")).Where(spec => spec.Fields.ContainsKey("parameter_snapshots")
                && spec.Get("zone") is EvidenceText { Value: "res" } && EffectConditions.AppliesToHit(spec, state.Element, state.School));
            if (!specs.Any()) continue;
            covered.Add(Instance(window, "start_ts_ms", "start_line_no"));
            var start = Stamp(window, "start_ts_ms", "start_line_no");
            var end = Stamp(window, "end_ts_ms", "end_line_no", lineFallback: long.MaxValue);
            if (start.CompareTo(baseline) <= 0 && baseline.CompareTo(end) < 0 || CatalogValues.Truth(window.Get("_effect_state_unresolved_at_hit"))) known = false;
            if (start.CompareTo(current) <= 0 && current.CompareTo(end) <= 0)
            {
                persistent = true;
                points += PythonFloatSum.Sum((state.EffectsAtHit.GetValueOrDefault(index) ?? []).Cast<EvidenceObject>()
                    .Where(effect => effect.Get("resistance_point_source") is EvidenceText { Value: "packet_bb_update_and_refresh" }
                        && EffectConditions.AppliesToHit(effect, state.Element, state.School))
                    .Select(effect => EffectIdentity.Float(effect.Fields["rate"])));
            }
        }
        var attributeName = state.Element switch { "physical" => "PhysicalResistance", "natural" => "NaturalResistance", "cryst" => "CrystResistance",
            "pulse" => "PulseResistance", "fire" => "FireResistance", "ether" => "EtherResistance", _ => throw new KeyNotFoundException("Resistance element") };
        var records = state.Input.ConditionsByActor is null ? state.Input.ConditionRecords : state.Input.ConditionsByActor.GetValueOrDefault(actor);
        foreach (var row in records ?? [])
        {
            if (Text(row.Get("target_actor_id")) != actor || covered.Contains(Instance(row, "ts_ms", "line_no"))) continue;
            var start = Stamp(row, "ts_ms", "line_no");
            var end = Stamp(row, "end_ts_ms", "end_line_no", state.TimestampMs, long.MaxValue);
            if (!(start.CompareTo(baseline) <= 0 && baseline.CompareTo(end) < 0 || start.CompareTo(current) <= 0 && current.CompareTo(end) < 0)) continue;
            var root = roots.GetValueOrDefault(Text(row.Get("event_key"))) ?? BuffEvidence.Object();
            if (Objects(Object(root.Get("attributeModifier")).Get("attributeModifiers"))
                .Any(modifier => modifier.Get("attributeType") is EvidenceText type && type.Value == attributeName)) known = false;
        }
        if (known && persistent && double.IsFinite(points))
        {
            state.EffectiveResistance = initial.Value - points;
            state.ResistanceNumerator = 100 - state.EffectiveResistance;
            state.ResistanceSource = "ENTITY_STATS+packet_bb_refresh+complete_instant_report";
        }
    }
}
