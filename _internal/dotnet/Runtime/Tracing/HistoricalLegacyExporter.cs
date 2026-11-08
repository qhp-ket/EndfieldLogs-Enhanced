using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Runtime.Tracing;

/// <summary>Reconstruct historical fields, never a stored whole legacy line.</summary>
public static class HistoricalLegacyExporter
{
    public static string Body(string type, EvidenceObject data)
    {
        if (data.Get("observation") is not EvidenceObject observation) throw new InvalidDataException("Missing historical export observation");
        string Token(string key) => observation.Get(key) is EvidenceText text ? text.Value : throw new InvalidDataException("Missing historical export token: " + key);
        if (type == "damage_raw")
        {
            var probe = observation.Get("probe") is EvidenceText value ? " probe=" + value.Value : "";
            return $"DPD_RAW #{Token("sequence_token")}{probe} calc={Token("calc")} atkScale={Token("atk_scale")} blocked={Token("blocked")} damageType={Token("damage_type")} decorateMask={Token("decorate_mask")} collider=\"{Token("collider")}\" atkZones=[{Token("atk_zones")}] defZones=[{Token("def_zones")}]";
        }
        if (type == "damage_baseline")
        {
            if (observation.Get("values") is not EvidenceArray values) throw new InvalidDataException("Missing historical baseline values");
            var tokens = values.Items.Select(value => value is EvidenceObject row && row.Get("attribute_type") is EvidenceText key && row.Get("value") is EvidenceText number
                ? key.Value + "=" + number.Value : throw new InvalidDataException("Invalid historical baseline value"));
            return $"BASELINE #{Token("sequence_token")} " + string.Join(' ', tokens);
        }
        var marker = type switch
        {
            "legacy_attribute_modifier" => "ATTR_MOD", "legacy_damage_modifier" => "DMG_MOD",
            "clock_tick" when data.Get("source") is EvidenceText { Value: "GAME_TIMER_TICK" or "HEARTBEAT" } clock => clock.Value,
            _ => throw new InvalidDataException("Expected historical event"),
        };
        var fields = HistoricalEvidenceWire.Fields(data);
        return marker + (fields.Count == 0 ? "" : " " + string.Join(' ', fields.Select(field => field.Name + "=" + (field.Quoted ? "\"" + field.Value + "\"" : field.Value))));
    }

    public static IReadOnlyList<string> Lines(TraceEvent item, int offset)
    {
        var data = ExportValues.Data(item);
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(offset)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return ["[" + stamp + "] " + Body(item.Type, data) + "\n"];
    }
}
