using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Ordered BUFF snapshots share lifecycle state with legacy input.</summary>
public static class StructuredBuff
{
    private static bool BlackboardValue(EvidenceValue value) => value is EvidenceInteger or EvidenceReal
        || value is EvidenceObject { Fields.Count: 1 } obj && obj.Get("number_status") is EvidenceText
            { Value: "nan" or "positive_infinity" or "negative_infinity" };
    public static void Accept(TraceEvent item, int evidenceIndex, BuffInstanceState buffs)
    {
        if (item.Type is not ("buff_start" or "buff_end" or "buff_blackboard"))
            throw new InvalidDataException("Expected BUFF lifecycle or blackboard event");
        if (!item.Data.Fields.ContainsKey("buff_inst_id")) throw new InvalidDataException("Expected BUFF instance");
        foreach (var key in new[] { "buff_inst_id", "target_id", "source_actor_id" })
            if (item.Data.Get(key) is not EvidenceNull && (item.Data.Get(key) is not EvidenceText id || id.Value.Length == 0 || id.Value.Any(unit => unit is < '0' or > '9')))
                throw new InvalidDataException("Instance identities must be decimal strings");
        foreach (var key in new[] { "template", "owner", "source" })
            if (item.Data.Get(key) is not (EvidenceNull or EvidenceText)) throw new InvalidDataException("Expected BUFF label");
        if (item.Type == "buff_blackboard" && (item.Data.Get("values") is not EvidenceArray array || array.Items.Any(row =>
                row is not EvidenceObject obj || obj.Get("key") is not EvidenceText || !BlackboardValue(obj.Get("value")))))
            throw new InvalidDataException("Expected BUFF blackboard values");
        var data = (EvidenceObject)TraceValueProjection.Restore(item.Data, item.Data.Get("legacy_layout") as EvidenceObject ?? new(new Dictionary<string, EvidenceValue>()));
        if (item.Type == "buff_blackboard")
        {
            Dictionary<string, double?> values = new(StringComparer.Ordinal);
            foreach (var row in ((EvidenceArray)data.Get("values")).Items.Cast<EvidenceObject>())
                values[((EvidenceText)row.Get("key")).Value] = SkillWire.ProjectedNumber(row.Get("value"));
            buffs.ObserveBlackboard(values);
        }
        else
        {
            buffs.ObserveLifecycle(item.Type == "buff_start" ? "start" : "end", new Dictionary<string, string>
            {
                ["uid"] = SkillWire.IdentityToken(data.Get("buff_inst_id")), ["id"] = SkillWire.Label(data, "template", ""),
                ["owner"] = SkillWire.Label(data, "owner", "?"), ["src"] = SkillWire.Label(data, "source", "?"),
                ["ownerId"] = SkillWire.IdentityToken(data.Get("target_id")), ["srcId"] = SkillWire.IdentityToken(data.Get("source_actor_id")),
                ["dur"] = "unknown",
            }, evidenceIndex, item.CapturedAtMs);
        }
    }
}
