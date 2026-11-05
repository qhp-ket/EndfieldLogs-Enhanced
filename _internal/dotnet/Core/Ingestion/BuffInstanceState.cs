using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Ordered BUFF snapshots and their live UID index, owned by one ingestion stream.</summary>
public sealed class BuffInstanceState(PacketBuffCatalog catalog, IReadOnlyDictionary<string, EvidenceObject> roots,
    IReadOnlyDictionary<string, string> numbers, Func<string?, string?> characterName, Func<string?, string?> enemyName,
    PartyObservationState? party = null)
{
    public PartyObservationState Party { get; } = party ?? new();
    public List<BuffRecord> Records { get; } = [];
    public Dictionary<string, BuffRecord> ActiveByUid { get; } = new(StringComparer.Ordinal);
    public BuffRecord? PendingRecord { get; internal set; }
    public List<string> Roster => Party.Roster;
    public Dictionary<string, List<BuffRecord>> RecentNumericBySource { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, List<BuffAttributeModifier>> PendingModifiers { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, HashSet<string>> ActiveSuits => Party.ActiveSuits;
    public Dictionary<string, string> ActiveWeapons => Party.ActiveWeapons;
    public List<BuffObservation> UnresolvedActions { get; } = [];
    public Dictionary<BuffCreationKey, BuffCreationHistory> CreationHistory { get; } = [];
    public BuffActionIndices ActionIndices { get; } = new();
    public List<BuffObservation> DynamicEvents { get; } = [];
    public List<BuffObservation> AttributeRefreshEvents { get; } = [];
    internal IReadOnlyDictionary<string, EvidenceObject> Roots => roots;
    internal IReadOnlyDictionary<string, string> Numbers => numbers;

    private BuffProjectionChanges? projectionChanges;
    internal BuffProjectionChanges TrackProjectionChanges()
    {
        if (projectionChanges is null)
        {
            projectionChanges = new();
            foreach (var record in Records) projectionChanges.Add(record);
        }
        return projectionChanges;
    }
    internal void MarkProjectionChanged(BuffRecord record) => projectionChanges?.Changed(record);
    internal void RemoveRecord(BuffRecord record)
    {
        if (Records.Remove(record)) projectionChanges?.Removed(record);
    }

    internal static string Normalize(string? value) => string.IsNullOrEmpty(value) ? "unknown_buff" : value;
    internal static string? ActorId(string? value) => Regex.IsMatch(value ?? "", @"\A[1-9]\d*\z") ? value : null;
    internal static bool ValidPacketId(EvidenceValue value) => value is EvidenceText text && ActorId(text.Value) is not null
        && TraceFields.OptionalInteger(text.Value) is BigInteger number && number < BigInteger.One << 64;

    public bool ObserveLifecycle(string line, int lineNumber, long timestampMs)
    {
        var fields = TraceFields.Extract(line);
        ObserveModifiers(line, fields);
        return ObserveLifecycle(line.Contains(" BUFF_START ", StringComparison.Ordinal) ? "start"
            : line.Contains(" BUFF_END ", StringComparison.Ordinal) ? "end" : null, fields, lineNumber, timestampMs);
    }

    public bool ObserveLifecycle(string? phase, IReadOnlyDictionary<string, string> fields, int lineNumber, long timestampMs)
    {
        BuffRecord? current = null;
        if (phase == "start")
        {
            var owner = fields.GetValueOrDefault("owner") ?? "";
            var ownerKey = ActorIdentity.CharacterKey(owner);
            var enemy = ActorIdentity.EnemyKey(owner);
            var source = ActorIdentity.CharacterKey(fields.GetValueOrDefault("src"));
            var raw = Normalize(fields.GetValueOrDefault("id"));
            var hint = catalog.Hint(raw);
            var rejected = hint is { Fields.Count: > 0 } && !PacketBuffCatalog.Applies(hint, ownerKey, source, ActiveSuits, ActiveWeapons);
            var key = catalog.Canonical(raw, ownerKey, source, ActiveSuits, ActiveWeapons);
            if (source is null && ownerKey is null && enemy is null) { PendingRecord = null; return true; }
            foreach (var actor in new[] { source, ownerKey }.OfType<string>())
                Party.ObserveCharacter(actor, characterName(actor));
            PendingModifiers.Remove(key, out var modifiers);
            if ((modifiers is null || modifiers.Count == 0) && raw != key) PendingModifiers.Remove(raw, out modifiers);
            modifiers ??= [];
            var rawUid = fields.GetValueOrDefault("uid") ?? "";
            var invalid = rawUid is "0" or "4294967295";
            current = new(invalid ? "" : rawUid, lineNumber, timestampMs, key, raw)
            {
                ObservationOnly = invalid,
                SourceCharacterKey = source, SourceCharacterName = characterName(source) ?? source,
                SourceWeaponTemplate = source is null ? null : ActiveWeapons.GetValueOrDefault(source),
                RawSourceCharacterKey = source, RawSourceCharacterName = characterName(source) ?? source,
                RawSource = fields.GetValueOrDefault("src"),
                TargetCharacterKey = ownerKey, TargetCharacterName = characterName(ownerKey) ?? ownerKey,
                TargetEnemyKey = enemy, TargetEnemyName = enemyName(enemy) ?? enemy,
                OwnerRaw = owner, TargetActorId = ActorId(fields.GetValueOrDefault("ownerId")),
                SourceActorId = ActorId(fields.GetValueOrDefault("srcId")),
                PacketMapping = !rejected && hint is { Fields.Count: > 0 } ? hint : null,
                PacketMappingRejected = rejected, RawDurationMs = TraceFields.DurationMs(fields.GetValueOrDefault("dur")),
                BlackboardKeys = modifiers.Where(row => row.BlackboardKey.Length > 0).Select(row => row.BlackboardKey).ToList(),
                AttributeTypes = modifiers.Where(row => row.AttributeType.Length > 0).Select(row => row.AttributeType).ToList(),
                AttributeModifiers = modifiers, IsWeaponBuff = Regex.IsMatch(key, @"^buff_wpn_[a-z]+_\d+_"),
            };
            ApplyDuration(current);
            if (current.Uid.Length > 0 && ActiveByUid.TryGetValue(current.Uid, out var existing)) UpdateSnapshot(existing, current);
            Records.Add(current);
            projectionChanges?.Add(current);
            if (SkillIdentityCatalog.IsDigitText(raw) && source is not null)
            {
                if (!RecentNumericBySource.TryGetValue(source, out var rows)) RecentNumericBySource[source] = rows = [];
                rows.Add(current);
                if (rows.Count > 128) rows.RemoveRange(0, rows.Count-128);
            }
            if (current.Uid.Length > 0) ActiveByUid[current.Uid] = current;
        }
        else if (phase == "end" && fields.GetValueOrDefault("uid") is { Length: > 0 } uid)
        {
            foreach (var unresolved in UnresolvedActions)
                if (BuffEvidence.String(unresolved.Get("uid")) == uid && unresolved.Get("end_ts_ms") is EvidenceNull)
                {
                    unresolved.Set("end_ts_ms", new EvidenceInteger(timestampMs));
                    unresolved.Set("end_line_no", new EvidenceInteger(lineNumber));
                }
            if (ActiveByUid.Remove(uid, out current))
            {
                MarkProjectionChanged(current);
                current.EndTimestampMs = timestampMs;
                current.EndLineNumber = lineNumber;
            }
        }
        PendingRecord = current;
        return false;
    }

    internal void ObserveModifiers(string line, IReadOnlyDictionary<string, string> fields)
    {
        if (line.Contains(" ATTR_MOD ", StringComparison.Ordinal) || line.Contains(" DMG_MOD ", StringComparison.Ordinal))
            ObserveModifier(fields);
    }

    public void ObserveModifier(IReadOnlyDictionary<string, string> fields)
    {
        var key = Normalize(fields.GetValueOrDefault("buff"));
        if (!PendingModifiers.TryGetValue(key, out var rows)) PendingModifiers[key] = rows = [];
        rows.Add(new(fields.GetValueOrDefault("attrType") ?? "", fields.GetValueOrDefault("bbKey") ?? "",
            fields.GetValueOrDefault("useKey") is { Length: > 0 } useKey ? useKey : "0", TraceFields.PositiveRate(fields.GetValueOrDefault("val"))));
    }

    private void UpdateSnapshot(BuffRecord previous, BuffRecord current)
    {
        MarkProjectionChanged(previous);
        current.PreviousSnapshot = previous;
        current.PreviousSnapshotBoundary = (previous.SnapshotEndTimestampMs, previous.SnapshotEndLineNumber);
        previous.SnapshotEndTimestampMs = current.TimestampMs;
        previous.SnapshotEndLineNumber = current.LineNumber;
        current.SnapshotUpdate = true;
        current.InstanceStartLineNumber = previous.InstanceStartLineNumber;
        current.SourceWeaponTemplate = previous.SourceWeaponTemplate;
        static bool Different(string? a, string? b) => !string.IsNullOrEmpty(a) && !string.IsNullOrEmpty(b) && a != b;
        current.LiveIdentityConflict = previous.LiveIdentityConflict
            || Different(previous.SourceActorId, current.SourceActorId) || Different(previous.TargetActorId, current.TargetActorId)
            || Different(previous.SourceCharacterKey, current.SourceCharacterKey) || Different(previous.TargetCharacterKey, current.TargetCharacterKey)
            || Different(previous.TargetEnemyKey, current.TargetEnemyKey)
            || roots.ContainsKey(previous.EventKey) && roots.ContainsKey(current.EventKey) && previous.EventKey != current.EventKey;
        if (current.LiveIdentityConflict) return;
        current.SourceActorId = Empty(current.SourceActorId, previous.SourceActorId);
        current.TargetActorId = Empty(current.TargetActorId, previous.TargetActorId);
        current.SourceCharacterKey = Empty(current.SourceCharacterKey, previous.SourceCharacterKey);
        current.TargetCharacterKey = Empty(current.TargetCharacterKey, previous.TargetCharacterKey);
        current.TargetEnemyKey = Empty(current.TargetEnemyKey, previous.TargetEnemyKey);
        current.SourceSkillKey = Empty(current.SourceSkillKey, previous.SourceSkillKey);
        current.SourceSkillFamilyKey = Empty(current.SourceSkillFamilyKey, previous.SourceSkillFamilyKey);
        current.EnableObservations = previous.EnableObservations;
        current.CreationObservations = previous.CreationObservations.Select(row => row.Copy()).ToList();
        current.AttributeRefreshSnapshots = previous.AttributeRefreshSnapshots;
        if (previous.DynamicState is not null)
        {
            current.DynamicState = previous.DynamicState.Copy();
            current.DynamicSeenContexts = new(previous.DynamicSeenContexts);
        }
        current.DynamicUnresolvedKeys.UnionWith(previous.DynamicUnresolvedKeys);
        current.DynamicIdentityConflict = previous.DynamicIdentityConflict;
        current.ConflictingEnableState = previous.ConflictingEnableState;
        if (previous.EventKey != current.EventKey) return;
        current.BlackboardValues = new(previous.BlackboardValues, StringComparer.Ordinal);
        current.BlackboardKeys = new(previous.BlackboardKeys);
        current.OriginObservations = previous.OriginObservations?.Select(row => row.Copy()).ToList() ?? [];
        if (current.AttributeModifiers.Count == 0)
        {
            current.AttributeModifiers = new(previous.AttributeModifiers);
            current.AttributeTypes = new(previous.AttributeTypes);
        }
    }

    private static string? Empty(string? current, string? previous) => string.IsNullOrEmpty(current) ? previous : current;

    public bool ObserveBlackboard(string line)
    {
        if (!line.Contains(" BB[", StringComparison.Ordinal)) return false;
        ObserveBlackboard(TraceFields.Extract(line).ToDictionary(pair => pair.Key, pair => TraceFields.OptionalFloat(pair.Value)));
        return true;
    }

    public void ObserveBlackboard(IReadOnlyDictionary<string, double?> values)
    {
        if (PendingRecord is not { } record) return;
        MarkProjectionChanged(record);
        record.BlackboardKeys.AddRange(values.Keys);
        foreach (var (key, raw) in values)
            if (raw is double value) { record.BlackboardValues[key] = value; record.ObservedBlackboardValues[key] = value; }
        ApplyDuration(record);
        var triggerKeys = new[] { "phy_dmg_up", "final_phy_dmg_up", "shatter_dmg", "consumed_layer" };
        if (SkillIdentityCatalog.IsDigitText(record.RawEventKey) && record.PacketMapping is null
            && record.OwnerRaw.StartsWith("eny_", StringComparison.Ordinal) && record.RawSource?.StartsWith("chr_", StringComparison.Ordinal) == true
            && triggerKeys.All(key => record.BlackboardKeys.Concat(record.BlackboardValues.Keys).Any(item => item.ToLowerInvariant() == key)))
            record.EventKey = record.RawEventKey;
    }

    private void ApplyDuration(BuffRecord record)
    {
        if (!roots.TryGetValue(record.EventKey, out var root) || root.Get("lifeType") is not EvidenceText { Value: "Limited" or "Infinity" } mode) return;
        record.LifetimeMode = mode.Value;
        if (record.RawDurationMs is not null || mode.Value == "Infinity" || root.Get("duration") is not EvidenceObject duration) return;
        var key = PacketBuffCatalog.Text(duration.Get("blackboardKey"));
        var seconds = duration.Get("useBlackboardKey") switch
        {
            EvidenceBoolean { Value: true } when key.Length > 0 => record.BlackboardValues.TryGetValue(key, out var value) ? value : (double?)null,
            EvidenceBoolean { Value: false } => BuffEvidence.OptionalFloat(duration.Get("value")),
            _ => null,
        };
        if (seconds is null || seconds < 0) return;
        record.RawDurationMs = new BigInteger(Math.Round(seconds.Value*1000, MidpointRounding.ToEven));
        record.RawDurationSource = duration.Get("useBlackboardKey") is EvidenceBoolean { Value: true } ? "official_duration_blackboard" : "official_duration_constant";
    }

    public BigInteger EndAt(BuffRecord record, long battleEndMs)
    {
        return BuffLifetime.EndAt(record.TimestampMs,record.EndTimestampMs,record.RawDurationMs,battleEndMs,
            roots.TryGetValue(Normalize(record.EventKey),out var root) && root.Get("lifeType") is EvidenceText { Value:"Infinity" },
            record.SnapshotEndTimestampMs);
    }

    internal void Unresolved(string reason, int lineNumber, long timestampMs, string? uid = null)
    {
        var row = new BuffObservation(BuffEvidence.Object(("reason", new EvidenceText(reason)),
            ("line_no", new EvidenceInteger(lineNumber)), ("ts_ms", new EvidenceInteger(timestampMs))));
        if (uid is not null) row.Set("uid", new EvidenceText(uid));
        UnresolvedActions.Add(row);
    }
}
