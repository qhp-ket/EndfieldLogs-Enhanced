using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Historical observations only. Token strings retain legacy precision, not new calculation authority.</summary>
public static class HistoricalEvidenceWire
{
    public sealed record Field(string Name, string Value, bool Quoted);
    private static EvidenceText Text(string value) => new(value);
    private static EvidenceObject Object(params (string Key, EvidenceValue Value)[] fields)
        => new(fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));

    public static (string Type, EvidenceObject Data)? Data(string line)
    {
        var raw = TraceFields.RawDamageTokens(line);
        if (raw.Success)
        {
            var observation = new Dictionary<string, EvidenceValue>(StringComparer.Ordinal);
            foreach (var key in new[] { "calc", "atk_scale", "blocked", "damage_type", "decorate_mask", "collider", "atk_zones", "def_zones" })
                observation[key] = Text(raw.Groups[key].Value);
            observation["sequence_token"] = Text(raw.Groups["seq"].Value);
            var probe = TraceFields.Token(line, "probe");
            if (probe is not null) observation["probe"] = Text(probe);
            return ("damage_raw", Object(("hit_seq", new EvidenceInteger(TraceFields.OptionalInteger(raw.Groups["seq"].Value)!.Value)), ("observation", new EvidenceObject(observation))));
        }
        var baseline = TraceFields.BaselineTokens(line);
        if (baseline.Success)
        {
            var values = Regex.Matches(baseline.Groups["body"].Value, @"(-?\d+)=([-\d.eE+]+)").Cast<Match>()
                .Select(match => (EvidenceValue)Object(("attribute_type", Text(match.Groups[1].Value)), ("value", Text(match.Groups[2].Value)))).ToArray();
            return ("damage_baseline", Object(("hit_seq", new EvidenceInteger(TraceFields.OptionalInteger(baseline.Groups["seq"].Value)!.Value)),
                ("observation", Object(("sequence_token", Text(baseline.Groups["seq"].Value)), ("values", new EvidenceArray(values))))));
        }
        if (line.Contains(" IDENTITY_INFERENCE ", StringComparison.Ordinal))
        {
            var fields = TraceFields.Extract(line);
            return ("identity_inference", Object(("entity_id", Text(fields.GetValueOrDefault("actorId") ?? "unknown")),
                ("template", Text(fields.GetValueOrDefault("template") ?? "unknown")), ("inference_source", Text(fields.GetValueOrDefault("source") ?? "unknown"))));
        }
        var type = line.Contains(" ATTR_MOD ", StringComparison.Ordinal) ? "legacy_attribute_modifier"
            : line.Contains(" DMG_MOD ", StringComparison.Ordinal) ? "legacy_damage_modifier" : null;
        var clock = Regex.Match(line, @"^\[[\d:.]+\] (?<kind>GAME_TIMER_TICK|HEARTBEAT)(?:\s|$)");
        if (type is null && !clock.Success) return null;
        var tokens = Regex.Matches(line, "(\\w+)=(\".*?\"|\\S+)").Cast<Match>().Select(match =>
        {
            var token = match.Groups[2].Value; var quoted = token.StartsWith('"') && token.EndsWith('"');
            return (EvidenceValue)Object(("name", Text(match.Groups[1].Value)), ("value", Text(quoted ? token[1..^1] : token)), ("quoted", new EvidenceBoolean(quoted)));
        }).ToArray();
        var data = new Dictionary<string, EvidenceValue> { ["observation"] = Object(("fields", new EvidenceArray(tokens))) };
        if (clock.Success)
        {
            data["source"] = Text(clock.Groups["kind"].Value);
            var fields = TraceFields.Extract(line);
            foreach (var (key, target) in new[] { ("tickMs", "tick_ms"), ("seq", "operation_seq") })
                if (TraceFields.OptionalInteger(fields.GetValueOrDefault(key)) is { } value) data[target] = new EvidenceInteger(value);
        }
        return (type ?? "clock_tick", new(data));
    }

    public static IReadOnlyList<Field> Fields(EvidenceObject data)
    {
        if (data.Get("observation") is not EvidenceObject observation || observation.Get("fields") is not EvidenceArray rows)
            throw new InvalidDataException("Historical observation requires ordered fields");
        List<Field> result = [];
        foreach (var value in rows.Items)
        {
            if (value is not EvidenceObject row || row.Get("name") is not EvidenceText name || row.Get("value") is not EvidenceText token
                || row.Get("quoted") is not EvidenceBoolean quoted) throw new InvalidDataException("Invalid historical field");
            result.Add(new(name.Value, token.Value, quoted.Value));
        }
        return result;
    }

    public static void Accept(TraceEvent item, PacketObservationState packets, BuffInstanceState buffs)
    {
        if (item.Type is "legacy_attribute_modifier" or "legacy_damage_modifier")
        {
            Dictionary<string, string> fields = new(StringComparer.Ordinal);
            foreach (var field in Fields(item.Data)) fields[field.Name] = field.Value;
            buffs.ObserveModifier(fields);
            buffs.PendingRecord = null; // The legacy lifecycle also ends the pending BB window here.
            return;
        }
        if (item.Data.Get("hit_seq") is not EvidenceInteger { Value.Sign: >= 0 } sequence
            || item.Data.Get("observation") is not EvidenceObject observation) throw new InvalidDataException("Historical damage requires a hit sequence and observation");
        string Token(string key) => observation.Get(key) is EvidenceText text ? text.Value : throw new InvalidDataException("Historical damage token missing: " + key);
        if (item.Type == "damage_raw")
        {
            var raw = new RawDamageEvidence(sequence.Value, TraceFields.OptionalFloat(Token("calc")), TraceFields.OptionalFloat(Token("atk_scale")),
                TraceFields.OptionalInteger(Token("blocked")), Token("damage_type"), Token("decorate_mask"), Token("collider"),
                TraceFields.ZoneValues(Token("atk_zones")), TraceFields.ZoneValues(Token("def_zones")));
            packets.ObserveRawDamage(raw);
        }
        else if (item.Type == "damage_baseline")
        {
            if (observation.Get("values") is not EvidenceArray values) throw new InvalidDataException("Historical baseline requires ordered values");
            Dictionary<BigInteger, double> parsed = [];
            foreach (var value in values.Items)
            {
                if (value is not EvidenceObject row || row.Get("attribute_type") is not EvidenceText key || row.Get("value") is not EvidenceText text
                    || TraceFields.OptionalInteger(key.Value) is not { } attribute) throw new InvalidDataException("Invalid historical baseline field");
                parsed[attribute] = TraceFields.Float(text.Value);
            }
            packets.ObserveBaseline(new(sequence.Value, parsed));
        }
        else throw new InvalidDataException("Expected historical packet or modifier observation");
    }
}
