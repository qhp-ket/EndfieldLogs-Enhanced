using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Observed keyword rates require both a bound creation and a reviewed typed-origin approval.</summary>
public sealed class BuffKeywordObservations(BuffInstanceState state, Func<BuffRecord, EvidenceObject?> approve)
{
    private static bool PacketId(EvidenceValue value) => value is EvidenceText text && Regex.IsMatch(text.Value, @"\A[1-9][0-9]*\z")
        && TraceFields.OptionalInteger(text.Value) is BigInteger number && number < BigInteger.One << 64;
    private static void Require(bool condition, string reason)
    {
        if (!condition) throw new FormatException(reason);
    }

    public bool Observe(string line, int lineNumber, long timestampMs)
    {
        var marker = line.Contains(" BUFF_KEYWORD_UPDATE_UNRESOLVED ", StringComparison.Ordinal)
            ? " BUFF_KEYWORD_UPDATE_UNRESOLVED " : " BUFF_KEYWORD_UPDATE ";
        var position = line.IndexOf(marker, StringComparison.Ordinal);
        if (position < 0) return false;
        return Observe(() =>
        {
            var encoded = line[(position + marker.Length)..];
            var parsed = EvidenceJson.ParseWithPairs(encoded);
            Require(encoded.StartsWith('{') && parsed is EvidenceObject, "invalid_keyword_observation");
            return (EvidenceObject)parsed;
        }, lineNumber, timestampMs);
    }

    public bool Observe(EvidenceObject observation, int lineNumber, long timestampMs) => Observe(() => observation, lineNumber, timestampMs);

    private bool Observe(Func<EvidenceObject> read, int lineNumber, long timestampMs)
    {
        BuffRecord? record = null;
        EvidenceObject? payload = null;
        var bound = false;
        try
        {
            payload = read();
            Require(payload.SourcePairs is null || payload.SourcePairs.Count == payload.Fields.Count, "duplicate_keyword_fields");
            var uid = BuffEvidence.String(payload.Get("buffUid"));
            record = uid is null ? null : state.ActiveByUid.GetValueOrDefault(uid);
            var session = BuffEvidence.String(payload.Get("sessionId"));
            var sequence = payload.Get("operationSeq") as EvidenceInteger;
            var generation = payload.Get("generation") as EvidenceInteger;
            var added = payload.Get("addedBuffNumId") as EvidenceInteger;
            Require(payload.Get("schemaVersion") is EvidenceInteger { Value.IsOne: true }
                && payload.Get("operationPayloadCase") is EvidenceText { Value: "trigger_keyword_op_data" }
                && record is not null && !record.LiveIdentityConflict && !string.IsNullOrEmpty(session)
                && sequence is { Value.Sign: >= 0 } && generation is { Value.Sign: >= 0 } && generation.Value < BigInteger.One << 32
                && added is { Value.Sign: >= 0 } && PacketId(payload.Get("buffUid")) && PacketId(payload.Get("ownerId"))
                && record.TargetActorId == BuffEvidence.String(payload.Get("ownerId"))
                && (timestampMs > record.TimestampMs || timestampMs == record.TimestampMs && lineNumber >= record.LineNumber), "unbound_keyword_identity");
            var anchors = record!.CreationObservations;
            Require(anchors.Any(row => BuffEvidence.String(row.Get("sessionId")) == session)
                && !anchors.Any(row => row.Get("sessionId") is not EvidenceNull && BuffEvidence.String(row.Get("sessionId")) != session),
                "keyword_creation_session_mismatch");
            Require(!anchors.Any(row => BuffEvidence.String(row.Get("sessionId")) == session
                && row.Get("operationSeq") is EvidenceInteger operation && operation.Value >= sequence!.Value
                && row.Get("line_no") is EvidenceInteger number && number.Value >= record.LineNumber), "keyword_update_before_creation");
            var approved = approve(record);
            Require(approved?.Get("_rdps_whitelist_keys") is EvidenceArray { Items.Count: 1 } keys
                && keys.Items[0] is EvidenceText { Value: "buff_chr_0023_antal_normal_fragile" }
                && approved.Get("_keyword_origin") is EvidenceArray { Items.Count: > 0 }, "keyword_update_without_approved_origin");
            bound = true;
            var rows = payload.Get("modify");
            var signature = new BuffKeywordUpdate(generation!.Value, added!.Value, NormalizedRows(rows));
            record.KeywordSeenUpdates ??= [];
            record.KeywordRateSnapshots ??= [];
            if (record.KeywordSeenUpdates.TryGetValue(sequence!.Value, out var seen))
            {
                if (!seen.SameAs(signature))
                {
                    foreach (var previous in record.KeywordRateSnapshots.Where(row => EvidenceJson.PythonEquals(row.Get("operation_seq"), sequence)))
                        previous.Set("status", new EvidenceText("conflicting_keyword_update"));
                    throw new FormatException("conflicting_keyword_update");
                }
                return true;
            }
            record.KeywordSeenUpdates[sequence.Value] = signature;
            Require(!Truthy(payload.Get("validationErrors")), "unresolved_keyword_packet_fields");
            var count = rows switch { EvidenceArray list => list.Items.Count, EvidenceObject obj => obj.SourcePairs?.Count ?? obj.Fields.Count, _ => -1 };
            Require(count == 1, "invalid_keyword_modify_rows");
            var rawRow = rows is EvidenceArray array ? array.Items[0] : null;
            Require(rawRow is EvidenceObject or EvidenceArray { Items.Count: 0 }, "invalid_keyword_modify_row");
            var row = rawRow as EvidenceObject ?? new EvidenceObject(new Dictionary<string, EvidenceValue>());
            Require((row.SourcePairs is null || row.SourcePairs.Count == row.Fields.Count)
                && row.Get("configIndex") is EvidenceInteger { Value.IsZero: true }, "invalid_keyword_config_index");
            var rate = BuffEvidence.FiniteNumber(row.Get("rateAfter"));
            Require(rate is >= 0, "invalid_keyword_rate");
            var addedId = state.Numbers.GetValueOrDefault(added.Value.ToString(System.Globalization.CultureInfo.InvariantCulture));
            var parent = state.Roots.GetValueOrDefault("buff_chr_0023_antal_tageffect");
            foreach (var origin in ((EvidenceArray)approved!.Get("_keyword_origin")).Items.OfType<EvidenceObject>())
            {
                List<EvidenceObject> selected = [];
                Stack<EvidenceValue> pending = [];
                if (parent is not null) pending.Push(parent);
                while (pending.TryPop(out var node))
                {
                    if (node is EvidenceObject obj)
                    {
                        if (obj.Get("$type") is EvidenceText { Value: "Beyond.Gameplay.Core.VulnerableAction.Data" }
                            && EvidenceJson.PythonEquals(obj.Get("serverActionIndex"), origin.Get("actionId"))) selected.Add(obj);
                        foreach (var value in obj.Fields.Values) pending.Push(value);
                    }
                    else if (node is EvidenceArray list) foreach (var value in list.Items) pending.Push(value);
                }
                var enhancement = selected.Count == 1 && selected[0].Get("enhancingList") is EvidenceArray { Items.Count: 1 } enhancing
                    ? enhancing.Items[0] as EvidenceObject : null;
                Require(enhancement?.Get("operationType") is EvidenceText { Value: "Add" }
                    && enhancement.Get("value") is EvidenceObject configuration
                    && configuration.Get("useBlackboardKey") is EvidenceBoolean { Value: true }
                    && configuration.Get("blackboardKey") is EvidenceText { Value: "potential_5_rate" }
                    && enhancement.Get("buffIds") is EvidenceArray ids && ids.Items.Any(id => addedId is null
                        ? id is EvidenceNull : id is EvidenceText text && text.Value == addedId), "keyword_marker_not_in_current_config");
            }
            record.KeywordRateSnapshots.Add(Snapshot(sequence.Value, lineNumber, timestampMs, session!, generation.Value, rate, "observed", addedId));
        }
        catch (FormatException failure)
        {
            if (bound && record is not null && payload?.Get("operationSeq") is EvidenceInteger sequence)
            {
                record.KeywordRateSnapshots ??= [];
                if (!record.KeywordRateSnapshots.Any(row => EvidenceJson.PythonEquals(row.Get("operation_seq"), sequence)))
                    record.KeywordRateSnapshots.Add(Snapshot(sequence.Value, lineNumber, timestampMs,
                        BuffEvidence.String(payload.Get("sessionId"))!, ((EvidenceInteger)payload.Get("generation")).Value,
                        null, "unresolved_keyword_update", null));
            }
            state.UnresolvedActions.Add(new(BuffEvidence.Object(("ts_ms", new EvidenceInteger(timestampMs)),
                ("line_no", new EvidenceInteger(lineNumber)), ("reason", new EvidenceText(failure.Message)),
                ("source", new EvidenceText("BUFF_KEYWORD_UPDATE")))));
        }
        finally
        {
            if (record is not null) state.MarkProjectionChanged(record);
        }
        return true;
    }

    private static bool Truthy(EvidenceValue value) => value switch
    {
        EvidenceNull => false, EvidenceBoolean flag => flag.Value, EvidenceInteger integer => !integer.Value.IsZero,
        EvidenceReal real => real.Value != 0, EvidenceText text => text.Value.Length > 0,
        EvidenceArray array => array.Items.Count > 0, EvidenceObject obj => obj.Fields.Count > 0,
        _ => false,
    };

    private static EvidenceValue NormalizedRows(EvidenceValue rows) => rows is EvidenceArray array
        ? new EvidenceArray(array.Items.Select(row => row switch
        {
            EvidenceObject obj => (EvidenceValue)new EvidenceObject(obj.Fields.ToDictionary(pair => pair.Key, pair => BuffEvidence.Hook(pair.Value), StringComparer.Ordinal)),
            EvidenceArray { Items.Count: 0 } => new EvidenceObject(new Dictionary<string, EvidenceValue>()),
            _ => BuffEvidence.Hook(row),
        }).ToArray()) : BuffEvidence.Hook(rows);

    private static BuffObservation Snapshot(BigInteger sequence, int line, long time, string session,
        BigInteger generation, double? rate, string status, string? addedId)
    {
        var snapshot = new BuffObservation(BuffEvidence.Object(("operation_seq", new EvidenceInteger(sequence)),
            ("line_no", new EvidenceInteger(line)), ("ts_ms", new EvidenceInteger(time)), ("session_id", new EvidenceText(session)),
            ("generation", new EvidenceInteger(generation)), ("rate_after", rate is double value ? new EvidenceReal(value) : EvidenceNull.Value),
            ("status", new EvidenceText(status))));
        if (status == "observed")
        {
            snapshot.Set("added_buff_id", BuffEvidence.Text(addedId));
            snapshot.Set("config_index", new EvidenceInteger(0));
        }
        return snapshot;
    }
}
