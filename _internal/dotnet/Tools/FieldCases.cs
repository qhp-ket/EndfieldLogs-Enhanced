using System.Collections;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Compatibility;

internal static class FieldCases
{
    private static object? Input(JsonNode? value)
    {
        if (value is null) return null;
        if (value is JsonObject obj && obj["f64"] is JsonNode bits)
            return BitConverter.UInt64BitsToDouble(ulong.Parse(bits.GetValue<string>(), NumberStyles.HexNumber));
        if (value is not JsonValue) return value;
        var raw = JsonSerializer.Deserialize<JsonElement>(value.ToJsonString());
        return raw.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.String => raw.GetString(),
            JsonValueKind.Number => raw.GetRawText().IndexOfAny(['.', 'e', 'E']) >= 0
                ? (object)raw.GetDouble() : BigInteger.Parse(raw.GetRawText(), CultureInfo.InvariantCulture),
            _ => null,
        };
    }

    internal static JsonNode? Canonical(object? value)
    {
        switch (value)
        {
            case null: return null;
            case EvidenceNull: return null;
            case EvidenceBoolean flag: return Canonical(flag.Value);
            case EvidenceInteger integer: return Canonical(integer.Value);
            case EvidenceReal number: return Canonical(number.Value);
            case EvidenceText text: return Canonical(text.Value);
            case EvidenceArray array: return Canonical(array.Items);
            case EvidenceObject mapping: return Canonical(mapping.Fields.ToDictionary(pair => pair.Key,pair => pair.Value));
            case string text: return JsonValue.Create(text);
            case bool flag: return JsonValue.Create(flag);
            case JsonNode node: return node.DeepClone();
            case double number: return new JsonObject { ["f64"] = BitConverter.DoubleToUInt64Bits(number).ToString("x16") };
            case BigInteger integer: return new JsonObject { ["int"] = integer.ToString(CultureInfo.InvariantCulture) };
            case long integer: return new JsonObject { ["int"] = integer.ToString(CultureInfo.InvariantCulture) };
            case int integer: return new JsonObject { ["int"] = integer.ToString(CultureInfo.InvariantCulture) };
            case IDictionary mapping:
                JsonObject result = [];
                foreach (DictionaryEntry item in mapping) result[Convert.ToString(item.Key, CultureInfo.InvariantCulture)!] = Canonical(item.Value);
                return result;
            case EquipmentLevel level:
                return Canonical(new Dictionary<string, object?> { ["index"]=level.Index, ["level"]=level.Level });
            case InlineEquipmentStat stat:
                return Canonical(new Dictionary<string, object?> { ["slot"]=stat.Slot, ["name"]=stat.Name, ["value"]=stat.Value, ["level"]=stat.Level });
            case RawDamageEvidence damage:
                return Canonical(new Dictionary<string, object?> { ["seq"]=damage.Sequence, ["calc"]=damage.Calculation,
                    ["atk_scale"]=damage.AttackScale, ["blocked"]=damage.Blocked, ["damage_type_raw"]=damage.DamageTypeRaw,
                    ["decorate_mask_raw"]=damage.DecorateMaskRaw, ["collider"]=damage.Collider,
                    ["atk_zones"]=damage.AttackerZones, ["def_zones"]=damage.DefenderZones });
            case BaselineEvidence baseline: return Canonical(new object[] { baseline.Sequence, baseline.Values });
            case PacketListEvidence packet: return Canonical(new object[] { packet.Sequence, packet.Attacker, packet.Defender });
            case IEnumerable items:
                JsonArray rows = [];
                foreach (var item in items) rows.Add(Canonical(item));
                return rows;
            default: throw new InvalidDataException("Unsupported field result: "+value.GetType());
        }
    }

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var value = Input(test!["input"]);
            JsonNode? actual;
            try
            {
                object? result = test["function"]!.GetValue<string>() switch
                {
                    "integer" => TraceFields.OptionalInteger(value),
                    "optional_float" => TraceFields.OptionalFloat(value),
                    "positive_integer" => TraceFields.PositiveInteger(value),
                    "positive_rate" => TraceFields.PositiveRate(value),
                    "duration" => TraceFields.DurationMs((string?)value),
                    "ms_text" => TraceFields.MillisecondTimeText(value is null ? null : (long)(BigInteger)value),
                    "timestamp" => TraceFields.PrefixedTimestampMs((string)value!),
                    "hint" => TraceFields.HintTimestampMs((string?)value),
                    "fields" => TraceFields.Extract((string)value!),
                    "token" => TraceFields.Token((string)value!, test["key"]!.GetValue<string>()),
                    "braced" => TraceFields.Braced((string)value!, test["key"]!.GetValue<string>()),
                    "split" => TraceFields.SplitTopLevel((string)value!, test["separator"]!.GetValue<string>()[0]),
                    "blackboard" => TraceFields.BlackboardAssignments((string?)value),
                    "zones" => TraceFields.ZoneValues((string?)value),
                    "suits" => TraceFields.LoadoutSuits((string?)value).Order(StringComparer.Ordinal).ToArray(),
                    "skill_ids" => TraceFields.SkillIntegerIds((string)value!),
                    "loadout_skill_ids" => TraceFields.LoadoutSkillIds((string)value!).Order(StringComparer.Ordinal).ToArray(),
                    "equip_levels" => TraceFields.EquipmentLevels((string?)value),
                    "equip_stats" => TraceFields.InlineEquipmentStats((string?)value),
                    "contract_ids" => TraceFields.ContractTagIds((string?)value),
                    "short_actor" => TraceFields.ShortActorNumber((string?)value),
                    "dpd_raw" => TraceFields.RawDamage((string)value!),
                    "baseline" => TraceFields.Baseline((string)value!),
                    "packet_mod" => TraceFields.PacketModifiers((string)value!),
                    "packet_attr" => TraceFields.PacketAttributes((string)value!),
                    "iso" => TraceFields.BuildIsoDateTime(DateOnly.Parse(test["date"]!.GetValue<string>(), CultureInfo.InvariantCulture),
                        (long)(BigInteger)value!, test["rollover"]!.GetValue<int>(),
                        TimeZoneInfo.CreateCustomTimeZone("reference", TimeSpan.FromMinutes(test["offset_minutes"]!.GetValue<int>()),"reference","reference")),
                    _ => throw new InvalidDataException("Unknown field function"),
                };
                actual = new JsonObject { ["value"] = Canonical(result) };
            }
            catch (Exception error) when (error is FormatException or OverflowException)
            {
                actual = new JsonObject { ["error"] = error is OverflowException ? "OverflowError" : "ValueError" };
            }
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),
                ["passed"]=JsonNode.DeepEquals(actual, test["expected"]), ["actual"]=actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(item => !item!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Trace-field differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
