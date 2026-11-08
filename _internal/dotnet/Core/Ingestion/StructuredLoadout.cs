using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public static class StructuredLoadout
{
    private static void Identity(EvidenceValue value)
    {
        if (value is not EvidenceNull && (value is not EvidenceText text || text.Value.Length == 0 || text.Value.Any(unit => unit is < '0' or > '9')))
            throw new InvalidDataException("Instance identities must be decimal strings");
    }
    private static void Identities(EvidenceValue value)
    {
        if (value is not EvidenceArray rows) throw new InvalidDataException("Expected loadout identities");
        foreach (var entry in rows.Items)
        {
            if (entry is not EvidenceObject row || !row.Fields.ContainsKey("entity_id")) throw new InvalidDataException("Expected loadout identity");
            Identity(row.Get("entity_id"));
        }
    }
    public static void Accept(TraceEvent item, int evidenceIndex, LoadoutObservations state)
    {
        if (item.Type == "loadout_group")
        {
            if (item.Data.Get("reason") is not EvidenceText || item.Data.Get("slot_count") is not EvidenceInteger { Value.Sign: >= 0 }
                || item.Data.Get("member_count") is not EvidenceInteger { Value.Sign: >= 0 }) throw new InvalidDataException("Expected loadout group");
            Identities(item.Data.Get("roster"));
        }
        else if (item.Type is "loadout_slot" or "loadout_stats")
        {
            if (item.Data.Get("template") is not EvidenceText) throw new InvalidDataException("Expected loadout character");
            foreach (var key in new[] { "entity_id", "weapon_id", "gem_id", "gem_weapon_id" })
                if (item.Data.Fields.ContainsKey(key)) Identity(item.Data.Get(key));
            if (item.Data.Fields.ContainsKey("unplaced_equipment")) Identities(item.Data.Get("unplaced_equipment"));
        }
        else throw new InvalidDataException("Expected loadout event");
        var data = TraceModel.Data(item);
        if (item.Type == "loadout_group") state.BeginGroup(((EvidenceText)data.Get("reason")).Value, evidenceIndex, item.CapturedAtMs);
        else if (item.Type == "loadout_slot")
        {
            var observation = LoadoutWire.Slot(data);
            state.ObserveSnapshot(observation, evidenceIndex, item.CapturedAtMs);
            if (observation.Slot >= 0 && observation.Character.Length > 0 && observation.Weapon.Length > 0
                && !observation.Character.Concat(observation.Weapon).Any(char.IsWhiteSpace))
                state.ObserveActive(observation.Character, observation.Weapon, (observation.Suits ?? new EvidenceArray([])).Items.Cast<EvidenceObject>()
                    .Where(row => row.Get("piece_count") is EvidenceInteger count && count.Value >= 3)
                    .Select(row => ((EvidenceText)row.Get("suit_id")).Value).ToHashSet(StringComparer.Ordinal));
        }
        else state.ObserveSnapshot(LoadoutWire.Stats(data), evidenceIndex, item.CapturedAtMs);
    }
}
