using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public static class StructuredIdentity
{
    private static void Identity(EvidenceValue value)
    {
        if (value is not EvidenceNull && (value is not EvidenceText text || text.Value.Length == 0 || text.Value.Any(unit => unit is < '0' or > '9')))
            throw new InvalidDataException("Instance identities must be decimal strings");
    }

    public static void Accept(TraceEvent item, ISet<string> partyIds, IDictionary<string, string> squad)
    {
        if (item.Type == "squad")
        {
            if (item.Data.Get("members") is not EvidenceArray rows) throw new InvalidDataException("Expected squad members");
            foreach (var value in rows.Items)
            {
                if (value is not EvidenceObject row || row.Get("template") is not EvidenceText || !row.Fields.ContainsKey("entity_id"))
                    throw new InvalidDataException("Expected squad identity fields");
                Identity(row.Get("entity_id"));
            }
        }
        else if (item.Type is "actor_mapping" or "identity_inference")
        {
            if (!item.Data.Fields.ContainsKey("entity_id") || item.Data.Get("template") is not EvidenceText
                || item.Data.Get(item.Type == "identity_inference" ? "inference_source" : "mapping_source") is not EvidenceText)
                throw new InvalidDataException("Expected mapping identity fields");
            Identity(item.Data.Get("entity_id"));
        }
        else throw new InvalidDataException("Expected identity event");
        var data = (EvidenceObject)TraceValueProjection.Restore(item.Data, item.Data.Get("legacy_layout") as EvidenceObject ?? new(new Dictionary<string, EvidenceValue>()));
        if (item.Type == "squad")
        {
            var bindings = ActorIdentity.SquadBindings(((EvidenceArray)data.Get("members")).Items.Cast<EvidenceObject>()
                .Select(row => (((EvidenceText)row.Get("template")).Value, PythonDisplay.String(row.Get("entity_id")))));
            ActorIdentity.ApplySquad(bindings, partyIds, squad);
        }
        // Legacy ACTOR_MAP is diagnostic only; it does not establish ingestion authority.
    }
}
