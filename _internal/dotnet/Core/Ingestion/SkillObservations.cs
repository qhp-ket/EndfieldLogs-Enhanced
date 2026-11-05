namespace EndfieldLogs.Core.Ingestion;

public sealed record AtbObservation(long TimestampMs, int LineNumber, string? CharacterKey, string? OwnerActorId,
    double? Value, double? Delta, double? RecoverySpeed, double? ClientTickMs, string? Reason,
    string? Source, string? OriginalSource);

public sealed class SkillCastObservation(long timestampMs, int lineNumber, string skill, string? owner,
    string? ownerId, string? skillInstanceId, string? skillSource, string? characterKey)
{
    public long TimestampMs { get; } = timestampMs;
    public int LineNumber { get; } = lineNumber;
    public string Skill { get; } = skill;
    public string? Owner { get; } = owner;
    public string? OwnerId { get; } = ownerId;
    public string? SkillInstanceId { get; } = skillInstanceId;
    public string? SkillSource { get; } = skillSource;
    public string? CharacterKey { get; } = characterKey;
    public long? EndTimestampMs { get; internal set; }
    public int? EndLineNumber { get; internal set; }
}

public sealed record RecentSkillCast(long TimestampMs, string Skill, string? Owner, string? SkillInstanceId, string? SkillSource);

/// <summary>Observed values and lifecycle only; energy is never integrated between observations.</summary>
public sealed class SkillObservationState
{
    public List<AtbObservation> AtbObservations { get; } = [];
    public Dictionary<string, List<long>> AtbGainMsByCharacter { get; } = new(StringComparer.Ordinal);
    public List<SkillCastObservation> Casts { get; } = [];
    public Dictionary<string, SkillCastObservation> ActiveCastsByInstance { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, List<RecentSkillCast>> RecentCastsByCharacter { get; } = new(StringComparer.Ordinal);
    public long? FirstPartyActionMs { get; set; }

    public bool Observe(string line, int lineNumber, long timestampMs)
    {
        if (line.Contains(" ATB_UPDATE ", StringComparison.Ordinal))
        {
            var fields = TraceFields.Extract(line);
            var character = ActorIdentity.CharacterKey(fields.GetValueOrDefault("owner"));
            var delta = TraceFields.OptionalFloat(fields.GetValueOrDefault("delta"));
            Observe(new AtbObservation(timestampMs, lineNumber, character, fields.GetValueOrDefault("ownerId"),
                TraceFields.OptionalFloat(fields.GetValueOrDefault("atb")), delta,
                TraceFields.OptionalFloat(fields.GetValueOrDefault("recoverySpeed")),
                TraceFields.OptionalFloat(fields.GetValueOrDefault("tick")), fields.GetValueOrDefault("reason"),
                fields.GetValueOrDefault("source"), fields.GetValueOrDefault("origSource")));
            return true;
        }
        if (line.Contains(" SKILL_CAST_START ", StringComparison.Ordinal))
        {
            var fields = TraceFields.Extract(line);
            var skill = fields.GetValueOrDefault("skill") ?? "";
            var owner = fields.GetValueOrDefault("owner");
            var character = ActorIdentity.CharacterKey(owner, skill);
            var instance = fields.GetValueOrDefault("inst");
            var source = fields.GetValueOrDefault("skillSource");
            if (string.IsNullOrEmpty(source)) source = fields.GetValueOrDefault("skill_source");
            var cast = new SkillCastObservation(timestampMs, lineNumber, skill, owner, fields.GetValueOrDefault("ownerId"),
                instance, source, character);
            BeginCast(cast);
            return true;
        }
        if (line.Contains(" SKILL_CAST_END ", StringComparison.Ordinal))
        {
            var fields = TraceFields.Extract(line);
            EndCast(fields.GetValueOrDefault("inst"), lineNumber, timestampMs);
            return true;
        }
        return false;
    }

    public void Observe(AtbObservation observation)
    {
        AtbObservations.Add(observation);
        if (observation.CharacterKey is { } character && observation.Reason == "AddValue" && observation.Delta > 0)
        {
            if (!AtbGainMsByCharacter.TryGetValue(character, out var rows)) AtbGainMsByCharacter[character] = rows = [];
            rows.Add(observation.TimestampMs);
        }
    }

    public void BeginCast(SkillCastObservation cast)
    {
        Casts.Add(cast);
        if (!string.IsNullOrEmpty(cast.SkillInstanceId)) ActiveCastsByInstance[cast.SkillInstanceId] = cast;
        if (cast.CharacterKey is { } character)
        {
            if (FirstPartyActionMs is null && !ActorIdentity.IsGenericRuntimeSkill(cast.Skill)) FirstPartyActionMs = cast.TimestampMs;
            if (!RecentCastsByCharacter.TryGetValue(character, out var rows)) RecentCastsByCharacter[character] = rows = [];
            rows.Add(new(cast.TimestampMs, cast.Skill, cast.Owner, cast.SkillInstanceId, cast.SkillSource));
            if (rows.Count > 16) rows.RemoveRange(0, rows.Count-16);
        }
    }

    public void EndCast(string? instance, int lineNumber, long timestampMs)
    {
        if (!string.IsNullOrEmpty(instance) && ActiveCastsByInstance.Remove(instance, out var cast))
        {
            cast.EndTimestampMs = timestampMs;
            cast.EndLineNumber = lineNumber;
        }
    }
}
