using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public static class StructuredCharacterSkills
{
    public static void Accept(TraceEvent item, int evidenceIndex, LoadoutObservations state)
    {
        if (item.Type != "character_skills" || item.Data.Get("template") is not EvidenceText || !item.Data.Fields.ContainsKey("entity_id"))
            throw new InvalidDataException("Expected character skill identity");
        var identity = item.Data.Get("entity_id");
        if (identity is not EvidenceNull && (identity is not EvidenceText text || text.Value.Length == 0 || text.Value.Any(unit => unit is < '0' or > '9')))
            throw new InvalidDataException("Instance identities must be decimal strings");
        if (item.Data.Get("skills") is not EvidenceArray rows || rows.Items.Any(value => value is not EvidenceObject row
            || row.Get("skill") is not EvidenceText || !row.Fields.ContainsKey("level")))
            throw new InvalidDataException("Expected character skill observations");
        var data = TraceModel.Data(item);
        state.ObserveCharacterSkills(((EvidenceText)data.Get("template")).Value,
            Catalog.CatalogValues.Truth(data.Get("entity_id")) ? PythonDisplay.String(data.Get("entity_id")) : "unknown",
            ((EvidenceArray)data.Get("skills")).Items.Cast<EvidenceObject>().Select(row =>
                (((EvidenceText)row.Get("skill")).Value, PythonDisplay.String(row.Get("level")))), evidenceIndex, item.CapturedAtMs);
    }
}
