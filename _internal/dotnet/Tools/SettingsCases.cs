using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

internal static class SettingsCases
{
    public static int Run(string inputPath, string outputPath, bool skins = false)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            JsonNode actual;
            if (skins)
            {
                try
                {
                    var name = test["name"]!.GetValue<string>();
                    var skin = name.StartsWith("builtin-", StringComparison.Ordinal) ? NativeSkins.Builtin(name[8..]) : NativeSkins.Parse(config.Get("data"));
                    OverlaySettings entry = new() { TemplateSettings = (EvidenceObject)config.Get("settings") };
                    if (config.Get("change") is EvidenceObject change)
                        entry = NativeSkins.WithValue(entry, skin, ((EvidenceText)change.Get("key")).Value, change.Get("value"));
                    actual = new JsonObject
                    {
                        ["valid"] = true, ["name"] = skin.Name,
                        ["subscriptions"] = new JsonArray(skin.Subscriptions.Select(v => JsonValue.Create(v)).ToArray()),
                        ["settings"] = Json(new EvidenceArray(skin.Settings)), ["window"] = Json(skin.Window),
                        ["modules"] = Json(new EvidenceArray(skin.Modules)), ["layout"] = Json(skin.Layout), ["theme"] = Json(skin.Theme),
                        ["values"] = Json(NativeSkins.Values(entry, skin)),
                        ["module_settings"] = new JsonArray(NativeSkins.ResolveModules(entry, skin).Select(module => (JsonNode)new JsonObject
                            { ["type"] = module.Type, ["settings"] = Json(module.Settings) }).ToArray()),
                    };
                }
                catch (Exception error) when (error is IOException or InvalidDataException or ArgumentException or FormatException)
                { actual = new JsonObject { ["valid"] = false }; }
            }
            else
            {
                SettingsCodec codec = new(new(@"C:\Endfield配置\应用", @"C:\Endfield配置\工作目录"));
                var settings = codec.Decode(config); var payload = Json(codec.Encode(settings));
                HashSet<string> explicitIds = config.Get("overlays") is EvidenceArray rows
                    ? rows.Items.OfType<EvidenceObject>().Select(row => row.Get("id")).OfType<EvidenceText>().Select(text => text.Value).ToHashSet(StringComparer.Ordinal) : [];
                Dictionary<string, string> identifiers = [];
                var entries = payload["overlays"]!.AsArray();
                for (var index = 0; index < entries.Count; index++)
                {
                    var id = entries[index]!["id"]!.GetValue<string>();
                    if (!explicitIds.Contains(id)) { identifiers[id] = "$generated-" + index; entries[index]!["id"] = identifiers[id]; }
                }
                var restore = payload["overlay_restore_ids"]!.AsArray();
                for (var index = 0; index < restore.Count; index++)
                { var id = restore[index]!.GetValue<string>(); if (identifiers.TryGetValue(id, out var updated)) restore[index] = updated; }
                if (config.Get("service") is not EvidenceObject service || service.Get("ws_browser_token") is not EvidenceText token
                    || !Regex.IsMatch(token.Value, @"\A[A-Za-z0-9_-]{43,128}\z")) payload["service"]!["ws_browser_token"] = "$generated";
                actual = new JsonObject { ["payload"] = payload, ["migration_count"] = settings.OverlayMigrationCount };
            }
            var comparable = actual;
            var formatContract = true;
            var recordingHotkeyContract = true;
            var battleFontContract = true;
            if (!skins && test["expected"]?["payload"]?["service"] is JsonObject expectedService
                && !expectedService.ContainsKey("trace_format"))
            {
                // The fixed Python fixture predates persistence of trace_format.
                // Keep its bytes and every other field unchanged; check the new
                // approved default/explicit-choice contract independently.
                var selected = config.Get("service") is EvidenceObject serviceConfig
                    && serviceConfig.Get("trace_format") is EvidenceText { Value: "legacy" or "jsonl" } format
                    ? format.Value : "jsonl";
                formatContract = actual["payload"]!["service"]!["trace_format"]?.GetValue<string>() == selected;
                comparable = actual.DeepClone();
                comparable["payload"]!["service"]!.AsObject().Remove("trace_format");
            }
            if (!skins && test["expected"]?["payload"] is JsonObject expectedPayload
                && !expectedPayload.ContainsKey("toggle_recording_hotkey"))
            {
                // These fixed cases also predate the recording shortcut. Check
                // its approved default separately without rewriting the golden.
                recordingHotkeyContract = actual["payload"]!["toggle_recording_hotkey"]?.GetValue<string>() == "Ctrl+I";
                if (ReferenceEquals(comparable, actual)) comparable = actual.DeepClone();
                comparable["payload"]!.AsObject().Remove("toggle_recording_hotkey");
            }
            if (!skins && test["expected"]?["payload"] is JsonObject fixedPayload && !fixedPayload.ContainsKey("battle_font_percent"))
            {
                // Independent analysis typography was added after the fixed reference.
                // Nondefault persistence and bounds are covered by SettingsSpecs.
                battleFontContract = actual["payload"]!["battle_font_percent"]?.GetValue<int>() == 115;
                if (ReferenceEquals(comparable, actual)) comparable = actual.DeepClone();
                comparable["payload"]!.AsObject().Remove("battle_font_percent");
            }
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(),
                ["passed"] = formatContract && recordingHotkeyContract && battleFontContract && JsonNode.DeepEquals(comparable, test["expected"]),
                ["battle_font_contract"] = battleFontContract,
                ["trace_format_contract"] = formatContract, ["recording_hotkey_contract"] = recordingHotkeyContract,
                ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"{(skins ? "Native skins" : "Application settings")} differential: {outcomes.Count} cases, {failures} differences");
        return failures == 0 ? 0 : 1;
    }
    private static JsonNode Json(EvidenceValue value) => JsonNode.Parse(PythonSortedJson.Serialize(value, compact: true))!;
}
