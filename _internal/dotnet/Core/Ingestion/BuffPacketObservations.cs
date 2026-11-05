using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Bind typed packet state to the currently live instance without inventing identity.</summary>
public sealed class BuffPacketObservations(BuffInstanceState state, Func<BuffRecord, EvidenceObject?>? effectApproval = null)
{
    private readonly BuffKeywordObservations keywords = new(state, effectApproval ?? (_ => null));
    public bool Observe(string kind, EvidenceObject payload, int lineNumber, long timestampMs)
    {
        if (kind == "buff_keyword") return keywords.Observe(payload, lineNumber, timestampMs);
        var reason = kind switch
        {
            "buff_enable" => "unbound_buff_enable_state", "buff_creation" => "unbound_buff_creation_observation",
            "buff_origin" => "unbound_buff_origin", _ => throw new InvalidDataException("Expected BUFF packet event"),
        };
        try
        {
            if (kind == "buff_enable") Enable(payload, lineNumber, timestampMs);
            else if (kind == "buff_creation") new BuffCreationObservations(state).Observe(payload, lineNumber, timestampMs);
            else Origin(payload, lineNumber);
        }
        catch (FormatException) { state.Unresolved(reason, lineNumber, timestampMs); }
        return true;
    }

    public void ObserveUnresolved(IReadOnlyDictionary<string, string> fields, int lineNumber, long timestampMs)
    {
        state.UnresolvedActions.Add(new(BuffEvidence.Object(
            ("uid", BuffEvidence.Text(fields.GetValueOrDefault("uid"))), ("seq", BuffEvidence.Text(fields.GetValueOrDefault("seq"))),
            ("ts_ms", new EvidenceInteger(timestampMs)), ("line_no", new EvidenceInteger(lineNumber)),
            ("trigger_type", BuffEvidence.Text(fields.GetValueOrDefault("triggerType"))), ("action_id", BuffEvidence.Text(fields.GetValueOrDefault("actionId"))),
            ("target_actor_id", BuffEvidence.Text(fields.GetValueOrDefault("ownerId"))), ("source_actor_id", BuffEvidence.Text(fields.GetValueOrDefault("srcId"))),
            ("reason", new EvidenceText("unresolved_buff_action_phase")))));
    }
    public bool Observe(string line, int lineNumber, long timestampMs)
    {
        const string unresolved = " BUFF_ACTION_UNRESOLVED ", enable = " BUFF_ENABLE ", origin = " BUFF_ORIGIN ", creation = " BUFF_CREATE_OBSERVED ";
        if (line.Contains(unresolved, StringComparison.Ordinal))
        {
            ObserveUnresolved(TraceFields.Extract(line), lineNumber, timestampMs);
            return true;
        }
        if (keywords.Observe(line, lineNumber, timestampMs)) return true;
        if (line.IndexOf(enable, StringComparison.Ordinal) is >= 0 and var enableIndex)
        {
            try { Enable(BuffEvidence.ParseObject(line[(enableIndex+enable.Length)..]), lineNumber, timestampMs); }
            catch (FormatException) { state.Unresolved("unbound_buff_enable_state", lineNumber, timestampMs); }
            return true;
        }
        if (line.IndexOf(creation, StringComparison.Ordinal) is >= 0 and var creationIndex)
        {
            try { new BuffCreationObservations(state).Observe(BuffEvidence.ParseObject(line[(creationIndex+creation.Length)..]), lineNumber, timestampMs); }
            catch (FormatException) { state.Unresolved("unbound_buff_creation_observation", lineNumber, timestampMs); }
            return true;
        }
        if (line.IndexOf(origin, StringComparison.Ordinal) is >= 0 and var originIndex)
        {
            try { Origin(BuffEvidence.ParseObject(line[(originIndex+origin.Length)..]), lineNumber); }
            catch (FormatException) { state.Unresolved("unbound_buff_origin", lineNumber, timestampMs); }
            return true;
        }
        return false;
    }

    private void Enable(EvidenceObject payload, int lineNumber, long timestampMs)
    {
        var uid = BuffEvidence.String(payload.Get("buffUid"));
        if (payload.Get("schemaVersion") is not EvidenceInteger { Value.IsOne: true }
            || payload.Get("enabled") is not EvidenceBoolean enabled || uid is null || !state.ActiveByUid.TryGetValue(uid, out var record)
            || payload.Get("ownerId") is not EvidenceText owner || owner.Value != record.TargetActorId
            || payload.Get("operationSeq") is not EvidenceInteger sequence || sequence.Value < 0) throw new FormatException();
        state.MarkProjectionChanged(record);
        if (record.EnableObservations.Any(row => EvidenceJson.PythonEquals(row.Get("operationSeq"), sequence)
            && !EvidenceJson.PythonEquals(row.Get("enabled"), enabled)))
        {
            record.ConflictingEnableState = true;
            state.Unresolved("conflicting_buff_enable_state", lineNumber, timestampMs, uid);
        }
        var observed = new BuffObservation(payload);
        observed.Set("ts_ms", new EvidenceInteger(timestampMs));
        observed.Set("line_no", new EvidenceInteger(lineNumber));
        record.EnableObservations.Add(observed);
    }

    private void Origin(EvidenceObject payload, int lineNumber)
    {
        var uid = BuffEvidence.String(payload.Get("buffUid"));
        if (payload.Get("schemaVersion") is not EvidenceInteger { Value.IsOne: true }
            || uid is null || !state.ActiveByUid.TryGetValue(uid, out var record)
            || payload.Get("buffTemplate") is not EvidenceText template || template.Value != record.EventKey && template.Value != record.RawEventKey
            || new[] { "buffUid", "sourceActorId", "targetActorId", "environmentInstId" }.Any(key => !BuffInstanceState.ValidPacketId(payload.Get(key)))
            || BuffEvidence.String(payload.Get("sourceActorId")) != record.SourceActorId
            || BuffEvidence.String(payload.Get("targetActorId")) != record.TargetActorId
            || payload.Get("actionId") is not EvidenceInteger action || action.Value < 0
            || payload.Get("operationSeq") is not EvidenceInteger sequence || sequence.Value < 0
            || payload.Get("triggerType") is not EvidenceInteger { Value.IsZero: true }) throw new FormatException();
        state.MarkProjectionChanged(record);
        var observation = new BuffObservation(payload);
        observation.Set("lineNo", new EvidenceInteger(lineNumber));
        observation.Set("_boundCreateRecord", new EvidenceBoolean(true));
        (record.OriginObservations ??= []).Add(observation);
    }
}
