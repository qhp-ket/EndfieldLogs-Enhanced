using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Allocation;

/// <summary>Owned explanation rows; names are supplied by the catalog, never by UI state.</summary>
public sealed class AllocationDebug(Func<string?, string?> characterName)
{
    private static readonly string[] ZoneOrder = ["atk", "dmg_inc", "fragile", "vuln_taken", "amp", "res", "combo", "crit", "arts_strength", "prod_dmg_inc", "prod_vuln_taken"];
    private static string Text(EvidenceValue value, string fallback = "") => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText(fallback)));
    private static string Label(string zone) => StaticLoadoutEvidence.ZoneLabels.GetValueOrDefault(zone) ?? zone;
    internal EvidenceValue Name(EvidenceValue key) => BuffEvidence.Text(characterName(key is EvidenceNull ? null : CatalogValues.Text(key)));
    private static Dictionary<string, EvidenceValue> Fields(EvidenceObject row) => (Dictionary<string, EvidenceValue>)row.Fields;
    public static EvidenceValue Round4(EvidenceValue value)
    {
        if (value is EvidenceNull) return value;
        try { return new EvidenceReal(PythonDecimalRounding.Round(EffectIdentity.Float(value), 4)); }
        catch (Exception error) when (error is InvalidCastException or FormatException) { return EvidenceNull.Value; }
    }
    private static EvidenceValue Round4(double? value) => value is double number ? new EvidenceReal(PythonDecimalRounding.Round(number, 4)) : EvidenceNull.Value;
    private static EvidenceArray List(EvidenceValue value) => new(CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([]))).Select(BuffEvidence.Clone).ToArray());

    public IReadOnlyList<EvidenceObject> SortZones(IEnumerable<EvidenceObject> rows) => rows.OrderBy(row =>
        Array.IndexOf(ZoneOrder, Text(row.Get("zone"))) is var index && index >= 0 ? index : 99)
        .ThenBy(row => Text(row.Get("zone")), PythonDisplay.CodePointComparer).ToArray();

    public EvidenceObject Applicable(EvidenceObject window, EvidenceObject effect, string scope, double? credit = null)
    {
        var source = window.Get("source_character_key");
        var raw = window.Get("raw_source_character_key");
        var zone = Text(effect.Get("zone"));
        Dictionary<string, EvidenceValue> row = new(StringComparer.Ordinal)
        {
            ["scope"] = new EvidenceText(scope), ["source_character_key"] = source,
            ["source_character_name"] = CatalogValues.Or(window.Get("source_character_name"), Name(source), source),
            ["raw_source_character_key"] = raw,
            ["raw_source_character_name"] = CatalogValues.Or(window.Get("raw_source_character_name"), Name(raw), raw),
            ["zone"] = new EvidenceText(zone), ["zone_label"] = new EvidenceText(Label(zone)),
            ["element"] = new EvidenceText(Text(effect.Get("element"), "all")),
            ["rate"] = Round4(CatalogValues.Or(effect.Get("rate"), new EvidenceReal(0))), ["rdps_credit"] = Round4(credit),
            ["uid_aliases"] = List(window.Get("uid_aliases")),
        };
        foreach (var key in new[] { "raw_source", "target_character_key", "target_character_name", "owner_raw", "event_key", "event_name", "uid", "start_ts_ms", "start_time", "end_ts_ms", "end_time" }) row[key] = window.Get(key);
        if (effect.Get("condition") is EvidenceObject condition) row["condition"] = BuffEvidence.Clone(condition);
        foreach (var key in new[] { "rdps_whitelist_keys", "external_rdps_allowed", "keyword_origin", "recipient_side", "converted_attribute" })
            if (effect.Fields.ContainsKey(key)) row[key] = BuffEvidence.Clone(effect.Get(key));
        return (EvidenceObject)BuffEvidence.Clone(new EvidenceObject(row));
    }

    private EvidenceObject Self(EvidenceObject hit, string zone, string element, string source, string eventKey, string eventName, EvidenceValue rate)
    {
        var attacker = Text(hit.Get("character_key"));
        var name = Text(CatalogValues.Or(hit.Get("character_name"), Name(new EvidenceText(attacker)), new EvidenceText(attacker)));
        Dictionary<string, EvidenceValue> row = new(StringComparer.Ordinal)
        {
            ["scope"] = new EvidenceText("self"), ["raw_source"] = new EvidenceText(source), ["owner_raw"] = new EvidenceText(source),
            ["event_key"] = new EvidenceText(eventKey), ["event_name"] = new EvidenceText(eventName),
            ["zone"] = new EvidenceText(zone), ["zone_label"] = new EvidenceText(Label(zone)), ["element"] = new EvidenceText(element),
            ["rate"] = Round4(rate), ["rdps_credit"] = EvidenceNull.Value,
        };
        foreach (var prefix in new[] { "source", "raw_source", "target" })
        {
            row[prefix + "_character_key"] = new EvidenceText(attacker);
            row[prefix + "_character_name"] = new EvidenceText(name);
        }
        foreach (var key in new[] { "uid", "start_ts_ms", "start_time", "end_ts_ms", "end_time" }) row[key] = EvidenceNull.Value;
        return new(row);
    }

    public EvidenceObject DpdResidual(EvidenceObject hit, string zone, double rate) => Self(hit, zone, Text(hit.Get("damage_element"), "all"),
        "DPD_RAW", "__dpd_self_residual__", "自身基线/未归因（DPD残差）", new EvidenceReal(rate));

    public EvidenceObject Baseline(EvidenceObject hit, BigInteger attribute, string zone, string element, double rate, double finalValue, double captured)
    {
        var label = BuffLabelCatalog.AttributeLabel(attribute) ?? Label(zone);
        var row = Self(hit, zone, element, "BASELINE", $"__baseline_attr_{attribute}__",
            $"自身属性基线（{label} / attrType={attribute}）", new EvidenceReal(rate));
        Fields(row)["baseline_final"] = Round4(finalValue);
        Fields(row)["baseline_captured"] = Round4(captured);
        return row;
    }

    public EvidenceObject Static(EvidenceObject hit, EvidenceObject entry)
    {
        var zone = Text(entry.Get("zone"));
        var type = Text(entry.Get("source_type"), "static");
        var name = Text(entry.Get("source_name"), "静态来源");
        var row = Self(hit, zone, Text(entry.Get("element"), "all"), type, $"__static_self_{type}__",
            $"自身静态基线（{name} / {Text(entry.Get("label"), zone)}）", CatalogValues.Or(entry.Get("rate"), new EvidenceReal(0)));
        Fields(row)["note"] = BuffEvidence.Clone(entry.Get("note"));
        return row;
    }

    public IReadOnlyList<EvidenceObject> ContributionRows(IReadOnlyDictionary<string, double> values, bool sortByValue)
    {
        var rows = sortByValue ? values.OrderBy(pair => -pair.Value).ThenBy(pair => pair.Key, PythonDisplay.CodePointComparer)
            : values.OrderBy(pair => pair.Key, PythonDisplay.CodePointComparer);
        return rows.Where(pair => pair.Value > 0).Select(pair => BuffEvidence.Object(("character_key", new EvidenceText(pair.Key)),
            ("character_name", CatalogValues.Or(Name(new EvidenceText(pair.Key)), new EvidenceText(pair.Key))), ("value", new EvidenceReal(pair.Value)))).ToArray();
    }

    internal IReadOnlyList<EvidenceObject> RecordedContributionRows(EvidenceObject values)
    {
        var ordered = values.Fields.Order(Comparer<KeyValuePair<string, EvidenceValue>>.Create((left, right) =>
        {
            var comparison = EffectIdentity.CompareKeys(right.Value, left.Value);
            return comparison == 0 ? PythonDisplay.CodePointComparer.Compare(left.Key, right.Key) : comparison;
        }));
        return ordered.Where(pair => pair.Value is not EvidenceReal { Value: var number } || !double.IsNaN(number))
            .Where(pair => EffectIdentity.CompareKeys(pair.Value, new EvidenceInteger(0)) > 0)
            .Select(pair => BuffEvidence.Object(("character_key", new EvidenceText(pair.Key)),
                ("character_name", CatalogValues.Or(Name(new EvidenceText(pair.Key)), new EvidenceText(pair.Key))),
                ("value", BuffEvidence.Clone(pair.Value)))).ToArray();
    }

    public EvidenceObject ArtsProvenance(EvidenceObject window, EvidenceObject effect, string source, double rate, EvidenceObject? provenance, string scope)
    {
        var debugEffect = new EvidenceObject(new Dictionary<string, EvidenceValue>(effect.Fields) { ["rate"] = new EvidenceReal(rate) });
        var key = new EvidenceText(source);
        var debugWindow = new EvidenceObject(new Dictionary<string, EvidenceValue>(window.Fields)
        { ["source_character_key"] = key, ["source_character_name"] = CatalogValues.Or(Name(key), key) });
        var row = Applicable(debugWindow, debugEffect, scope);
        if (provenance is { Fields.Count: > 0 })
        {
            var fields = Fields(row);
            fields["derived_from_zone"] = new EvidenceText("arts_strength");
            fields["effect_source_character_key"] = BuffEvidence.Clone(provenance.Get("effect_source_character_key"));
            foreach (var name in new[] { "arts_strength_points", "arts_strength_self_points", "arts_strength_external_points" })
                fields[name] = Round4(CatalogValues.Or(provenance.Get(name), new EvidenceReal(0)));
            fields["effect_rdps_whitelist_keys"] = List(effect.Get("rdps_whitelist_keys"));
            fields["rdps_whitelist_keys"] = List(provenance.Get("arts_strength_whitelist_keys"));
        }
        return row;
    }
}
