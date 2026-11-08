using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Tracing;

/// <summary>Typed equipment evidence. Decode source/v1 strings once, format only for export.</summary>
public static class TraceLoadout
{
    private static EvidenceObject Obj(params (string, EvidenceValue)[] rows) => new(rows.ToDictionary(row => row.Item1, row => row.Item2));
    private static EvidenceText Text(string value) => new(value);
    private static EvidenceInteger Int(string value) => new(BigInteger.Parse(value, CultureInfo.InvariantCulture));
    public static EvidenceObject Native(EvidenceObject input)
    {
        var fields = input.Fields.ToDictionary();
        var invalid = input.Get("invalid_fields") is EvidenceObject previous ? previous.Fields.ToDictionary() : new Dictionary<string, EvidenceValue>();
        foreach (var key in new[] { "equip_suit", "equip_inst_ids" })
            if (input.Get(key) is EvidenceText raw)
            {
                var body = LoadoutWire.CompactBody(raw.Value);
                var pattern = key == "equip_suit" ? @"\[([^\]]+)\]=([0-9]+)" : @"\[([0-9]+)\]=([0-9]+)";
                fields[key] = new EvidenceArray(Regex.Matches(body ?? "", pattern).Select(match => (EvidenceValue)Obj(
                    (key == "equip_suit" ? "suit_id" : "slot", key == "equip_suit" ? Text(match.Groups[1].Value) : Int(match.Groups[1].Value)),
                    (key == "equip_suit" ? "piece_count" : "entity_id", key == "equip_suit" ? Int(match.Groups[2].Value) : Text(match.Groups[2].Value)))).ToArray());
                if (body is null || Regex.Replace(body, pattern, "").Trim().Length > 0) invalid[key] = raw;
            }
        if (input.Get("skill_int_ids") is EvidenceText skills)
            fields["skill_int_ids"] = new EvidenceArray(Regex.Matches(skills.Value.Split(']', 2)[0], @"\d+").Select(match => (EvidenceValue)Int(match.Value)).ToArray());
        if (input.Get("equips") is EvidenceText equipment)
        {
            var body = LoadoutWire.CompactBody(equipment.Value); var blob = body ?? "";
            var matches = Regex.Matches(blob, @"\[(\d+)\]="); List<EvidenceValue> rows = [];
            for (var index = 0; index < matches.Count; index++)
            {
                var match = matches[index]; var end = index + 1 < matches.Count ? matches[index + 1].Index : blob.Length;
                var row = blob[(match.Index + match.Length)..end].Trim();
                var levels = Regex.Match(row, @"\|lv=([^|]+)"); var stats = Regex.Match(row, @"\|stats=(.*)$");
                rows.Add(Obj(("slot", Int(match.Groups[1].Value)), ("item_id", Text(row.Split('|', 2)[0].Trim())),
                    ("enhance_levels", new EvidenceArray(TraceFields.EquipmentLevels(levels.Success ? levels.Groups[1].Value : null)
                        .Select(value => (EvidenceValue)Obj(("index", new EvidenceInteger(value.Index)), ("level", new EvidenceInteger(value.Level)))).ToArray())),
                    ("stats", new EvidenceArray(TraceFields.InlineEquipmentStats(stats.Success ? stats.Groups[1].Value : null)
                        .Select(value => (EvidenceValue)Obj(("slot", Text(value.Slot)), ("name", Text(value.Name)),
                            ("value", value.Value is double number ? new EvidenceReal(number) : Text((string)value.Value)),
                            ("level", value.Level is BigInteger level ? new EvidenceInteger(level) : EvidenceNull.Value))).ToArray()))));
            }
            fields["equips"] = new EvidenceArray(rows);
            if (body is null || blob.Trim().Length > 0 && rows.Count == 0) invalid["equips"] = equipment;
        }
        foreach (var key in new[] { "weapon_source_skills", "weapon_refine_stats" })
            if (input.Get(key) is EvidenceText raw)
            {
                var rows = LoadoutSnapshotParser.SourceSkills(raw.Value); fields[key] = rows;
                if (raw.Value.Trim('{', '}', ' ').Length > 0 && rows.Items.Count == 0) invalid[key] = raw;
            }
        if (input.Get("gem_terms") is EvidenceText terms)
        {
            var matches = terms.Value.Length == 0 ? [] : terms.Value.Split(',').Select(value => Regex.Match(value.Trim(), @"\A(\d+):([^,@{}]*)@cost(\d+)\z")).ToArray();
            fields["gem_terms"] = new EvidenceArray(matches.All(match => match.Success) ? matches.Select(match => (EvidenceValue)Obj(
                ("term_num_id", Int(match.Groups[1].Value)), ("template", Text(match.Groups[2].Value)), ("cost", Int(match.Groups[3].Value)))).ToArray() : []);
            if (matches.Any(match => !match.Success)) invalid["gem_terms"] = terms;
        }
        if (invalid.Count > 0) fields["invalid_fields"] = new EvidenceObject(invalid);
        return new(fields);
    }
    private static string Scalar(EvidenceValue value) => value is EvidenceReal real ? real.Value.ToString("g17", CultureInfo.InvariantCulture) : PythonDisplay.String(value);
    public static EvidenceObject Legacy(EvidenceObject input)
    {
        var fields = input.Fields.ToDictionary();
        foreach (var key in new[] { "equip_suit", "equip_inst_ids" })
            if (input.Get(key) is EvidenceArray rows)
            {
                var (name, count) = key == "equip_suit" ? ("suit_id", "piece_count") : ("slot", "entity_id");
                fields[key] = Text("{" + string.Join(' ', rows.Items.Cast<EvidenceObject>().Select(row => $"[{Scalar(row.Get(name))}]={Scalar(row.Get(count))}")) + "}");
            }
        if (input.Get("skill_int_ids") is EvidenceArray skills) fields["skill_int_ids"] = Text(string.Join(' ', skills.Items.Select(Scalar)));
        if (input.Get("equips") is EvidenceArray equips)
            fields["equips"] = Text("{" + string.Join(' ', equips.Items.Cast<EvidenceObject>().Select(row =>
                $"[{Scalar(row.Get("slot"))}]={Scalar(row.Get("item_id"))}|lv=" + string.Join(',', ((EvidenceArray)row.Get("enhance_levels")).Items.Cast<EvidenceObject>()
                    .Select(value => Scalar(value.Get("index")) + ":" + Scalar(value.Get("level")))) + "|stats="
                + string.Join(';', ((EvidenceArray)row.Get("stats")).Items.Cast<EvidenceObject>().Select(value =>
                    Scalar(value.Get("slot")) + ":" + Scalar(value.Get("name")) + "=" + Scalar(value.Get("value"))
                    + (value.Get("level") is EvidenceNull ? "" : "@" + Scalar(value.Get("level"))))))) + "}");
        foreach (var key in new[] { "weapon_source_skills", "weapon_refine_stats" })
            if (input.Get(key) is EvidenceArray rows)
                fields[key] = Text(string.Join(';', rows.Items.Cast<EvidenceObject>().Select(row => Scalar(row.Get("skill_id"))
                    + (row.Get("level") is EvidenceNull ? "" : ":level=" + Scalar(row.Get("level")))
                    + (row.Get("potential_level") is EvidenceNull ? "" : ":potentialLv=" + Scalar(row.Get("potential_level")))
                    + ":bb={" + string.Join(',', ((EvidenceObject)row.Get("bb")).Fields.Select(pair => pair.Key + "=" + Scalar(pair.Value))) + "}")));
        if (input.Get("gem_terms") is EvidenceArray terms)
            fields["gem_terms"] = input.Get("invalid_fields") is EvidenceObject invalid && invalid.Get("gem_terms") is EvidenceText raw ? raw
                : Text(string.Join(',', terms.Items.Cast<EvidenceObject>().Select(row => Scalar(row.Get("term_num_id")) + ":" + Scalar(row.Get("template")) + "@cost" + Scalar(row.Get("cost")))));
        if (input.Get("invalid_fields") is EvidenceObject rawFields)
            foreach (var (key, value) in rawFields.Fields) fields[key] = value;
        return new(fields);
    }
}
