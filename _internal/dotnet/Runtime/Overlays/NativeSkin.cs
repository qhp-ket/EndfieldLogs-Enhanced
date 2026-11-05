using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Storage;

namespace EndfieldLogs.Runtime.Overlays;

public sealed record NativeSkin(string? Path, string Name, IReadOnlyList<string> Subscriptions,
    IReadOnlyList<EvidenceObject> Settings, EvidenceObject Window, IReadOnlyList<EvidenceObject> Modules,
    EvidenceObject Layout, EvidenceObject Theme);
public sealed record NativeSkinModule(string Type, EvidenceObject Settings);

/// <summary>Declarative v2 skins: validated data, no executable expressions or subscriber-controlled full reports.</summary>
public static partial class NativeSkins
{
    private static readonly Dictionary<string, string[]> ModuleSettings = new(StringComparer.Ordinal)
    {
        ["damage"] = ["bar_mode", "columns", "theme", "show_character_avatars", "avatar_size_percent"],
        ["combo_skill"] = ["display_style", "theme", "show_character_avatars", "avatar_size_percent"],
        ["uid_mask"] = ["shape"],
    };
    private static readonly Dictionary<string, string[]> Options = new(StringComparer.Ordinal)
    {
        ["bar_mode"] = ["dps", "rdps"], ["columns"] = ["damage", "damage_rate", "rdamage", "rdamage_rate"],
        ["theme"] = ["light", "dark", "transparent", "endfield"], ["show_character_avatars"] = ["on", "off"],
        ["display_style"] = ["circles", "bars"], ["shape"] = ["rectangle", "rounded"],
    };
    private static readonly HashSet<string> LegacyFields = ["bar_mode", "visible_columns", "overlay_theme"];
    private static InvalidDataException Invalid(string message) => new(message);
    private static void Keys(EvidenceObject value, params string[] allowed)
    { if (value.Fields.Keys.Except(allowed, StringComparer.Ordinal).Any()) throw Invalid("包含未支持的字段"); }
    private static bool ExactInt(EvidenceValue value, int min, int max) => value is EvidenceInteger integer && integer.Value >= min && integer.Value <= max;
    private static bool Valid(string key, EvidenceValue value) => key switch
    {
        "avatar_size_percent" => ExactInt(value, 50, 300),
        "columns" => value is EvidenceArray array && array.Items.All(item => item is EvidenceText text && Options[key].Contains(text.Value)),
        _ => value is EvidenceText text && Options[key].Contains(text.Value),
    };
    public static NativeSkin Read(string path)
    {
        path = Path.GetFullPath(path);
        using FileStream stream = new(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length > 1024 * 1024) throw Invalid("皮肤文件上限为 1 MiB");
        using MemoryStream content = new(); stream.CopyTo(content);
        var text = new UTF8Encoding(false, true).GetString(content.ToArray());
        if (text.StartsWith('\ufeff')) text = text[1..];
        return Parse(EvidenceJson.Parse(text), path);
    }
    public static NativeSkin Builtin(string type)
    {
        // The reference loads these directory names on a case-insensitive Windows filesystem.
        if (type.Equals("damage", StringComparison.OrdinalIgnoreCase)) type = "damage";
        if (type.Equals("uid_mask", StringComparison.OrdinalIgnoreCase)) type = "uid_mask";
        if (!ModuleSettings.ContainsKey(type)) throw Invalid("未知内置浮窗");
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("EndfieldLogs.Skins." + type + ".json")
            ?? throw Invalid("缺少内置皮肤");
        using StreamReader reader = new(stream, Encoding.UTF8);
        return Parse(EvidenceJson.Parse(reader.ReadToEnd()));
    }
    public static NativeSkin For(OverlaySettings entry, SettingsContext context) => entry.SourceType switch
    {
        "builtin" => Builtin(entry.SourceValue),
        "file" when string.Equals(Path.GetExtension(entry.SourceValue), ".json", StringComparison.OrdinalIgnoreCase) => Read(Path.GetFullPath(entry.SourceValue, context.WorkingDirectory)),
        _ => throw Invalid("仅支持内置浮窗或 v2 JSON 原生皮肤"),
    };

    public static NativeSkin Parse(EvidenceValue value, string? path = null)
    {
        if (value is not EvidenceObject data || !EvidenceJson.PythonEquals(data.Get("schema_version"), new EvidenceInteger(2)))
            throw Invalid("原生皮肤 schema_version 必须为 2");
        Keys(data, "schema_version", "name", "window", "settings", "modules", "layout", "theme");
        var settingsValue = SettingsData.Get(data, "settings", Array.Empty<object>());
        if (settingsValue is not EvidenceArray { Items.Count: <= 64 } settingsArray) throw Invalid("模板 settings 必须为数组");
        Dictionary<string, EvidenceObject> declarations = new(StringComparer.Ordinal);
        foreach (var raw in settingsArray.Items)
        {
            if (raw is not EvidenceObject item || item.Get("key") is not EvidenceText { Value.Length: > 0 } key || !declarations.TryAdd(key.Value, item))
                throw Invalid("模板设置 key 不能为空或重复");
            if (item.Get("type") is not EvidenceText type || type.Value is not ("select" or "multiselect" or "slider")) throw Invalid("模板设置类型仅支持 select / multiselect / slider");
            if (type.Value == "slider")
            {
                if (!ExactInt(item.Get("min"), -16384, 16384) || !ExactInt(item.Get("max"), -16384, 16384)
                    || !ExactInt(item.Get("default"), SettingsData.Int(item.Get("min"), 0), SettingsData.Int(item.Get("max"), 0))
                    || item.Get("legacy_field") is not EvidenceNull) throw Invalid("模板滑条需要有效的整数范围，不能绑定 legacy_field");
                continue;
            }
            if (item.Get("options") is not EvidenceArray { Items.Count: > 0 } choices) throw Invalid("模板选项不能为空");
            List<string> options = [];
            foreach (var choice in choices.Items)
            {
                if (choice is not EvidenceObject option || option.Get("value") is not EvidenceText optionText || options.Contains(optionText.Value))
                    throw Invalid("模板选项 value 必须为不重复的字符串");
                options.Add(optionText.Value);
            }
            if (type.Value == "select" && (item.Get("default") is not EvidenceText selected || !options.Contains(selected.Value))
                || type.Value == "multiselect" && (item.Get("default") is not EvidenceArray defaults || defaults.Items.Any(v => v is not EvidenceText t || !options.Contains(t.Value))))
                throw Invalid("模板默认值不在选项内");
            if (item.Get("legacy_field") is not EvidenceNull && (item.Get("legacy_field") is not EvidenceText legacy || !LegacyFields.Contains(legacy.Value))) throw Invalid("未知 legacy_field");
        }
        EvidenceObject ObjectField(string key) => data.Fields.TryGetValue(key, out var field)
            ? field as EvidenceObject ?? throw Invalid(key + " 必须为对象") : SettingsData.Empty();
        var window = ObjectField("window");
        Keys(window, "min_width", "min_height", "default_width", "default_height");
        if (window.Fields.Values.Any(v => !ExactInt(v, 1, 16384))) throw Invalid("模板窗口尺寸无效");
        if (data.Get("modules") is not EvidenceArray { Items.Count: >= 1 and <= 16 } moduleArray) throw Invalid("皮肤需要 1–16 个原生模块");
        List<EvidenceObject> modules = []; HashSet<string> subscriptions = [];
        foreach (var raw in moduleArray.Items)
        {
            if (raw is not EvidenceObject module || module.Get("type") is not EvidenceText type || !ModuleSettings.TryGetValue(type.Value, out var allowed)) throw Invalid("模块仅支持 damage / combo_skill / uid_mask");
            Keys(module, "type", "settings", "setting_bindings");
            var bindings = allowed.Where(declarations.ContainsKey).ToDictionary(key => key, key => key, StringComparer.Ordinal);
            foreach (var field in new[] { "settings", "setting_bindings" })
            {
                if (!module.Fields.TryGetValue(field, out var fieldValue)) continue;
                if (fieldValue is not EvidenceObject values) throw Invalid("模块设置无效");
                Keys(values, allowed);
                foreach (var (key, entry) in values.Fields)
                {
                    if (field == "settings" && !Valid(key, entry)) throw Invalid("模块设置值无效");
                    if (field == "setting_bindings")
                    {
                        if (entry is not EvidenceText target || !declarations.ContainsKey(target.Value)) throw Invalid("模块绑定必须引用已声明的设置");
                        bindings[key] = target.Value;
                    }
                }
            }
            foreach (var (key, target) in bindings)
            {
                var item = declarations[target];
                var expected = key == "avatar_size_percent" ? "slider" : key == "columns" ? "multiselect" : "select";
                if (item.Get("type") is not EvidenceText kind || kind.Value != expected || !Valid(key, item.Get("default"))) throw Invalid("模块绑定与设置类型或默认值不匹配");
                if (expected == "slider")
                {
                    if (!ExactInt(item.Get("min"), 50, 300) || !ExactInt(item.Get("max"), 50, 300)) throw Invalid("模块绑定范围无效");
                }
                else if (((EvidenceArray)item.Get("options")).Items.Any(option => !Options[key].Contains(((EvidenceText)((EvidenceObject)option).Get("value")).Value))) throw Invalid("模块绑定选项无效");
            }
            if (type.Value == "damage") subscriptions.Add("analysis_summary");
            if (type.Value == "combo_skill") subscriptions.Add("combo_snapshot");
            modules.Add((EvidenceObject)EvidenceJson.Clone(module));
        }
        var layout = ObjectField("layout"); Keys(layout, "direction");
        var direction = SettingsData.Get(layout, "direction", "single");
        if (direction is not EvidenceText layoutText || layoutText.Value is not ("single" or "horizontal" or "vertical") || modules.Count > 1 && layoutText.Value == "single") throw Invalid("多个模块需要横向或纵向排列");
        var theme = ObjectField("theme");
        Keys(theme, "font_family", "background", "foreground", "muted", "accent", "ready", "border", "radius", "spacing", "padding", "border_width", "image");
        foreach (var (key, entry) in theme.Fields)
        {
            if (key is "radius" or "spacing" or "padding" or "border_width")
            {
                if (entry is not (EvidenceInteger or EvidenceReal) || SettingsData.Number(entry, -1) is < 0 or > 128) throw Invalid("主题尺寸参数必须为 0–128 的有限数值");
            }
            else if (key == "font_family")
            { if (entry is not EvidenceText font || SettingsData.Length(font.Value) > 120) throw Invalid("主题字体名称无效"); }
            else if (key == "image")
            {
                if (entry is not EvidenceText image || path is null || Path.IsPathRooted(image.Value)) throw Invalid("主题图片必须使用皮肤目录内的相对路径");
                var directory = Path.GetDirectoryName(Path.GetFullPath(path))!;
                var resolved = PhysicalPaths.Resolve(Path.GetFullPath(image.Value, directory));
                if (!PortableSettingsPaths.IsWithin(resolved, PhysicalPaths.Resolve(directory)) || !File.Exists(resolved) || !new[] { ".png", ".jpg", ".jpeg", ".bmp", ".webp" }.Contains(Path.GetExtension(resolved).ToLowerInvariant())) throw Invalid("主题图片不存在或格式无效");
            }
            else if (entry is not EvidenceText color || !Color().IsMatch(color.Value)) throw Invalid("主题颜色使用 #RRGGBB / #AARRGGBB / transparent");
        }
        return new(path, SettingsData.Slice(SettingsData.String(SettingsData.Get(data, "name", path is null ? "原生皮肤" : Path.GetFileNameWithoutExtension(path))), 160),
            subscriptions.Order(StringComparer.Ordinal).ToArray(), declarations.Values.Select(item => (EvidenceObject)EvidenceJson.Clone(item)).ToArray(),
            SettingsData.Object(window), modules, SettingsData.Object(layout), SettingsData.Object(theme));
    }

    [GeneratedRegex(@"\A(?:#[\da-fA-F]{6}(?:[\da-fA-F]{2})?|transparent)\z")]
    private static partial Regex Color();

    public static EvidenceObject Values(OverlaySettings entry, NativeSkin skin)
    {
        Dictionary<string, EvidenceValue> result = new(StringComparer.Ordinal);
        foreach (var item in skin.Settings)
        {
            var key = ((EvidenceText)item.Get("key")).Value;
            var legacy = item.Get("legacy_field") is EvidenceText field ? field.Value switch
            { "bar_mode" => SettingsData.Value(entry.BarMode), "visible_columns" => SettingsData.Value(entry.VisibleColumns), "overlay_theme" => SettingsData.Value(entry.Theme), _ => item.Get("default") } : item.Get("default");
            var value = entry.TemplateSettings.Fields.GetValueOrDefault(key) ?? legacy;
            if (item.Get("type") is EvidenceText { Value: "slider" })
                value = value is EvidenceInteger integer ? new EvidenceInteger(System.Numerics.BigInteger.Clamp(integer.Value, ((EvidenceInteger)item.Get("min")).Value, ((EvidenceInteger)item.Get("max")).Value)) : item.Get("default");
            else
            {
                var allowed = ((EvidenceArray)item.Get("options")).Items.Cast<EvidenceObject>().Select(option => option.Get("value")).ToArray();
                if (item.Get("type") is EvidenceText { Value: "multiselect" })
                    value = value is EvidenceArray array ? new EvidenceArray(allowed.Where(option => array.Items.Any(v => EvidenceJson.PythonEquals(v, option))).ToArray()) : item.Get("default");
                else if (!allowed.Any(option => EvidenceJson.PythonEquals(value, option))) value = item.Get("default");
            }
            result[key] = EvidenceJson.Clone(value);
        }
        return new(result);
    }

    public static OverlaySettings WithValue(OverlaySettings entry, NativeSkin skin, string key, EvidenceValue value)
    {
        var declaration = skin.Settings.FirstOrDefault(item => item.Get("key") is EvidenceText text && text.Value == key);
        if (declaration is null) return entry;
        var settings = Values(entry, skin).Fields.ToDictionary(); settings[key] = EvidenceJson.Clone(value);
        var normalized = Values(entry with { TemplateSettings = new(settings) }, skin).Fields.ToDictionary();
        foreach (var scale in new[] { "_damage_window_scale", "_combo_window_scale", "_native_window_scale" })
            if (entry.TemplateSettings.Fields.TryGetValue(scale, out var saved)) normalized[scale] = EvidenceJson.Clone(saved);
        var result = entry with { TemplateSettings = new(normalized) };
        return declaration.Get("legacy_field") is EvidenceText legacy ? legacy.Value switch
        {
            "bar_mode" => result with { BarMode = ((EvidenceText)normalized[key]).Value },
            "overlay_theme" => result with { Theme = ((EvidenceText)normalized[key]).Value },
            "visible_columns" => result with { VisibleColumns = SettingsData.Strings(normalized[key]).ToArray() }, _ => result,
        } : result;
    }

    public static IReadOnlyList<NativeSkinModule> ResolveModules(OverlaySettings entry, NativeSkin skin)
    {
        var values = Values(entry, skin);
        return skin.Modules.Select(module =>
        {
            var settings = values.Fields.ToDictionary(pair => pair.Key, pair => EvidenceJson.Clone(pair.Value), StringComparer.Ordinal);
            if (module.Get("settings") is EvidenceObject constants)
                foreach (var (key, value) in constants.Fields) settings[key] = EvidenceJson.Clone(value);
            if (module.Get("setting_bindings") is EvidenceObject bindings)
                foreach (var (key, target) in bindings.Fields) settings[key] = EvidenceJson.Clone(values.Get(((EvidenceText)target).Value));
            settings["_font_scale"] = new EvidenceReal(entry.FontScale);
            return new NativeSkinModule(((EvidenceText)module.Get("type")).Value, new(settings));
        }).ToArray();
    }
}
