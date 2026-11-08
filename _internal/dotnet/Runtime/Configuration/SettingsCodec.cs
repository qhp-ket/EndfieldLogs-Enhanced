using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Runtime.Configuration;

/// <summary>Existing Python/Qt settings schema, including portable references and one-time retired-overlay migration.</summary>
public sealed partial class SettingsCodec(SettingsContext context, SettingsStorage? storage = null)
{
    private readonly SettingsStorage storage = storage ?? new();
    public SettingsContext Context => context;
    private static readonly string[] Columns = ["damage", "damage_rate", "rdamage", "rdamage_rate"];
    private static readonly HashSet<string> WidthKeys = ["skills", "participants", "contributions", "hits", "enemy_stats", "enemy_poise"];
    [GeneratedRegex(@"\A[A-Za-z0-9_-]{43,128}\z")]
    private static partial Regex Token();
    public ApplicationSettings Load(string? path = null)
    {
        path ??= context.DefaultPath;
        if (!File.Exists(path) && !File.Exists(path + ".bak"))
        {
            var legacy = Path.Combine(context.ApplicationRoot, "endfield_pcap.gui.json");
            if (File.Exists(legacy)) path = legacy;
        }
        return Decode(storage.Read(path));
    }
    public void Save(ApplicationSettings settings, string? path = null) => storage.Write(path ?? context.DefaultPath, Encode(settings));

    public ApplicationSettings Decode(EvidenceObject source)
    {
        var payload = PortableSettingsPaths.Transform(source, context);
        var defaults = ServiceSettings.Default(context);
        var service = SettingsData.Object(payload.Get("service"));
        string ServiceString(string key, string fallback) => SettingsData.String(SettingsData.Get(service, key, fallback));
        string ServicePath(string key, string fallback) => SettingsData.PathValue(service.Get(key), context.WorkingDirectory) ?? fallback;
        var port = SettingsData.Integer(service.Get("ws_port"));
        var token = service.Get("ws_browser_token") is EvidenceText text && Token().IsMatch(text.Value) ? text.Value : defaults.BrowserToken;
        var overlays = new List<OverlaySettings>(); var removed = 0;
        if (payload.Get("overlays") is EvidenceArray entries)
            foreach (var raw in entries.Items.OfType<EvidenceObject>())
            {
                var type = SettingsData.Get(raw, "source_type", "builtin");
                var sourceType = type is EvidenceText t ? t.Value : "";
                var sourceValue = SettingsData.Or(raw.Get("source_value"), "damage").Trim().ToLowerInvariant();
                if (sourceType == "builtin" && sourceValue is not ("damage" or "combo_skill" or "uid_mask") || sourceType is not ("builtin" or "file")) { removed++; continue; }
                try
                {
                    var entry = ReadOverlay(raw, sourceType);
                    NativeSkins.For(entry, context);
                    overlays.Add(entry);
                }
                catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or ArgumentException or FormatException or System.Text.DecoderFallbackException) { removed++; }
            }
        if (overlays.Count == 0) overlays.AddRange(DefaultOverlays());
        for (var index = 0; index < overlays.Count; index++)
            if (overlays[index].SourceType == "builtin" && overlays[index].SourceValue.Trim().ToLowerInvariant() == "damage") overlays[index] = overlays[index] with { SourceValue = "damage", Name = "伤害统计" };
        if (!overlays.Any(entry => entry.SourceType == "builtin" && entry.SourceValue.Trim().ToLowerInvariant() == "damage")) overlays.Insert(0, new());
        if (!overlays.Any(entry => entry.SourceType == "builtin" && entry.SourceValue.Trim().ToLowerInvariant() == "uid_mask")) overlays.Add(new() { SourceValue = "uid_mask", Name = "UID遮挡" });
        if (!overlays.Any(entry => entry.SourceType == "builtin" && entry.SourceValue.Trim().ToLowerInvariant() == "combo_skill"))
        {
            var index = overlays.FindIndex(entry => entry.SourceValue is "input" or "uid_mask");
            overlays.Insert(index < 0 ? overlays.Count : index, Combo());
        }
        var ids = overlays.Select(entry => entry.Id).ToHashSet(StringComparer.Ordinal);
        var restore = SettingsData.Strings(payload.Get("overlay_restore_ids")).Where(ids.Contains).Distinct(StringComparer.Ordinal).ToArray();
        if (!payload.Fields.ContainsKey("overlay_restore_ids") && payload.Get("overlays_visible") is EvidenceBoolean { Value: false })
        {
            restore = overlays.Where(entry => !entry.Hidden).Select(entry => entry.Id).ToArray();
            overlays = overlays.Select(entry => entry with { Hidden = true }).ToList();
        }
        return new()
        {
            Service = defaults with
            {
                WebSocketPort = port is not null && port.Value >= 1 && port.Value <= 65535 ? (int)port.Value : defaults.WebSocketPort,
                BrowserToken = token, LogDirectory = ServicePath("log_dir", defaults.LogDirectory),
                LogLevel = ServiceString("log_level", defaults.LogLevel), GameExecutable = ServiceString("game_exe", defaults.GameExecutable),
                TraceFormat = service.Get("trace_format") is EvidenceText { Value: "legacy" or "jsonl" } format ? format.Value : defaults.TraceFormat,
                NpcapDevice = ServiceString("npcap_device", defaults.NpcapDevice), NativeGameDirectory = ServicePath("dll_dir", defaults.NativeGameDirectory),
                DebugEnabled = SettingsData.Truth(service.Get("debug_enabled")), DebugDirectory = ServicePath("debug_dir", defaults.DebugDirectory),
                RsaKeyPath = ServicePath("rsa_key_txt", defaults.RsaKeyPath), NameIndexPath = ServicePath("name_index_path", defaults.NameIndexPath),
                MergeMultiPhaseEnemyBattles = SettingsData.Truth(service.Get("merge_multi_phase_enemy_battles")),
            },
            Overlays = overlays, OverlayMigrationCount = removed, OverlayRestoreIds = restore,
            ThemeMode = Theme(payload.Get("theme_mode")), FontPercent = Font(payload.Get("gui_font_percent")),
            BattleFontPercent = Font(SettingsData.Get(payload, "battle_font_percent", 115)),
            ToggleOverlaysHotkey = Hotkey(payload.Get("toggle_overlays_hotkey")), ToggleGuiHotkey = SettingsData.Or(payload.Get("toggle_gui_hotkey"), "Ctrl+Shift+O"),
            ToggleRecordingHotkey = SettingsData.Or(payload.Get("toggle_recording_hotkey"), "Ctrl+I"),
            StartCaptureOnLaunch = SettingsData.IsTrue(payload.Get("start_capture_on_launch")),
            CheckUpdatesOnStart = SettingsData.IsTrue(SettingsData.Get(payload, "check_updates_on_start", true)),
            IgnoredUpdateVersion = SettingsData.Or(payload.Get("ignored_update_version"), ""),
            ShowCharacterAvatars = SettingsData.IsTrue(SettingsData.Get(payload, "show_character_avatars", true)),
            CharacterAvatarPercent = Avatar(SettingsData.Get(payload, "character_avatar_percent", 100)),
            StartInputRecordingOnLaunch = SettingsData.IsTrue(payload.Get("start_input_recording_on_launch")),
            InputSettings = SettingsData.Object(payload.Get("input_settings")), InputLogBindings = SettingsData.Object(payload.Get("input_log_bindings")), VisionSettings = SettingsData.Object(payload.Get("vision_settings")),
            BattleTableWidths = TableWidths(payload.Get("battle_table_widths")), BattleLaneConfigs = LaneConfigs(payload.Get("battle_lane_configs")),
            ImportedTraceFiles = SettingsData.Strings(payload.Get("imported_trace_files")).Select(path => SettingsData.PathValue(new EvidenceText(path), context.WorkingDirectory))
                .OfType<string>().Distinct(StringComparer.OrdinalIgnoreCase).ToArray(),
            HiddenHistoryRecords = SettingsData.Strings(payload.Get("hidden_history_records")).ToArray(),
        };
    }

    public EvidenceObject Encode(ApplicationSettings settings)
    {
        var service = settings.Service;
        var servicePayload = SettingsData.Make(("ws_port", service.WebSocketPort), ("ws_browser_token", service.BrowserToken), ("log_dir", service.LogDirectory),
            ("log_level", service.LogLevel), ("game_exe", service.GameExecutable), ("npcap_device", service.NpcapDevice), ("dll_dir", service.NativeGameDirectory),
            ("debug_enabled", service.DebugEnabled), ("debug_dir", service.DebugDirectory), ("rsa_key_txt", service.RsaKeyPath), ("name_index_path", service.NameIndexPath),
            ("merge_multi_phase_enemy_battles", service.MergeMultiPhaseEnemyBattles));
        ((IDictionary<string, EvidenceValue>)servicePayload.Fields)["trace_format"] = new EvidenceText(service.TraceFormat);
        return PortableSettingsPaths.Transform(SettingsData.Make(
            ("service", servicePayload),
            ("overlays", settings.Overlays.Select(EncodeOverlay).ToArray()), ("overlay_restore_ids", settings.OverlayRestoreIds),
            ("theme_mode", Theme(new EvidenceText(settings.ThemeMode))), ("gui_font_percent", Font(SettingsData.Value(settings.FontPercent))),
            ("battle_font_percent", Font(SettingsData.Value(settings.BattleFontPercent))),
            ("start_capture_on_launch", settings.StartCaptureOnLaunch), ("check_updates_on_start", settings.CheckUpdatesOnStart), ("ignored_update_version", settings.IgnoredUpdateVersion),
            ("show_character_avatars", settings.ShowCharacterAvatars), ("character_avatar_percent", Avatar(SettingsData.Value(settings.CharacterAvatarPercent))),
            ("start_input_recording_on_launch", settings.StartInputRecordingOnLaunch), ("input_settings", settings.InputSettings), ("input_log_bindings", settings.InputLogBindings), ("vision_settings", settings.VisionSettings),
            ("battle_table_widths", TableWidths(settings.BattleTableWidths)), ("battle_lane_configs", LaneConfigs(settings.BattleLaneConfigs)),
            ("toggle_overlays_hotkey", Hotkey(new EvidenceText(settings.ToggleOverlaysHotkey))), ("toggle_gui_hotkey", settings.ToggleGuiHotkey),
            ("toggle_recording_hotkey", settings.ToggleRecordingHotkey),
            ("imported_trace_files", settings.ImportedTraceFiles), ("hidden_history_records", settings.HiddenHistoryRecords)), context, saving: true);
    }

    public static EvidenceObject EncodeOverlay(OverlaySettings entry) => SettingsData.Make(("id", entry.Id), ("name", entry.Name), ("source_type", entry.SourceType), ("source_value", entry.SourceValue),
        ("enabled", entry.Enabled), ("hidden", entry.Hidden), ("locked", entry.Locked), ("click_through", entry.ClickThrough), ("opacity", entry.Opacity), ("scale", entry.Scale),
        ("font_scale", entry.FontScale), ("template_settings", entry.TemplateSettings), ("bar_mode", entry.BarMode), ("visible_columns", entry.VisibleColumns), ("overlay_theme", entry.Theme),
        ("geometry", entry.Geometry is { } geometry ? SettingsData.Make(("x", geometry.X), ("y", geometry.Y), ("width", geometry.Width), ("height", geometry.Height)) : null));

    private static OverlaySettings ReadOverlay(EvidenceObject row, string sourceType)
    {
        var value = SettingsData.Or(row.Get("source_value"), "").Trim();
        if (sourceType == "builtin" && value.Length == 0) value = "damage";
        var name = SettingsData.Or(row.Get("name"), "").Trim();
        if (name.Length == 0) name = value switch { "damage" => "伤害统计", "combo_skill" => "连携cd监控", "uid_mask" => "UID遮挡", _ => "悬浮窗" };
        return new()
        {
            Id = SettingsData.Or(row.Get("id"), Guid.NewGuid().ToString()), Name = name, SourceType = sourceType, SourceValue = value,
            Enabled = SettingsData.Truth(SettingsData.Get(row, "enabled", true)), Hidden = SettingsData.Truth(row.Get("hidden")),
            Locked = SettingsData.Truth(row.Get("locked")), ClickThrough = SettingsData.Truth(row.Get("click_through")),
            Opacity = Math.Clamp(SettingsData.Number(row.Get("opacity"), 1), .1, 1), Scale = Math.Clamp(SettingsData.Number(row.Get("scale"), 1), .5, 3),
            FontScale = Math.Clamp(SettingsData.Number(SettingsData.Get(row, "font_scale", row.Get("scale")), 1), .5, 3),
            TemplateSettings = SettingsData.Object(row.Get("template_settings")), BarMode = row.Get("bar_mode") is EvidenceText { Value: "dps" } ? "dps" : "rdps",
            VisibleColumns = row.Get("visible_columns") is EvidenceArray columns ? Columns.Where(key => columns.Items.Any(item => item is EvidenceText text && text.Value == key)).ToArray() : Columns.ToArray(),
            Theme = row.Get("overlay_theme") is EvidenceText theme && theme.Value is "dark" or "transparent" or "endfield" ? theme.Value : "light",
            Geometry = row.Get("geometry") is EvidenceObject geometry ? new(SettingsData.Int(geometry.Get("x"), 0), SettingsData.Int(geometry.Get("y"), 0),
                Math.Max(1, SettingsData.Int(geometry.Get("width"), 980)), Math.Max(1, SettingsData.Int(geometry.Get("height"), 492))) : null,
        };
    }
    private static string Theme(EvidenceValue value) => SettingsData.Or(value, "system").Trim().ToLowerInvariant() is var mode && mode is "light" or "dark" or "system" ? mode : "system";
    private static int Font(EvidenceValue value) => SettingsData.Int(value, 115, 80, 180, allowBoolean: true);
    private static int Avatar(EvidenceValue value) => value is EvidenceInteger ? SettingsData.Int(value, 100, 50, 300) : 100;
    private static string Hotkey(EvidenceValue value) => SettingsData.Or(value, "Ctrl+O").Trim() is { Length: > 0 } text ? text : "Ctrl+O";
    private static OverlaySettings Combo() => new() { SourceValue = "combo_skill", Name = "连携 CD（图像识别）", Enabled = false };
    public static IReadOnlyList<OverlaySettings> DefaultOverlays() => [new(), Combo(), new() { SourceValue = "uid_mask", Name = "UID遮挡" }];

    private static EvidenceObject TableWidths(EvidenceValue value)
    {
        Dictionary<string, EvidenceValue> result = new(StringComparer.Ordinal);
        if (value is EvidenceObject map)
            foreach (var (key, widths) in map.Fields)
                if (WidthKeys.Contains(key) && widths is EvidenceArray array)
                    result[key] = SettingsData.Value(array.Items.Take(12).Select(width => (int)Math.Clamp(Math.Truncate(SettingsData.Number(width, 100)), 40, 2000)).ToArray());
        return new(result);
    }
    public static EvidenceObject LaneConfigs(EvidenceValue value)
    {
        Dictionary<string, EvidenceValue> result = new(StringComparer.Ordinal);
        if (value is not EvidenceObject owners) return new(result);
        foreach (var (owner, raw) in owners.Fields.Take(500))
        {
            if (owner.Length == 0 || SettingsData.Length(owner) > 160 || raw is not EvidenceArray rows) continue;
            List<EvidenceValue> lanes = []; HashSet<string> ids = [], assigned = [];
            for (var index = 0; index < Math.Min(32, rows.Items.Count); index++)
            {
                if (rows.Items[index] is not EvidenceObject row || row.Get("skills") is not EvidenceArray skills) continue;
                var key = SettingsData.Slice(SettingsData.Or(row.Get("id"), "track-" + index), 80);
                if (!ids.Add(key)) continue;
                var selected = skills.Items.Take(256).OfType<EvidenceText>().Select(item => item.Value)
                    .Where(item => item.Length > 0 && SettingsData.Length(item) <= 1024 && assigned.Add(item)).ToArray();
                lanes.Add(SettingsData.Make(("id", key), ("name", SettingsData.Slice(SettingsData.Or(row.Get("name"), "轨道 " + (index + 1)), 60)), ("skills", selected)));
            }
            if (lanes.Count > 0 || rows.Items.Count == 0) result[owner] = new EvidenceArray(lanes);
        }
        return new(result);
    }
}
