using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Allocation;

public sealed record PacketDefenderMatches(IReadOnlySet<EffectSignature> Signatures, IReadOnlyList<EvidenceObject> Windows);

/// <summary>Hit-side modifier proof and exact entity/lifetime matching; no inferred BUFF activation.</summary>
public static class PacketAllocationEvidence
{
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static BigInteger Coordinate(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static BigInteger? Optional(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceReal real => TraceFields.OptionalInteger(real.Value),
        EvidenceText text => TraceFields.OptionalInteger(text.Value),
        _ => null,
    };

    public static IReadOnlySet<(string Zone, string Element)> AllowedAttributes(IEnumerable<EvidenceValue>? tokens)
    {
        HashSet<(string, string)> allowed = [];
        foreach (var token in tokens ?? [])
        {
            BigInteger attribute;
            try { attribute = EffectIdentity.Integer(new EvidenceText(CatalogValues.Text(token).Split(':', 2)[0])); }
            catch (Exception error) when (error is FormatException or InvalidCastException) { continue; }
            if (StaticLoadoutEvidence.AttributeEffects.TryGetValue(attribute, out var mapping)) allowed.Add(mapping);
        }
        return allowed;
    }

    public static double? Bucket(string zone, EvidenceObject? raw)
    {
        if (raw is null || raw.Fields.Count == 0) return null;
        var (side, index) = zone switch
        {
            "dmg_inc" => ("atk_zones", 1), "amp" => ("atk_zones", 3), "combo" => ("atk_zones", 4),
            "vuln_taken" => ("def_zones", 1), "fragile" => ("def_zones", 5), _ => ("", -1),
        };
        if (index < 0 || !CatalogValues.Truth(raw.Get(side))) return null;
        var values = raw.Get(side) switch
        {
            EvidenceArray array => array.Items,
            EvidenceText text => CatalogValues.Iterable(text).ToArray(),
            _ => throw new InvalidCastException("Damage pack buckets must be an indexed sequence"),
        };
        if (index >= values.Count) return null;
        try { return EffectIdentity.Float(values[index]); }
        catch (Exception error) when (error is FormatException or InvalidCastException) { return null; }
    }

    public static bool MatchesUids(EvidenceObject window, IReadOnlySet<string> packetUids)
    {
        if (packetUids.Count == 0) return true;
        var aliases = EffectIdentity.WindowUids(window);
        return aliases.Count == 0 || aliases.Any(packetUids.Contains);
    }

    public static PacketDefenderMatches MatchDefender(EvidenceObject hit, IReadOnlyList<EvidenceObject> windows,
        IReadOnlySet<string> defenderUids)
    {
        HashSet<EffectSignature> signatures = [];
        var updated = windows.ToArray();
        if (defenderUids.Count == 0) return new(signatures, updated);
        var target = Text(hit.Get("target_enemy_key"));
        var stamp = Coordinate(hit.Get("ts_ms"));
        var line = Coordinate(hit.Get("line_no"));
        var skill = Text(hit.Get("skill_key"));
        for (var index = 0; index < windows.Count; index++)
        {
            var window = windows[index];
            if (target.Length == 0 || Text(window.Get("target_character_key")) != target
                || !EffectIdentity.WindowUids(window).Any(defenderUids.Contains)) continue;
            var evaluation = EffectWindowEvaluation.At(window, new(checked((long)stamp), checked((int)line),
                hit.Get("packet_seq_id") is EvidenceInteger sequence ? sequence.Value : null));
            updated[index] = evaluation.Window;
            if (evaluation.Effects.Count == 0) continue;
            var start = Coordinate(window.Get("start_ts_ms"));
            if (stamp < start || stamp > Coordinate(window.Get("end_ts_ms"))) continue;
            var startLine = Coordinate(CatalogValues.Or(window.Get("start_line_no"), window.Get("line_no")));
            if (stamp == start && line != 0 && startLine != 0 && startLine > line
                || stamp == start && Text(window.Get("event_key")) == skill) continue;
            var family = window.Get("skill_family_key");
            if (CatalogValues.Truth(family) && !EvidenceJson.PythonEquals(family, hit.Get("skill_family_key"))) continue;
            // The fixed source has an empty _BUFF_SKILL_FILTER; no inferred name filter is applied.
            foreach (var effect in evaluation.Effects.Cast<EvidenceObject>())
                if (Text(effect.Get("zone")) == "vuln_taken") signatures.Add(EffectIdentity.PacketGuard(effect));
        }
        return new(signatures, updated);
    }

    public static IReadOnlySet<string> ActiveTargetBuffs(EvidenceObject hit, IEnumerable<EvidenceObject>? records, string side = "defender")
    {
        var attacker = side == "attacker";
        var target = Text(hit.Get(attacker ? "character_key" : "target_enemy_key"));
        var targetId = Text(hit.Get(attacker ? "source_actor_id" : "target_actor_id"));
        var stamp = Coordinate(hit.Get("ts_ms"));
        var line = Coordinate(hit.Get("line_no"));
        var modifiers = CatalogValues.Or(hit.Get("packet_modifier_uids"), BuffEvidence.Object()) as EvidenceObject
            ?? throw new InvalidDataException("Packet modifier UIDs must be an object");
        HashSet<string> packetUids = new(CatalogValues.Iterable(modifiers.Fields.GetValueOrDefault(side) ?? new EvidenceArray([]))
            .Select(CatalogValues.Text), StringComparer.Ordinal);
        HashSet<string> active = new(StringComparer.Ordinal);
        foreach (var record in records ?? [])
        {
            if (Text(CatalogValues.Or(record.Get("target_enemy_key"), record.Get("target_character_key"))) != target) continue;
            var owner = Text(record.Get("target_actor_id"));
            var seen = packetUids.Contains(Text(record.Get("uid")));
            if (targetId.Length != 0 && owner.Length != 0 && targetId != owner) continue;
            if ((targetId.Length == 0 || owner.Length == 0) && !seen) continue;
            var start = Optional(record.Get("ts_ms"));
            if (start is null || start > stamp) continue;
            var startLine = Coordinate(record.Get("line_no"));
            if (start == stamp && line != 0 && startLine != 0 && startLine > line) continue;
            var end = Optional(record.Get("end_ts_ms"));
            var endLine = Coordinate(record.Get("end_line_no"));
            if (end is not null && (stamp > end || stamp == end && (endLine == 0 || line == 0 || line >= endLine))) continue;
            var snapshot = record.Get("snapshot_end_ts_ms");
            if (snapshot is not EvidenceNull && (stamp > EffectIdentity.Integer(snapshot)
                || stamp == EffectIdentity.Integer(snapshot) && (line == 0 || line >= Coordinate(record.Get("snapshot_end_line_no"))))) continue;
            var duration = Optional(record.Get("raw_duration_ms"));
            if (duration is not null && (duration <= 0 || stamp >= start + duration)) continue;
            if (end is null && duration is null && !seen && record.Get("lifetime_mode") is not EvidenceText { Value: "Infinity" }) continue;
            foreach (var key in new[] { record.Get("event_key"), record.Get("raw_event_key") })
                if (CatalogValues.Truth(key)) active.Add(CatalogValues.Text(key));
        }
        return active;
    }
}
