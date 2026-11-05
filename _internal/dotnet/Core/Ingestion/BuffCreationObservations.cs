using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

internal sealed class BuffCreationObservations(BuffInstanceState state)
{
    private EvidenceValue ResolveNumber(EvidenceValue number) => state.Numbers.TryGetValue(PythonDisplay.String(number), out var value)
        ? new EvidenceText(value) : EvidenceNull.Value;

    private EvidenceValue Template(BuffObservation observation)
    {
        var template = observation.Get("buffTemplate");
        if (template is EvidenceText text && SkillIdentityCatalog.IsDigitText(text.Value)) template = ResolveNumber(template);
        List<EvidenceValue> reports = [];
        var number = observation.Get("buffNumId");
        if (number is not EvidenceNull && !EvidenceJson.PythonEquals(number, new EvidenceInteger(0)))
        {
            if (number is not EvidenceInteger integer || integer.Value < 0) throw new FormatException();
            reports.Add(ResolveNumber(number));
        }
        else if (number is EvidenceBoolean) throw new FormatException();
        var literal = observation.Get("buffId");
        if (literal is not EvidenceNull and not EvidenceText { Value: "" })
        {
            if (literal is not EvidenceText) throw new FormatException();
            reports.Add(literal);
        }
        if (observation.Get("buffTemplateId") is not EvidenceNull)
        {
            var obj = BuffEvidence.Pairs(observation.Get("buffTemplateId"));
            observation.Set("buffTemplateId", obj);
            var choices = new[] { "int_id", "str_id" }.Where(obj.Fields.ContainsKey).ToArray();
            if (choices.Length != 1 || obj.Get("type") is not (EvidenceInteger { Value.IsOne: true } or EvidenceText { Value: "Buff" })) throw new FormatException();
            var value = obj.Get(choices[0]);
            if (choices[0] == "int_id")
            {
                if (value is not EvidenceInteger id || id.Value < 0) throw new FormatException();
                reports.Add(ResolveNumber(value));
            }
            else
            {
                if (value is not EvidenceText { Value.Length: > 0 }) throw new FormatException();
                reports.Add(value);
            }
        }
        if (reports.Count == 0 || reports.Any(value => !EvidenceJson.PythonEquals(value, template))) throw new FormatException();
        return template;
    }

    public void Observe(EvidenceObject payload, int lineNumber, long timestampMs)
    {
        var observation = new BuffObservation(payload);
        var uid = BuffEvidence.String(observation.Get("buffUid"));
        state.ActiveByUid.TryGetValue(uid ?? "", out var record);
        if (record is not null) state.MarkProjectionChanged(record);
        var template = Template(observation);
        var sourceEvent = BuffEvidence.String(observation.Get("sourceEvent"));
        var session = BuffEvidence.String(observation.Get("sessionId"));
        var sequence = BuffEvidence.Integer(observation.Get("operationSeq"));
        var source = BuffEvidence.String(observation.Get("sourceActorId"));
        var target = BuffEvidence.String(observation.Get("targetActorId"));
        if (record is not null && BuffEvidence.String(template) == record.EventKey && sourceEvent == "BattleOpTriggerAction"
            && source == record.SourceActorId && target == record.TargetActorId && session is { Length: > 0 } && sequence >= 0)
        {
            var context = new BuffObservation(BuffEvidence.Object(("session_id", new EvidenceText(session)), ("operation_seq", new EvidenceInteger(sequence.Value))));
            var contexts = record.PacketCreationContexts ??= [];
            if (!contexts.Any(row => EvidenceJson.PythonEquals(row.Evidence, context.Evidence))) contexts.Add(context);
        }
        if (observation.Get("schemaVersion") is not EvidenceInteger { Value.IsOne: true } || record is null
            || BuffEvidence.String(template) != record.EventKey || sourceEvent is not ("BattleOpTriggerAction" or "BattleOpAddBuff")
            || string.IsNullOrEmpty(session) || sequence is null || sequence < 0
            || observation.Get("generationScope") is not EvidenceText { Value: "operation_owner" }
            || new[] { "buffUid", "targetActorId", "operationOwnerId" }.Any(key => !BuffInstanceState.ValidPacketId(observation.Get(key)))
            || uid is "0" or "4294967295" || target != record.TargetActorId
            || !string.IsNullOrEmpty(record.SourceActorId) && source != record.SourceActorId) throw new FormatException();

        var observedValues = new Dictionary<string, double>(record.ObservedBlackboardValues, StringComparer.Ordinal);
        HashSet<string> conflicts = new(StringComparer.Ordinal);
        if (observation.Get("assignedItems") is EvidenceArray assigned)
        {
            List<EvidenceValue> decoded = [];
            observedValues.Clear();
            foreach (var raw in assigned.Items)
            {
                EvidenceObject item;
                try { item = BuffEvidence.Pairs(raw); }
                catch (FormatException) { conflicts.Add("*"); continue; }
                decoded.Add(item);
                if (item.Get("target_key") is not EvidenceText { Value.Length: > 0 } key) { conflicts.Add("*"); continue; }
                if (item.Get("use_direct_value") is not EvidenceBoolean { Value: true }
                    || BuffEvidence.FiniteNumber(item.Get("numeric_value")) is not double operand) { conflicts.Add(key.Value); continue; }
                if (observedValues.TryGetValue(key.Value, out var previous) && BitConverter.DoubleToUInt64Bits(previous) != BitConverter.DoubleToUInt64Bits(operand)) conflicts.Add(key.Value);
                observedValues[key.Value] = operand;
            }
            observation.Set("assignedItems", new EvidenceArray(decoded));
            foreach (var key in conflicts) observedValues.Remove(key);
            if (conflicts.Contains("*")) observedValues.Clear();
        }
        var owner = BuffEvidence.String(observation.Get("operationOwnerId"))!;
        var generation = observation.Get("operationGeneration");
        if (generation is EvidenceObject or EvidenceArray) throw new FormatException();
        var creationKey = new BuffCreationKey(new(session, owner, generation), sequence.Value, uid!);
        state.CreationHistory.TryGetValue(creationKey, out var historical);
        var pending = record.DynamicState;
        static BuffOperationContext Context(BuffObservation row) => new(BuffEvidence.String(row.Get("sessionId"))!,
            BuffEvidence.String(row.Get("operationOwnerId"))!, row.Get("operationGeneration"));
        var stale = record.CreationObservations.Any(row => Context(row) == creationKey.Context && BuffEvidence.Integer(row.Get("operationSeq")) > sequence)
            || pending is not null && pending.Context == creationKey.Context && sequence < pending.LastSequence;
        var conflicting = historical is not null && observedValues.Count > 0 && historical.Observation.Get("bb_values") is EvidenceObject { Fields.Count: > 0 } oldValues
            && !EvidenceJson.PythonEquals(oldValues, BuffEvidence.Blackboard(observedValues));
        if (historical is not null || stale)
        {
            var incoming = record;
            if (record.PreviousSnapshot is { } prior)
            {
                state.MarkProjectionChanged(prior);
                var boundary = record.PreviousSnapshotBoundary!.Value;
                prior.SnapshotEndTimestampMs = boundary.Time;
                prior.SnapshotEndLineNumber = boundary.Line;
                state.ActiveByUid[uid!] = prior;
                state.PendingRecord = prior;
                record = prior;
            }
            else if (historical is not null && historical.InstanceStartLineNumber != record.InstanceStartLineNumber)
            {
                state.ActiveByUid.Remove(uid!);
                state.PendingRecord = null;
                record = historical.Record;
            }
            state.MarkProjectionChanged(record);
            if (!ReferenceEquals(record, incoming)) state.RemoveRecord(incoming);
            observation.Set("ts_ms", new EvidenceInteger(timestampMs));
            observation.Set("line_no", new EvidenceInteger(lineNumber));
            observation.Set("bb_values", BuffEvidence.Blackboard(observedValues));
            observation.Set("status", new EvidenceText(conflicting ? "conflicting" : historical is not null ? "duplicate" : "out_of_order"));
            (record.RepeatedCreationObservations ??= []).Add(observation);
            if (conflicting)
            {
                var affected = historical?.Record ?? record;
                state.MarkProjectionChanged(affected);
                affected.DynamicUnresolvedKeys.Add("*");
                affected.DynamicState?.InvalidKeys.Add("*");
                foreach (var snapshot in affected.AttributeRefreshSnapshots)
                    if (BuffEvidence.Integer(snapshot.Get("operation_seq")) >= sequence) snapshot.Set("status", new EvidenceText("conflicting_creation_parameters"));
            }
            return;
        }
        if (record.CreationObservations.Any(row => BuffEvidence.String(row.Get("sessionId")) != session))
        {
            record.DynamicIdentityConflict = true;
            throw new FormatException();
        }
        observation.Set("ts_ms", new EvidenceInteger(timestampMs));
        observation.Set("line_no", new EvidenceInteger(lineNumber));
        observation.Set("bb_values", BuffEvidence.Blackboard(observedValues));
        observation.Set("bb_conflicts", new EvidenceArray(conflicts.Order(StringComparer.Ordinal).Select(key => (EvidenceValue)new EvidenceText(key)).ToArray()));
        observation.Set("bb_observation_source", new EvidenceText("unverified_creation_bb"));
        record.CreationObservations.Add(observation);
        state.CreationHistory[creationKey] = new(observation, record, record.InstanceStartLineNumber);
        record.ObservedBlackboardValues.Clear();
        if (pending is not null && !(owner == pending.Context.OwnerId && !EvidenceJson.PythonEquals(generation, pending.Context.Generation)))
        {
            foreach (var (key, value) in observedValues)
            {
                pending.Values[key] = value;
                pending.InvalidKeys.Remove(key);
                record.DynamicUnresolvedKeys.Remove(key);
                pending.ValueSources[key] = BuffEvidence.Object(("kind", new EvidenceText("creation_observation")),
                    ("creation_key", new EvidenceArray([new EvidenceText(session), new EvidenceText(owner), generation, new EvidenceInteger(sequence.Value), new EvidenceText(uid!)])));
            }
            pending.InvalidKeys.UnionWith(conflicts);
        }
    }
}
