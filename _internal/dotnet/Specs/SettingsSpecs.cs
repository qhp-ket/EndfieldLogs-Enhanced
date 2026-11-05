using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

internal static class SettingsSpecs
{
    private static EvidenceObject Object(string text) => (EvidenceObject)EvidenceJson.Parse(text);
    public static void Run(Action<bool, string> check)
    {
        var root = Path.Combine(Path.GetTempPath(), "endfield-settings-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            List<string> messages = []; SettingsStorage storage = new((message, _) => messages.Add(message));
            var path = Path.Combine(root, "settings.json");
            SettingsCodec formatCodec = new(new(root));
            var defaults = formatCodec.Decode(Object("{}"));
            check(defaults.ToggleRecordingHotkey == "Ctrl+I", "Recording starts and stops with Ctrl+I by default");
            formatCodec.Save(defaults with { ToggleRecordingHotkey = "Ctrl+Alt+I" }, path);
            check(formatCodec.Load(path).ToggleRecordingHotkey == "Ctrl+Alt+I", "Recording shortcut persists independently");
            check(defaults.Service.ToCaptureOptions().TraceFormat == "jsonl", "New profiles use structured capture by default");
            foreach (var source in new[] { """{"service":{"ws_port":29325}}""", """{"service":{"trace_format":"unknown"}}""",
                """{"service":{"trace_format":""}}""", """{"service":{"trace_format":null}}""", """{"service":{"trace_format":42}}""" })
                check(formatCodec.Decode(Object(source)).Service.TraceFormat == "jsonl", "Missing or invalid format in an existing profile uses JSONL");
            foreach (var format in new[] { "jsonl", "legacy" })
            {
                var selected = formatCodec.Decode(Object("{\"service\":{\"trace_format\":\"" + format + "\"}}"));
                formatCodec.Save(selected, path);
                var persisted = storage.Read(path);
                check(selected.Service.TraceFormat == format
                    && ((EvidenceObject)persisted.Get("service")).Get("trace_format") is EvidenceText savedFormat && savedFormat.Value == format
                    && formatCodec.Load(path).Service.ToCaptureOptions().TraceFormat == format,
                    "Explicit " + format + " survives file save/load and reaches the production capture options");
            }
            File.Delete(path); File.Delete(path + ".bak");
            storage.Write(path, Object("{\"value\":1,\"中文\":\"原始\"}"));
            var original = File.ReadAllBytes(path);
            storage.Write(path, Object("{\"value\":2}"));
            check(File.ReadAllBytes(path + ".bak").SequenceEqual(original), "Backup preserves exact last valid bytes");
            File.WriteAllText(path, "{broken");
            var recovered = storage.Read(path);
            check(recovered.Get("value") is EvidenceInteger { Value.IsOne: true } && !File.Exists(path)
                && Directory.GetFiles(root, "settings.json.corrupt-*").Length == 1, "Corrupt main is preserved and valid backup restored");
            check(storage.Read(path).Get("value") is EvidenceInteger { Value.IsOne: true }, "Backup-only recovery works");
            File.WriteAllText(path, "{broken-again");
            using (var held = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                check(storage.Read(path).Get("value") is EvidenceInteger { Value.IsOne: true } && File.Exists(path), "Windows rename failure still permits backup recovery");
            storage.Write(path, Object("{\"value\":3}"));
            check(File.ReadAllBytes(path + ".bak").SequenceEqual(original), "Malformed main never overwrites good backup");
            var before = File.ReadAllBytes(path);
            using (var held = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                var failed = false;
                try { storage.Write(path, Object("{\"value\":4}")); }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException) { failed = true; }
                check(failed && File.ReadAllBytes(path).SequenceEqual(before), "Failed final replacement preserves main");
            }
            check(Directory.GetFiles(root, "*.tmp").Length == 0, "Failure cleans temporary files");
            var invalidFailed = false;
            try { storage.Write(path, Object("{\"value\":NaN}")); }
            catch (InvalidDataException) { invalidFailed = true; }
            check(invalidFailed && File.ReadAllBytes(path).SequenceEqual(before), "Non-finite serialization fails before altering files");
            File.WriteAllBytes(path, [0xff]);
            check(storage.Read(path).Get("value") is EvidenceInteger, "Invalid UTF-8 recovers valid backup");
            File.WriteAllText(path, "[]"); File.WriteAllText(path + ".bak", "false");
            check(storage.Read(path).Fields.Count == 0, "Non-object main and backup fall back to empty object");

            var app = Path.Combine(root, "安装 中文"); var moved = Path.Combine(root, "移动 后");
            var external = Path.Combine(root, "external"); SettingsContext context = new(app, root);
            SettingsCodec codec = new(context);
            var config = codec.Decode(Object("{}"));
            var key = PythonSortedJson.Serialize(new EvidenceArray([new EvidenceText(Path.Combine(app, "logs", "a.log")), new EvidenceInteger(1), new EvidenceText("time")]));
            config = config with
            {
                Service = config.Service with { NativeGameDirectory = external, DebugEnabled = true },
                ImportedTraceFiles = [Path.Combine(app, "logs", "a.log"), Path.Combine(external, "b.log")],
                HiddenHistoryRecords = [key], InputLogBindings = new(new Dictionary<string, EvidenceValue> { [key] = Object("{\"offset\":25}") }),
            };
            codec.Save(config);
            var saved = storage.Read(context.DefaultPath);
            check(saved.Get("path_base") is EvidenceText { Value: "application" } && ((EvidenceObject)saved.Get("service")).Get("rsa_key_txt") is EvidenceText { Value: "_internal/secrets/client_privkey.pem" }, "Portable save records application-relative resource anchors");
            Directory.Move(app, moved);
            SettingsCodec movedCodec = new(new(moved, external)); var after = movedCodec.Load();
            check(after.Service.LogDirectory.StartsWith(moved, StringComparison.Ordinal) && after.Service.RsaKeyPath.StartsWith(moved, StringComparison.Ordinal)
                && after.Service.NativeGameDirectory == external, "Relocation remaps internal paths and preserves external game installation");
            check(after.ImportedTraceFiles[0] == Path.Combine(moved, "logs", "a.log") && after.ImportedTraceFiles[1] == Path.Combine(external, "b.log"), "Relocation keeps external imported traces external");
            var hiddenPath = ((EvidenceText)((EvidenceArray)EvidenceJson.Parse(after.HiddenHistoryRecords.Single())).Items[0]).Value;
            check(hiddenPath == Path.Combine(moved, "logs", "a.log").ToLowerInvariant() && after.InputLogBindings.Fields.ContainsKey(after.HiddenHistoryRecords.Single()), "Hidden record identity and input binding migrate together");
            var options = after.Service.ToCaptureOptions();
            check(options.NameIndexPath == after.Service.NameIndexPath && options.RsaKeyPath == after.Service.RsaKeyPath && options.DebugDirectory == after.Service.DebugDirectory
                && options.BrowserToken == after.Service.BrowserToken && options.WebSocketPort == after.Service.WebSocketPort, "Saved service settings feed production capture options");
            var fresh = codec.Decode(Object("{}"));
            check(config.Service.BrowserToken != fresh.Service.BrowserToken && fresh.Service.BrowserToken.Length == 43, "Fresh configurations use independent 256-bit browser capabilities");
            check(after.Service.BrowserToken == config.Service.BrowserToken, "Save and relocation retain the browser capability");
            check(!codec.Encode(config).Fields.ContainsKey("overlay_migration_count") && !codec.Encode(config).Fields.ContainsKey("input_recording_enabled"), "Transient migration and running status are not persisted");
            var legacyApp = Path.Combine(root, "legacy"); Directory.CreateDirectory(legacyApp);
            File.WriteAllText(Path.Combine(legacyApp, "endfield_pcap.gui.json"), "{\"theme_mode\":\"dark\"}");
            check(new SettingsCodec(new(legacyApp)).Load().ThemeMode == "dark", "Portable launcher reads legacy settings when profile is absent");
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    public static void Skins(Action<bool, string> check)
    {
        var root = Path.Combine(Path.GetTempPath(), "endfield-skins-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        try
        {
            var damage = NativeSkins.Builtin("damage"); var combo = NativeSkins.Builtin("combo_skill"); var uid = NativeSkins.Builtin("uid_mask");
            check(damage.Subscriptions.SequenceEqual(["analysis_summary"]) && combo.Subscriptions.SequenceEqual(["combo_snapshot"]) && uid.Subscriptions.Count == 0, "Skins derive minimal subscriptions from registered modules");
            var entry = new OverlaySettings { TemplateSettings = Object("{\"_damage_window_scale\":1.75,\"theme\":\"endfield\"}") };
            var updated = NativeSkins.WithValue(entry, damage, "columns", new EvidenceArray([new EvidenceText("rdamage"), new EvidenceText("damage")]));
            check(updated.VisibleColumns.SequenceEqual(["damage", "rdamage"]) && updated.TemplateSettings.Get("_damage_window_scale") is EvidenceReal { Value: 1.75 }, "Instance settings retain declared order, legacy columns and measured scale");
            check(entry.VisibleColumns.Count == 4 && entry.TemplateSettings.Fields.Count == 2, "Changing one instance preserves its original settings");
            var modules = NativeSkins.ResolveModules(updated with { FontScale = 1.25 }, damage);
            check(modules.Single().Settings.Get("theme") is EvidenceText { Value: "endfield" }
                && modules.Single().Settings.Get("_font_scale") is EvidenceReal { Value: 1.25 }, "Renderer receives resolved per-instance theme and font scale");
            var copy = NativeSkins.Builtin("damage");
            ((IDictionary<string, EvidenceValue>)damage.Settings[0].Fields)["label"] = new EvidenceText("modified");
            check(copy.Settings[0].Get("label") is EvidenceText { Value: "显示角色头像" }, "Builtin skin metadata is independent across instances");
            var skinPath = Path.Combine(root, "skin.json"); File.WriteAllBytes(Path.Combine(root, "image.png"), [1]);
            File.WriteAllText(skinPath, "\ufeff{\"schema_version\":2,\"modules\":[{\"type\":\"damage\"},{\"type\":\"combo_skill\"}],\"layout\":{\"direction\":\"horizontal\"},\"theme\":{\"image\":\"image.png\",\"background\":\"transparent\"}}", new UTF8Encoding(false));
            check(NativeSkins.Read(skinPath).Subscriptions.SequenceEqual(["analysis_summary", "combo_snapshot"]), "BOM and local-image combined skin loads");
            foreach (var image in new[] { "../outside.png", Path.Combine(root, "image.png") })
            {
                var rejected = false;
                try { NativeSkins.Parse(Object("{\"schema_version\":2,\"modules\":[{\"type\":\"damage\"}],\"theme\":{\"image\":" + PythonSortedJson.Serialize(new EvidenceText(image)) + "}}"), skinPath); }
                catch (InvalidDataException) { rejected = true; }
                check(rejected, "Skin cannot load absolute or escaped images");
            }
            var oldSkin = Path.Combine(root, "old.json"); File.WriteAllText(oldSkin, "{\"schema_version\":1,\"entry\":\"index.html\"}");
            var payload = Object("{\"overlays\":[{\"id\":\"old\",\"source_type\":\"file\",\"source_value\":" + PythonSortedJson.Serialize(new EvidenceText(oldSkin)) + "},{\"id\":\"valid\",\"source_type\":\"file\",\"source_value\":" + PythonSortedJson.Serialize(new EvidenceText(skinPath)) + "}]}");
            var config = new SettingsCodec(new(root)).Decode(payload);
            check(config.OverlayMigrationCount == 1 && File.Exists(oldSkin) && config.Overlays.Any(item => item.Id == "valid"), "Migration removes unsupported entries, preserves user skin files and v2 instances");
            File.WriteAllBytes(skinPath, new byte[1024 * 1024 + 1]); var tooLarge = false;
            try { NativeSkins.Read(skinPath); } catch (InvalidDataException) { tooLarge = true; }
            check(tooLarge, "Skin size bound is enforced before parsing");
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
