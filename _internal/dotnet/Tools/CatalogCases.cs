using System.Globalization;
using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

internal static class CatalogCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        var temporary = Path.Combine(Path.GetTempPath(), "endfield-catalog-spec-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        try
        {
            foreach (var test in cases)
            {
                var directory = Path.Combine(temporary, results.Count.ToString(CultureInfo.InvariantCulture));
                Directory.CreateDirectory(Path.Combine(directory, "_internal"));
                foreach (var (name, contents) in test!["files"]!.AsObject())
                {
                    var path = SafePath(directory, name);
                    Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                    File.WriteAllText(path, contents!.GetValue<string>());
                }
                foreach (var name in test["directories"]?.AsArray() ?? [])
                    Directory.CreateDirectory(SafePath(directory, name!.GetValue<string>()));
                foreach (var (name, bytes) in test["binary_files"]?.AsObject() ?? [])
                {
                    var path = SafePath(directory, name);
                    Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                    File.WriteAllBytes(path, Convert.FromBase64String(bytes!.GetValue<string>()));
                }
                JsonNode? actual;
                try { actual = Evaluate(new ResourceFiles(Path.Combine(directory, "_internal")), test); }
                catch (Exception error) when (test["kind"]!.GetValue<string>() is "weapons" or "suits" or "equipment" or "display_names" or "skill_profiles" or "character_profiles"
                    && error is InvalidDataException or InvalidCastException or System.Text.DecoderFallbackException or FormatException or OverflowException)
                {
                    actual = new JsonObject { ["catalog_error"] = error is InvalidDataException ? "AttributeError"
                        : error is InvalidCastException ? "TypeError" : error is FormatException ? "JSONDecodeError"
                        : error is OverflowException ? "OverflowError" : "UnicodeDecodeError" };
                }
                results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                    ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) });
            }
        }
        finally
        {
            // This directory is created exclusively for this invocation, never from a fixture path.
            Directory.Delete(temporary, recursive: true);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Resource catalog differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }

    private static string SafePath(string root, string relative)
    {
        var path = Path.GetFullPath(Path.Combine(root, relative));
        if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Fixture resource path is outside its temporary directory");
        return path;
    }

    internal static JsonNode? Evaluate(ResourceFiles resources, JsonNode test)
    {
        object result;
        switch (test["kind"]!.GetValue<string>())
        {
            case "display_names":
            {
                CharacterResourceCatalog characters = new(resources);
                DisplayNameCatalog names = new(resources, characters, new SkillResourceCatalog(resources).CreateIdentityCatalog());
                result = new Dictionary<string, object?>
                {
                    ["characters"] = characters.Names, ["enemies"] = names.EnemyNames,
                    ["prefixes"] = characters.SkillNames.Select(row => new[] {row.Key, row.Name}).ToArray(),
                    ["exact"] = names.ExactSkillNames, ["canonical"] = names.CanonicalSkillNames,
                    ["resolved"] = test["ids"]!.AsArray().Select(row => row?.GetValue<string>())
                        .Select(key => new[] {names.Character(key),names.Enemy(key),names.Skill(key)}).ToArray(),
                };
                break;
            }
            case "character_profiles": result = new CharacterResourceCatalog(resources).Profiles; break;
            case "skill_profiles":
            {
                SkillProfileCatalog profiles = new(resources, new(resources), new SkillResourceCatalog(resources).CreateIdentityCatalog());
                result = new Dictionary<string, object?>
                {
                    ["profiles"] = profiles.Profiles,
                    ["resolved"] = test["ids"]!.AsArray().Select(row => profiles.Resolve(row?.GetValue<string>())).ToArray(),
                };
                break;
            }
            case "dungeons":
            {
                var catalog = new DungeonCatalog(resources);
                static object Context(EndfieldLogs.Core.Ingestion.DungeonContext value) => new[] { value.Key, value.Name };
                var resolutions = test["ids"]!.AsArray().Select(id => catalog.Resolve(id?.GetValue<string>()))
                    .Select(context => context is null ? null : Context(context)).ToArray();
                result = new Dictionary<string, object?> { ["entries"] = catalog.Entries.ToDictionary(pair => pair.Key, pair => Context(pair.Value)),
                    ["resolved"] = resolutions };
                break;
            }
            case "numbers":
            {
                var catalog = new SkillResourceCatalog(resources);
                result = new Dictionary<string, object?> { ["skills"] = catalog.Skills, ["buffs"] = catalog.Buffs };
                break;
            }
            case "profiles":
                result = new SkillResourceCatalog(resources).Profiles.ToDictionary(pair => pair.Key, pair => pair.Value.Definition);
                break;
            case "weapons": result = new WeaponCatalog(resources).Entries.ToDictionary(pair => pair.Key, pair => pair.Value); break;
            case "suits": result = new EquipmentCatalog(resources).Suits.ToDictionary(pair => pair.Key, pair => pair.Value); break;
            case "equipment": result = new EquipmentCatalog(resources).Pieces.ToDictionary(pair => pair.Key, pair => pair.Value); break;
            case "skill_metadata":
            {
                var catalog = new SkillItemMetadataCatalog(resources);
                result = test["ids"]!.AsArray().Select(id => catalog.For(id!.GetValue<string>())).Select(value => value.Available
                    ? (object)new Dictionary<string, object?>
                    {
                        ["skill_specification"] = value.Specification, ["cast_type"] = value.CastType, ["attack_range_type"] = value.AttackRangeType,
                        ["dynamic_action_keys"] = value.DynamicActionKeys.ToDictionary(pair => pair.Key.ToString(CultureInfo.InvariantCulture), pair => pair.Value),
                    } : new Dictionary<string, object?>()).ToArray();
                break;
            }
            case "buff_roots":
            {
                var catalog = new BuffRootCatalog(resources);
                result = new Dictionary<string, object?>
                {
                    ["roots"] = catalog.Roots,
                    ["action_types"] = catalog.ActionTypes.ToDictionary(pair => pair.Key,
                        pair => pair.Value.Order(StringComparer.Ordinal).ToArray()),
                };
                break;
            }
            case "identities":
            {
                var catalog = new SkillResourceCatalog(resources).CreateIdentityCatalog();
                result = test["queries"]!.AsArray().Select(query =>
                {
                    var skill = query!["skill"]?.GetValue<string>();
                    var owner = query["owner"]?.GetValue<string>();
                    var action = query["action"] is JsonNode actionValue ? BigInteger.Parse(actionValue.GetValue<string>(), CultureInfo.InvariantCulture) : (BigInteger?)null;
                    var unit = query["unit"] is JsonNode unitValue ? BigInteger.Parse(unitValue.GetValue<string>(), CultureInfo.InvariantCulture) : (BigInteger?)null;
                    return new Dictionary<string, object?>
                    {
                        ["skill"] = catalog.CanonicalSkill(skill, owner),
                        ["hit"] = catalog.CanonicalHitSkill(skill, owner),
                        ["buff"] = catalog.CanonicalRuntimeBuff(skill, owner, action, unit),
                        ["template"] = catalog.HitFromTemplate(skill, owner, query["template"]?.GetValue<string>(), action, unit),
                    };
                }).ToArray();
                break;
            }
            case "contracts":
            {
                var catalog = new ContractTagCatalog(resources);
                result = new Dictionary<string, object?>
                {
                    ["entries"] = catalog.Entries.ToDictionary(pair => pair.Key.ToString(CultureInfo.InvariantCulture), pair => pair.Value),
                    ["payloads"] = test["ids"]!.AsArray().Select(id => catalog.Payload(BigInteger.Parse(id!.GetValue<string>(), CultureInfo.InvariantCulture))).ToArray(),
                };
                break;
            }
            default: throw new InvalidDataException("Unknown resource catalog fixture kind");
        }
        return FieldCases.Canonical(result);
    }
}
