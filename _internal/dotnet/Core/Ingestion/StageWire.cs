using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public static class StageWire
{
    public static EvidenceObject Data(string kind, EvidenceObject source, string dungeonId, string origin)
    {
        Dictionary<string, EvidenceValue> data = new() { ["dungeon_id"] = dungeonId.Length > 0 ? new EvidenceText(dungeonId) : EvidenceNull.Value, ["source"] = new EvidenceText(origin) };
        (string Input, string Output)[] fields = kind switch
        {
            "dungeon" => [("scene_num_id","scene_num_id"), ("scene_id","scene_id"), ("challenge_expire_ts","challenge_expire_ts"),
                ("leave_dungeon_ts","leave_dungeon_ts"), ("char_team_count","char_team_count"), ("is_reward","is_reward"), ("is_calc","is_calc"), ("is_pass","is_pass")],
            "battle_result" => [("is_calc","is_calc"), ("is_pass","is_pass")],
            "contracts" => [("tag_ids","tag_ids"), ("tagIds","alternate_tag_ids"), ("display_tag_ids","display_tag_ids"),
                ("score","score"), ("direction","direction"), ("msg_id","message_id"), ("msgId","alternate_message_id")],
            _ => throw new InvalidDataException("Expected stage event"),
        };
        foreach (var (input, output) in fields) if (source.Fields.TryGetValue(input, out var value)) data[output] = value;
        return new(data);
    }

    public static IReadOnlyList<BigInteger> ContractTags(EvidenceObject data)
    {
        var raw = CatalogValues.Truth(data.Get("tag_ids")) ? data.Get("tag_ids")
            : CatalogValues.Truth(data.Get("alternate_tag_ids")) ? data.Get("alternate_tag_ids") : data.Get("display_tag_ids");
        return (raw is EvidenceArray array ? array.Items : []).Select(SkillWire.Integer)
            .Where(value => value is { IsZero: false }).Select(value => value!.Value).ToArray();
    }

    public static (string Marker, IReadOnlyDictionary<string, string> Fields, IReadOnlyList<BigInteger>? Tags) Observation(TraceEvent item)
    {
        if (item.Type is not ("dungeon" or "contracts" or "battle_result")) throw new InvalidDataException("Expected stage event");
        if (item.Data.Get("source") is not EvidenceText { Value.Length: > 0 } source) throw new InvalidDataException("Stage source is required");
        var rawDungeon = item.Data.Get("dungeon_id");
        if (rawDungeon is not (EvidenceText or EvidenceNull)) throw new InvalidDataException("Stage dungeon identity must be text or null");
        var dungeon = (rawDungeon as EvidenceText)?.Value;
        if (item.Type != "contracts" && string.IsNullOrEmpty(dungeon)) throw new InvalidDataException("Stage dungeon identity is required");
        Dictionary<string, string> fields = new() { ["dungeonId"] = string.IsNullOrEmpty(dungeon) ? "unknown" : dungeon, ["source"] = source.Value };
        if (item.Type == "battle_result") fields["isPass"] = CatalogValues.Truth(item.Data.Get("is_pass")) ? "1" : "0";
        IReadOnlyList<BigInteger>? tags = null;
        if (item.Type == "contracts")
        {
            // Preserve the established legacy digit-only analysis projection.
            tags = ContractTags(item.Data).Select(BigInteger.Abs).ToArray();
            if (SkillWire.Integer(item.Data.Get("score")) is { } score) fields["score"] = score.ToString(System.Globalization.CultureInfo.InvariantCulture);
        }
        return (item.Type == "dungeon" ? "DUNGEON_CONTEXT" : item.Type == "contracts" ? "CONTRACT_TAGS" : "BATTLE_RESULT", fields, tags);
    }
}
