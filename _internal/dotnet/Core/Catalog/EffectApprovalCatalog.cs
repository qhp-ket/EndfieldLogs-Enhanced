using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Catalog;

/// <summary>The reviewed registry plus the version-bound native keyword mapping.</summary>
public static class EffectApprovalCatalog
{
    public static EvidenceObject Load(ResourceFiles resources) => Project(resources.ReadRelative("data/packet_semantics/rdps_semantics_registry.json"),
        resources.ReadRelative("data/local_static/buff/keyword_buff_map.json"));

    public static EvidenceObject Project(EvidenceValue? registry, EvidenceValue? keyword)
    {
        if (registry is not EvidenceObject result) return new(new Dictionary<string, EvidenceValue>());
        if (keyword is not EvidenceObject document || document.Get("schemaVersion") is not EvidenceInteger { Value.IsOne: true }
            || document.Get("source") is not EvidenceText { Value: "current_native_keyword_switch_and_metadata_literals" }
            || document.Get("decoder") is not EvidenceObject decoder || decoder.Fields.Count != 2
            || new[] { "gameAssemblySha256", "metadataSha256" }.Any(key => !EvidenceJson.PythonEquals(decoder.Get(key), TypedResourceBinding.Evidence.Get(key)))
            || document.Get("mapping") is not EvidenceObject mapping || !mapping.Fields.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(["Vulnerable", "Enhanced"])) return result;
        string[] subtypes = ["All", "Spell", "Physical", "Natural", "Fire", "Crystal", "Pulse"];
        if (mapping.Fields.Values.Any(value => value is not EvidenceObject rows || !rows.Fields.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(subtypes)
            || rows.Fields.Values.Any(item => item is not EvidenceText { Value.Length: > 0 }))) return result;
        return new(new Dictionary<string, EvidenceValue>(result.Fields, StringComparer.Ordinal) { ["_keyword_buff_map"] = mapping });
    }
}
