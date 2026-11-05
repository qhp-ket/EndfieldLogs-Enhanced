using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Catalog;

public static class DamageZoneCatalog
{
    public static IReadOnlyDictionary<string, EvidenceObject> Load(ResourceFiles files) => Project(files.ReadRelative("data/local_static/damage_zone_config.json"));

    public static IReadOnlyDictionary<string, EvidenceObject> Project(EvidenceValue? value)
    {
        if (value is null) return new Dictionary<string, EvidenceObject>();
        if (value is not EvidenceObject payload) throw new InvalidDataException("Damage zone configuration must be an object");
        if (!EvidenceJson.PythonEquals(payload.Get("schemaVersion"), new EvidenceInteger(1))
            || payload.Get("source") is not EvidenceText { Value: "official_unity_typetree_damage_zone_config" }
            || payload.Get("decoder") is not EvidenceObject decoder
            || ((EvidenceObject)NativeDamageSemanticsBinding.Evidence).Fields.Any(pair => !EvidenceJson.PythonEquals(pair.Value, decoder.Get(pair.Key)))
            || payload.Get("zones") is not EvidenceArray { Items.Count: > 0 } zones) return new Dictionary<string, EvidenceObject>();
        Dictionary<string, EvidenceObject> result = new(StringComparer.Ordinal);
        for (var index = 0; index < zones.Items.Count; index++)
        {
            if (zones.Items[index] is not EvidenceObject row || row.Get("name") is not EvidenceText name
                || row.Get("isMultiplyZone") is not EvidenceInteger || row.Get("serverIndex") is not EvidenceInteger)
                return new Dictionary<string, EvidenceObject>();
            result[name.Value] = new(new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal) { ["clientIndex"] = new EvidenceInteger(index) });
        }
        return result;
    }
}
