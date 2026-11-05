using System.Numerics;
using System.Collections.ObjectModel;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>One decoded damage observation. Text import is an adapter into this same state boundary.</summary>
public sealed record DamageObservation
{
    private static readonly HitBlackboards EmptyBlackboards = new(null,
        new ReadOnlyDictionary<BigInteger, double>(new Dictionary<BigInteger, double>()), null,
        new ReadOnlyDictionary<BigInteger, Dictionary<string, EvidenceValue>>(new Dictionary<BigInteger, Dictionary<string, EvidenceValue>>()));
    public BigInteger? Sequence { get; init; }
    public string? Source { get; init; }
    public string? Attacker { get; init; }
    public string? Target { get; init; }
    public string? SourceActor { get; init; }
    public string? TargetActor { get; init; }
    public string? Skill { get; init; }
    public string? TemplateType { get; init; }
    public BigInteger Hit { get; init; }
    public bool HitObserved { get; init; }
    public string? UnresolvedHitText { get; init; }
    public BigInteger EnemyHp { get; init; }
    public bool EnemyHpObserved { get; init; }
    public double? Raw { get; init; }
    public double? Final { get; init; }
    public BigInteger Critical { get; init; }
    public bool CriticalObserved { get; init; }
    public BigInteger? SkillLevel { get; init; }
    public BigInteger? TemplateInteger { get; init; }
    public string? EventInstance { get; init; }
    public string? EventOwner { get; init; }
    public BigInteger? ClientTick { get; init; }
    public BigInteger? Action { get; init; }
    public BigInteger? UnitIndex { get; init; }
    public BigInteger? OriginalTemplate { get; init; }
    public BigInteger? PartInstance { get; init; }
    public BigInteger HitIndex { get; init; } = BigInteger.One;
    public string? PacketOwner { get; init; }
    public BigInteger? PacketGeneration { get; init; }
    public BigInteger? PacketSequence { get; init; }
    public string? PacketSession { get; init; }
    public HitBlackboards Blackboards { get; init; } = EmptyBlackboards;

    public static DamageObservation FromLegacy(string line)
    {
        var fields = TraceFields.Extract(line);
        BigInteger Integer(string key, int fallback = 0) => TraceFields.OptionalInteger(fields.GetValueOrDefault(key)) ?? fallback;
        BigInteger? Nonzero(string key) => Integer(key) is var value && !value.IsZero ? value : null;
        BigInteger? Index(string key) => Regex.IsMatch(fields.GetValueOrDefault(key) ?? "", @"\A\d+\z")
            ? TraceFields.OptionalInteger(fields.GetValueOrDefault(key)) : null;
        string? Actor(string key) => Regex.IsMatch(fields.GetValueOrDefault(key) ?? "", @"\A[1-9]\d*\z") ? fields[key] : null;
        var match = Regex.Match(line, @"\bHP_V2\s+#(\d+)\b");
        var owner = Actor("packetOwnerId");
        if (owner is not null && Integer("packetOwnerId") >= BigInteger.One << 64) owner = null;
        return new()
        {
            Sequence = match.Success ? TraceFields.OptionalInteger(match.Groups[1].Value) : null,
            Source = fields.GetValueOrDefault("src"), Attacker = fields.GetValueOrDefault("atk"), Target = fields.GetValueOrDefault("tgt"),
            SourceActor = Actor("atkId"), TargetActor = Actor("tgtId"), Skill = fields.GetValueOrDefault("skill"),
            TemplateType = fields.GetValueOrDefault("templateType"), Hit = Integer("hit"), HitObserved = fields.ContainsKey("hit"),
            UnresolvedHitText = fields.GetValueOrDefault("hit"), EnemyHp = Integer("eHP"), EnemyHpObserved = fields.ContainsKey("eHP"),
            Raw = TraceFields.OptionalFloat(fields.GetValueOrDefault("raw")), Final = TraceFields.OptionalFloat(fields.GetValueOrDefault("packetFinalValue")),
            Critical = Integer("critFlag"), CriticalObserved = fields.GetValueOrDefault("critFlag") is "0" or "1",
            SkillLevel = Nonzero("skillLv"), TemplateInteger = Nonzero("templateIntId"), EventInstance = Actor("eventInstId"),
            EventOwner = Actor("eventOwnerId"), ClientTick = Index("clientTick"), Action = Index("actionId"), UnitIndex = Index("damageUnitIndex"),
            OriginalTemplate = Nonzero("origTemplateIntId"), PartInstance = TraceFields.OptionalInteger(fields.GetValueOrDefault("partInstId")),
            HitIndex = Integer("hits", 1), PacketOwner = owner, PacketGeneration = Index("packetGeneration"), PacketSequence = Index("packetSeq"),
            PacketSession = fields.GetValueOrDefault("packetSessionId") is { Length: > 0 } session ? session : null,
            Blackboards = ParseBlackboards(fields),
        };
    }

    private static HitBlackboards ParseBlackboards(IReadOnlyDictionary<string, string> fields)
    {
        Dictionary<BigInteger, double> dynamic = [];
        foreach (var token in Regex.Split(fields.GetValueOrDefault("dynBB") ?? "", "[,;]"))
        {
            var colon = token.IndexOf(':');
            if (colon >= 0 && TraceFields.OptionalInteger(token[..colon]) is BigInteger key
                && TraceFields.OptionalFloat(token[(colon + 1)..]) is double value) dynamic[key] = value;
        }
        Dictionary<BigInteger, Dictionary<string, EvidenceValue>> calculation = [];
        foreach (var token in Regex.Split(fields.GetValueOrDefault("calcBB") ?? "", "[,;]"))
        {
            var colon = token.IndexOf(':'); var equal = colon < 0 ? -1 : token.IndexOf('=', colon + 1);
            if (colon < 0 || equal <= colon + 1 || TraceFields.OptionalInteger(token[..colon]) is not BigInteger group) continue;
            if (!calculation.TryGetValue(group, out var entries)) calculation[group] = entries = new(StringComparer.Ordinal);
            var text = token[(equal + 1)..];
            entries[token[(colon + 1)..equal]] = TraceFields.OptionalFloat(text) is double number ? new EvidenceReal(number) : new EvidenceText(text);
        }
        return new(fields.GetValueOrDefault("dynBB"), dynamic, fields.GetValueOrDefault("calcBB"), calculation);
    }

    internal HitBlackboards OwnBlackboards() => new(Blackboards.DynamicSignature, new Dictionary<BigInteger, double>(Blackboards.Dynamic),
        Blackboards.CalculationSignature, Blackboards.Calculation.ToDictionary(pair => pair.Key,
            pair => pair.Value.ToDictionary(item => item.Key, item => EvidenceJson.Clone(item.Value), StringComparer.Ordinal)));
}
