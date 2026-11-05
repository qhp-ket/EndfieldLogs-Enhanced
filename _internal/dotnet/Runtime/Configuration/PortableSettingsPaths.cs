using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Runtime.Configuration;

public static class PortableSettingsPaths
{
    private static readonly string[] ServicePaths = ["log_dir", "debug_dir", "rsa_key_txt", "name_index_path"];
    public static EvidenceObject Transform(EvidenceObject source, SettingsContext context, bool saving = false)
    {
        var payload = SettingsData.Object(source).Fields.ToDictionary();
        var service = SettingsData.Object(source.Get("service")).Fields.ToDictionary();
        var relative = source.Get("path_base") is EvidenceText { Value: "application" };
        string? previousRoot = null;
        if (!saving && !relative)
        {
            string? Anchor(string key, string suffix)
            {
                var value = SettingsData.PathValue(service.GetValueOrDefault(key) ?? EvidenceNull.Value, context.WorkingDirectory);
                var expected = Path.DirectorySeparatorChar + suffix.Replace('/', Path.DirectorySeparatorChar);
                return value?.EndsWith(expected, StringComparison.OrdinalIgnoreCase) == true ? value[..^expected.Length] : null;
            }
            var rsa = Anchor("rsa_key_txt", "_internal/secrets/client_privkey.pem");
            var names = Anchor("name_index_path", "_internal/jsondata/CharacterNameIndex.json");
            if (rsa is not null && string.Equals(rsa, names, StringComparison.OrdinalIgnoreCase)) previousRoot = rsa;
        }
        EvidenceValue ConvertPath(EvidenceValue value)
        {
            if (value is not EvidenceText text || string.IsNullOrWhiteSpace(text.Value) || text.Value.Contains('\0')) return value;
            try
            {
                if (saving && Path.IsPathFullyQualified(text.Value) && IsWithin(text.Value, context.ApplicationRoot))
                    return new EvidenceText(Path.GetRelativePath(context.ApplicationRoot, text.Value).Replace('\\', '/'));
                if (!saving && !Path.IsPathFullyQualified(text.Value) && relative)
                    return new EvidenceText(Path.GetFullPath(text.Value, context.ApplicationRoot));
                if (!saving && previousRoot is not null && Path.IsPathFullyQualified(text.Value) && IsWithin(text.Value, previousRoot))
                    return new EvidenceText(Path.Combine(context.ApplicationRoot, Path.GetRelativePath(previousRoot, text.Value)));
            }
            catch (Exception error) when (error is ArgumentException or NotSupportedException or IOException) { }
            return value;
        }
        string RecordKey(string value)
        {
            try
            {
                if (EvidenceJson.Parse(value) is EvidenceArray { Items.Count: 3 } parts && parts.Items[0] is EvidenceText path)
                {
                    var converted = (EvidenceText)ConvertPath(path);
                    var normalized = saving ? converted.Value : converted.Value.Replace('/', '\\').ToLowerInvariant();
                    return PythonSortedJson.Serialize(new EvidenceArray([new EvidenceText(normalized), parts.Items[1], parts.Items[2]]));
                }
            }
            catch (FormatException) { }
            return value;
        }
        foreach (var key in ServicePaths) if (service.TryGetValue(key, out var value)) service[key] = ConvertPath(value);
        payload["service"] = new EvidenceObject(service);
        if (source.Get("imported_trace_files") is EvidenceArray imports) payload["imported_trace_files"] = new EvidenceArray(imports.Items.Select(ConvertPath).ToArray());
        if (source.Get("hidden_history_records") is EvidenceArray hidden) payload["hidden_history_records"] = SettingsData.Value(hidden.Items.OfType<EvidenceText>().Select(item => RecordKey(item.Value)).ToArray());
        if (source.Get("input_log_bindings") is EvidenceObject bindings)
        {
            Dictionary<string, EvidenceValue> result = new(StringComparer.Ordinal);
            foreach (var pair in bindings.Fields) result[RecordKey(pair.Key)] = EvidenceJson.Clone(pair.Value);
            payload["input_log_bindings"] = new EvidenceObject(result);
        }
        if (source.Get("overlays") is EvidenceArray overlays)
            payload["overlays"] = new EvidenceArray(overlays.Items.Select(item =>
            {
                if (item is not EvidenceObject row || row.Get("source_type") is not EvidenceText { Value: "file" }) return item;
                var copy = row.Fields.ToDictionary(); copy["source_value"] = ConvertPath(row.Get("source_value")); return new EvidenceObject(copy);
            }).ToArray());
        if (saving) payload["path_base"] = new EvidenceText("application");
        return new(payload);
    }

    internal static bool IsWithin(string path, string root)
    {
        var relative = Path.GetRelativePath(root, path);
        return relative != ".." && !relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) && !Path.IsPathFullyQualified(relative);
    }
}
