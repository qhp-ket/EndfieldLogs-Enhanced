using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Decoded source fields and the established scalar analysis projections.</summary>
public static class SkillWire
{
    public static EvidenceObject Data(string kind, EvidenceObject source)
    {
        (string Input, string Output)[] fields = kind switch
        {
            "skill_cast" => [("skill_inst_id","skill_inst_id"), ("owner_id","owner_id")],
            "atb" => [("owner_id","owner_id"), ("reason","reason"), ("atb_value","value"),
                ("atb_recovery_speed","recovery_speed"), ("delta_value","delta")],
            "poise" => [("attacker_inst_id","attacker_id"), ("modify_type","modify_type"), ("value","value"),
                ("cur_poise_value","current_value"), ("owner_type","owner_type"), ("template_type","source_type"),
                ("template_int_id","source_int"), ("orig_template_type","original_source_type"),
                ("orig_template_int_id","original_source_int"), ("action_id","action_id")],
            _ => throw new InvalidDataException("Expected skill/resource type"),
        };
        Dictionary<string, EvidenceValue> result = [];
        foreach (var (input, output) in fields.Concat([("seq_id","operation_seq"), ("client_tick_tms","client_tick_ms")]))
            if (source.Fields.TryGetValue(input, out var value)) result[output] = value;
        return new(result);
    }
    public static BigInteger? Integer(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsFinite(real.Value) => new BigInteger(real.Value),
        EvidenceText text when BigInteger.TryParse(text.Value.Trim(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var number) => number,
        _ => null,
    };
    public static double? Number(EvidenceValue value) => value switch
    {
        EvidenceReal real => real.Value, EvidenceInteger integer => (double)integer.Value,
        EvidenceBoolean flag => flag.Value ? 1 : 0,
        EvidenceText text when double.TryParse(text.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number) => number,
        _ => null,
    };
    public static double? ProjectedNumber(EvidenceValue value) => Number(value) is { } number && double.IsFinite(number)
        ? double.Parse(number.ToString("g6", CultureInfo.InvariantCulture), CultureInfo.InvariantCulture) : null;
    public static string Label(EvidenceObject data, string key, string fallback = "unknown") => Catalog.CatalogValues.Truth(data.Get(key))
        ? PythonDisplay.String(data.Get(key)) : fallback;
    public static string IdentityToken(EvidenceValue value) => Integer(value)?.ToString(CultureInfo.InvariantCulture) ?? "unknown";
}
