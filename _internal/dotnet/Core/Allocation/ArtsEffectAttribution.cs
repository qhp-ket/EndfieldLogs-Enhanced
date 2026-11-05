using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Allocation;

public sealed record ArtsEffectSource(string Provider, double Rate, EvidenceObject? Provenance);
public sealed record ArtsEffectAttributionResult(IReadOnlyList<ArtsEffectSource> Sources, IReadOnlyList<EvidenceObject> Windows);

/// <summary>Redistribute a debuff's strength only with explicit typed arts-strength provenance at its application.</summary>
public static class ArtsEffectAttribution
{
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static long Coordinate(EvidenceValue value) => checked((long)EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0))));
    private static double Float(EvidenceValue value) => EffectIdentity.Float(CatalogValues.Or(value, new EvidenceReal(0)));
    public static ArtsEffectAttributionResult Attribute(EvidenceObject window, EvidenceObject effect, IReadOnlyList<EvidenceObject> sourceWindows)
    {
        var source = Text(window.Get("source_character_key"));
        var final = Float(effect.Get("rate"));
        if (effect.Get("arts_strength_provenance") is not EvidenceBoolean { Value: true }) return new([new(source, final, null)], sourceWindows);
        var windows = sourceWindows.ToArray();
        var applied = Coordinate(window.Get("start_ts_ms"));
        var line = checked((int)Coordinate(CatalogValues.Or(window.Get("start_line_no"), window.Get("line_no"))));
        var self = Math.Max(Float(window.Get("source_static_arts_strength")), 0);
        Dictionary<string, double> pointsByProvider = new(StringComparer.Ordinal);
        Dictionary<string, HashSet<EffectSignature>> approvals = new(StringComparer.Ordinal);
        for (var index = 0; index < windows.Length; index++)
        {
            var candidate = windows[index];
            if (Text(candidate.Get("target_character_key")) != source) continue;
            var start = Coordinate(candidate.Get("start_ts_ms"));
            if (start > applied || applied > Coordinate(candidate.Get("end_ts_ms"))) continue;
            var startLine = Coordinate(CatalogValues.Or(candidate.Get("start_line_no"), candidate.Get("line_no")));
            if (start == applied && line != 0 && startLine != 0 && startLine > line) continue;
            var provider = Text(candidate.Get("source_character_key"));
            if (provider.Length == 0) continue;
            var evaluated = EffectWindowEvaluation.At(candidate, new(applied, line));
            windows[index] = evaluated.Window;
            foreach (var row in evaluated.Effects.Cast<EvidenceObject>())
            {
                if (Text(row.Get("zone")) != "arts_strength") continue;
                var points = Float(row.Get("rate"));
                if (points <= 0) continue;
                if (provider == source) self += points;
                else
                {
                    if (row.Get("external_rdps_allowed") is EvidenceBoolean { Value: false }) continue;
                    pointsByProvider[provider] = pointsByProvider.GetValueOrDefault(provider) + points;
                    if (!approvals.TryGetValue(provider, out var keys)) approvals[provider] = keys = [];
                    foreach (var value in CatalogValues.Iterable(CatalogValues.Or(row.Get("rdps_whitelist_keys"), new EvidenceArray([]))))
                        keys.Add(new([value], value is not (EvidenceArray or EvidenceObject)));
                }
            }
        }
        var total = PythonFloatSum.Sum(pointsByProvider.Values);
        if (total <= 0) return new([new(source, final, null)], windows);
        static double Multiplier(double value)
        {
            var normalized = Math.Max(value, 0);
            return 1 + 2 * normalized / (normalized + 300);
        }
        var without = final * (Multiplier(self) / Multiplier(self + total));
        var external = Math.Max(final - without, 0);
        List<ArtsEffectSource> sources = [new(source, without, null)];
        foreach (var (provider, points) in pointsByProvider)
        {
            var provenance = BuffEvidence.Object(("derived_from_zone", new EvidenceText("arts_strength")),
                ("effect_event_key", window.Get("event_key")), ("effect_source_character_key", new EvidenceText(source)),
                ("arts_strength_points", new EvidenceReal(points)), ("arts_strength_self_points", new EvidenceReal(self)),
                ("arts_strength_external_points", new EvidenceReal(total)), ("arts_strength_whitelist_keys", new EvidenceArray(
                    approvals[provider].Select(signature => signature.Parts.Items[0]).Order(Comparer<EvidenceValue>.Create(EffectIdentity.CompareKeys)).Select(BuffEvidence.Clone).ToArray())));
            sources.Add(new(provider, external * (points / total), provenance));
        }
        return new(sources, windows);
    }
}
