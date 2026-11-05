using System.Globalization;
using System.Net;
using System.Numerics;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace EndfieldLogs.Runtime.Updates;

public sealed record ReleaseUpdate(string Version, DateTimeOffset PublishedAt, Uri Url);

/// <summary>Only reads the official stable release metadata. Downloading is a user browser action.</summary>
public static partial class ReleaseUpdates
{
    public const string Repository = "qhp-ket/EndfieldLogs-Enhanced";
    public static Uri Endpoint { get; } = new($"https://api.github.com/repos/{Repository}/releases/latest");
    private const int Limit = 1024 * 1024;
    private static readonly HttpClient Client = new();
    [GeneratedRegex(@"\Av?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\z")] private static partial Regex Stable();
    [GeneratedRegex(@"\Av?([0-9]+)\.([0-9]+)\.([0-9]+)(.*)\z")] private static partial Regex Installed();
    [GeneratedRegex(@"(?:Z|[+-][0-9]{2}:[0-9]{2})\z")] private static partial Regex Zone();
    public static ReleaseUpdate? Parse(JsonElement payload, string currentVersion, string ignoredVersion = "")
    {
        if (payload.ValueKind != JsonValueKind.Object) return null;
        bool Flag(string name) => payload.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
        string Text(string name) => payload.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString()! : "";
        if (Flag("draft") || Flag("prerelease")) return null;
        var tag = Text("tag_name"); var match = Stable().Match(tag); var installed = Installed().Match(currentVersion); var published = Text("published_at");
        if (!match.Success || !installed.Success || published.Length == 0 || !Zone().IsMatch(published)) return null;
        var date = DateTimeOffset.Parse(published, CultureInfo.InvariantCulture, DateTimeStyles.None);
        var comparison = 0;
        for (var index = 1; index <= 3 && comparison == 0; index++) comparison = BigInteger.Parse(match.Groups[index].Value, CultureInfo.InvariantCulture).CompareTo(BigInteger.Parse(installed.Groups[index].Value, CultureInfo.InvariantCulture));
        if (comparison < 0 || comparison == 0 && !installed.Groups[4].Value.StartsWith('-') || tag.TrimStart('v') == ignoredVersion.TrimStart('v')) return null;
        return new(tag.TrimStart('v'), date, new Uri($"https://github.com/{Repository}/releases/tag/{Uri.EscapeDataString(tag)}"));
    }
    public static async Task<ReleaseUpdate?> CheckAsync(string currentVersion, string ignoredVersion = "", CancellationToken token = default, HttpClient? client = null)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token); deadline.CancelAfter(TimeSpan.FromSeconds(8));
        using HttpRequestMessage request = new(HttpMethod.Get, Endpoint);
        request.Headers.Accept.ParseAdd("application/vnd.github+json"); request.Headers.UserAgent.ParseAdd("Endfield-Logs-Enhanced");
        using var response = await (client ?? Client).SendAsync(request, HttpCompletionOption.ResponseHeadersRead, deadline.Token).ConfigureAwait(false);
        if (response.StatusCode == HttpStatusCode.NotFound) return null;
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength > Limit) throw new InvalidDataException("更新信息过大");
        await using var stream = await response.Content.ReadAsStreamAsync(deadline.Token).ConfigureAwait(false);
        using MemoryStream content = new(); var buffer = new byte[16 * 1024];
        while (true)
        {
            var count = await stream.ReadAsync(buffer, deadline.Token).ConfigureAwait(false); if (count == 0) break;
            if (content.Length + count > Limit) throw new InvalidDataException("更新信息过大");
            content.Write(buffer, 0, count);
        }
        using var document = JsonDocument.Parse(content.ToArray()); return Parse(document.RootElement, currentVersion, ignoredVersion);
    }
}
