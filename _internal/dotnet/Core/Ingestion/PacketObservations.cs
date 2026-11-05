using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

public sealed class HitPacketEvidence(string? characterKey=null, BigInteger? packetSequence=null, string? packetSession=null)
{
    internal long Revision { get; private set; }
    public string? CharacterKey { get; } = characterKey;
    public BigInteger? PacketSequence { get; } = packetSequence;
    public string? PacketSession { get; } = packetSession;
    public RawDamageEvidence? RawDamage { get; internal set { field = value; Revision++; } }
    public IReadOnlyDictionary<BigInteger, double>? Baseline { get; internal set { field = value; Revision++; } }
    public bool? AttributeReportPresent { get; internal set { field = value; Revision++; } }
    public bool AttributeReportUnresolved { get; internal set { field = value; Revision++; } }
    public EvidenceObject? ModifierHandles { get; internal set { field = value; Revision++; } }
    public bool ModifierHandlesUnresolved { get; internal set { field = value; Revision++; } }
    public PacketListEvidence? Modifiers { get; internal set { field = value; Revision++; } }
    public PacketListEvidence? Attributes { get; internal set { field = value; Revision++; } }
    public bool AttributeConflict { get; internal set { field = value; Revision++; } }
    public bool UnresolvedEffectConditions { get; internal set { field = value; Revision++; } }
}

public sealed record PoiseDamageObservation(int LineNumber, long TimestampMs, double? Value, double? CurrentValue,
    string Source, BigInteger? SourceInteger, string? OriginalSource, BigInteger? OriginalSourceInteger);

/// <summary>Per-hit packet evidence; malformed or conflicting observations permanently invalidate their proof.</summary>
public sealed class PacketObservationState
{
    public Dictionary<BigInteger, HitPacketEvidence> HitsBySequence { get; } = [];
    public Dictionary<string, IReadOnlyDictionary<BigInteger, double>> BaselinesByCharacter { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, long> ModifierLastSeenByUid { get; } = new(StringComparer.Ordinal);
    public List<PoiseDamageObservation> PoiseDamage { get; } = [];

    private static bool ContextMatches(EvidenceObject value, HitPacketEvidence hit)
    {
        var sequence = value.Get("packetSeq");
        var session = value.Get("packetSessionId");
        return (sequence is EvidenceNull || hit.PacketSequence is BigInteger expected && EvidenceJson.PythonEquals(sequence,new EvidenceInteger(expected)))
            && (session is EvidenceNull || session is EvidenceText text && text.Value == hit.PacketSession);
    }

    private static EvidenceObject? Handles(EvidenceObject payload, HitPacketEvidence hit, bool owned)
    {
        if (!ContextMatches(payload,hit)) return null;
        Dictionary<string, EvidenceValue> handles = new(StringComparer.Ordinal);
        foreach (var side in new[] { "attacker", "defender" })
        {
            if (payload.Get(side) is not EvidenceArray entries) return null;
            List<EvidenceValue> normalized = [];
            foreach (var entry in entries.Items)
            {
                if (entry is not EvidenceObject item || item.Get("index") is not EvidenceInteger { Value.Sign: >= 0 }) return null;
                var uid = item.Get("buff_inst_id") switch
                {
                    EvidenceInteger integer => integer.Value.ToString(System.Globalization.CultureInfo.InvariantCulture),
                    EvidenceText text => text.Value,
                    _ => null,
                };
                if (uid is null || !Regex.IsMatch(uid,@"\A[1-9]\d*\z") || TraceFields.OptionalInteger(uid) is not BigInteger number
                    || number >= BigInteger.One << 64) return null;
                var fields = item.Fields.ToDictionary(pair => pair.Key,pair => owned ? pair.Value : EvidenceJson.Clone(pair.Value),StringComparer.Ordinal);
                fields["buff_inst_id"] = new EvidenceText(uid);
                normalized.Add(new EvidenceObject(fields));
            }
            handles[side] = new EvidenceArray(normalized);
        }
        return new(handles);
    }

    private bool ObserveJson(string line, string marker, bool reportPresence)
    {
        var match = Regex.Match(line,@"\b"+marker+@" #(\d+) (\{.*\})$");
        if (!match.Success || TraceFields.OptionalInteger(match.Groups[1].Value) is not BigInteger sequence
            || !HitsBySequence.TryGetValue(sequence,out var hit)) return true;
        EvidenceValue? parsed = null;
        try { parsed = EvidenceJson.Parse(match.Groups[2].Value); }
        catch (FormatException) { }
        if (reportPresence) ObserveAttributeReport(sequence, parsed);
        else ObserveModifierHandles(sequence, parsed, owned: true);
        return true;
    }

    public void ObserveAttributeReport(BigInteger sequence, EvidenceValue? parsed)
    {
        if (!HitsBySequence.TryGetValue(sequence, out var hit)) return;
        if (parsed is EvidenceObject payload && ContextMatches(payload,hit) && payload.Get("reportPresent") is EvidenceBoolean present
            && (hit.AttributeReportPresent is null || hit.AttributeReportPresent == present.Value))
        {
            if (!hit.AttributeReportUnresolved) hit.AttributeReportPresent = present.Value;
        }
        else
        {
            hit.AttributeReportPresent = null;
            hit.AttributeReportUnresolved = true;
        }
    }

    public void ObserveModifierHandles(BigInteger sequence, EvidenceValue? parsed) => ObserveModifierHandles(sequence, parsed, owned: false);

    private void ObserveModifierHandles(BigInteger sequence, EvidenceValue? parsed, bool owned)
    {
        if (!HitsBySequence.TryGetValue(sequence, out var hit)) return;
        var handles = parsed is EvidenceObject payload ? Handles(payload,hit,owned) : null;
        if (handles is not null && (hit.ModifierHandles is null || EvidenceJson.PythonEquals(hit.ModifierHandles,handles)))
        {
            if (!hit.ModifierHandlesUnresolved) hit.ModifierHandles = handles;
        }
        else
        {
            hit.ModifierHandles = null;
            hit.ModifierHandlesUnresolved = true;
        }
    }

    public void ObserveModifiers(PacketListEvidence modifiers, long timestampMs)
    {
        foreach (var uid in modifiers.Attacker.Concat(modifiers.Defender))
            if (uid.Length > 0) ModifierLastSeenByUid[uid] = Math.Max(ModifierLastSeenByUid.GetValueOrDefault(uid,timestampMs),timestampMs);
        if (HitsBySequence.TryGetValue(modifiers.Sequence,out var hit))
            hit.Modifiers = modifiers with { Attacker = modifiers.Attacker.ToArray(), Defender = modifiers.Defender.ToArray() };
    }

    public void ObserveAttributes(PacketListEvidence attrs)
    {
        if (!HitsBySequence.TryGetValue(attrs.Sequence,out var hit)) return;
        if (hit.Attributes is PacketListEvidence previous && (!previous.Attacker.SequenceEqual(attrs.Attacker) || !previous.Defender.SequenceEqual(attrs.Defender)))
        {
            hit.AttributeConflict = true;
            hit.AttributeReportUnresolved = true;
            hit.UnresolvedEffectConditions = true;
        }
        else if (!hit.AttributeConflict)
            hit.Attributes = attrs with { Attacker = attrs.Attacker.ToArray(), Defender = attrs.Defender.ToArray() };
    }

    public bool Observe(string line, int lineNumber, long timestampMs)
    {
        if (TraceFields.RawDamage(line) is RawDamageEvidence raw)
        {
            ObserveRawDamage(raw);
            return true;
        }
        if (TraceFields.Baseline(line) is BaselineEvidence baseline)
        {
            ObserveBaseline(baseline);
            return true;
        }
        if (line.Contains(" PKT_ATTR_INFO #",StringComparison.Ordinal)) return ObserveJson(line,"PKT_ATTR_INFO",true);
        if (line.Contains(" PKT_MOD_DETAIL #",StringComparison.Ordinal)) return ObserveJson(line,"PKT_MOD_DETAIL",false);
        if (TraceFields.PacketModifiers(line) is PacketListEvidence modifiers)
        {
            ObserveModifiers(modifiers, timestampMs);
            return true;
        }
        if (TraceFields.PacketAttributes(line) is PacketListEvidence attrs)
        {
            ObserveAttributes(attrs);
            return true;
        }
        var poise = ParsePoise(line,lineNumber,timestampMs);
        if (poise is null) return false;
        PoiseDamage.Add(poise);
        return true;
    }

    public void ObserveRawDamage(RawDamageEvidence raw)
    {
        if (HitsBySequence.TryGetValue(raw.Sequence, out var hit)) hit.RawDamage = raw;
    }

    public void ObserveBaseline(BaselineEvidence baseline)
    {
        if (!HitsBySequence.TryGetValue(baseline.Sequence, out var hit)) return;
        hit.Baseline = baseline.Values;
        BaselinesByCharacter[hit.CharacterKey ?? ""] = baseline.Values;
    }

    public static PoiseDamageObservation? ParsePoise(string line, int lineNumber, long timestampMs)
    {
        if (!Regex.IsMatch(line,@"\bPOISE_V1\b")) return null;
        var fields = TraceFields.Extract(line);
        static BigInteger? Nonzero(string? value) => TraceFields.OptionalInteger(value) is BigInteger number && !number.IsZero ? number : null;
        return PoiseObservation(lineNumber, timestampMs, fields.GetValueOrDefault("type"),
            TraceFields.OptionalFloat(fields.GetValueOrDefault("value")), TraceFields.OptionalFloat(fields.GetValueOrDefault("cur")),
            fields.GetValueOrDefault("source") ?? "", Nonzero(fields.GetValueOrDefault("sourceInt")),
            fields.GetValueOrDefault("origSource") ?? "", Nonzero(fields.GetValueOrDefault("origSourceInt")));
    }

    public static PoiseDamageObservation? PoiseObservation(int lineNumber, long timestampMs, string? type,
        double? value, double? current, string source, BigInteger? sourceInteger, string original, BigInteger? originalInteger)
    {
        if (type != "PoiseDamage") return null;
        original = original.Trim(); source = source.Trim();
        if (source is "" or "unknown") source = original;
        if (source is "" or "unknown") return null;
        return new(lineNumber, timestampMs, value, current, source, sourceInteger,
            original is "" or "unknown" ? null : original, originalInteger);
    }
}
