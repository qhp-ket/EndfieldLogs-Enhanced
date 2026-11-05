using System.Security.Cryptography;
using System.Text;

namespace EndfieldLogs.Runtime.Realtime;

/// <summary>The restricted HTTP upgrade used by the loopback-only service; no HTTP content is served.</summary>
public sealed record LoopbackWebSocketRequest(string Key, bool Summary, bool Analysis = true, bool Combo = false, bool ReceiveCombo = true)
{
    public string Accept => Convert.ToBase64String(SHA1.HashData(Encoding.ASCII.GetBytes(Key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")));

    public static LoopbackWebSocketRequest? Parse(string headers, string browserToken, out int status)
    {
        status = 400;
        if (headers.Length > 16_384 || headers.Any(value => value > 127 || value < 32 && value is not '\r' and not '\n' and not '\t')) return null;
        var lines = headers.Split("\r\n", StringSplitOptions.None);
        var first = lines[0].Split(' ');
        if (first.Length != 3 || first[0] != "GET" || first[2] != "HTTP/1.1" || !first[1].StartsWith('/')
            || first[1].StartsWith("//", StringComparison.Ordinal) || first[1].Contains('#')) return null;
        Dictionary<string, List<string>> fields = new(StringComparer.OrdinalIgnoreCase);
        foreach (var line in lines.Skip(1))
        {
            if (line.Length == 0) continue;
            var colon = line.IndexOf(':');
            if (colon <= 0 || line[..colon].Any(value => !char.IsAsciiLetterOrDigit(value) && value != '-')) return null;
            var name = line[..colon];
            if (!fields.TryGetValue(name, out var values)) fields[name] = values = [];
            values.Add(line[(colon + 1)..].Trim(' ', '\t'));
        }
        string? One(string name) => fields.TryGetValue(name, out var values) && values.Count == 1 ? values[0] : null;
        if (One("Host") is not { Length: > 0 } || !string.Equals(One("Upgrade"), "websocket", StringComparison.OrdinalIgnoreCase)
            || !fields.TryGetValue("Connection", out var connections)
            || !connections.SelectMany(value => value.Split(',')).Any(value => value.Trim().Equals("Upgrade", StringComparison.OrdinalIgnoreCase))
            || One("Sec-WebSocket-Version") != "13" || One("Sec-WebSocket-Key") is not { } key
            || fields.ContainsKey("Transfer-Encoding") || fields.ContainsKey("Content-Length")) return null;
        try { if (Convert.FromBase64String(key).Length != 16) return null; }
        catch (FormatException) { return null; }
        var queryStart = first[1].IndexOf('?');
        var query = queryStart < 0 ? "" : first[1][(queryStart + 1)..];
        Dictionary<string, List<string>> parameters = new(StringComparer.Ordinal);
        foreach (var item in query.Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var parts = item.Split('=', 2);
            string Decode(string value) => Uri.UnescapeDataString(value.Replace('+', ' '));
            var name = Decode(parts[0]); var value = parts.Length == 1 ? "" : Decode(parts[1]);
            if (!parameters.TryGetValue(name, out var values)) parameters[name] = values = [];
            values.Add(value);
        }
        if (fields.TryGetValue("Origin", out var origins))
        {
            status = 403;
            if (origins.Count != 1 || browserToken.Length < 43 || !parameters.TryGetValue("access_token", out var tokens)
                || tokens.Count != 1 || tokens[0].Length > 256
                || !CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(tokens[0]), Encoding.UTF8.GetBytes(browserToken))) return null;
        }
        status = 101;
        var mode = parameters.TryGetValue("analysis", out var analysis) && analysis.Count == 1 ? analysis[0] : "full";
        var combo = parameters.TryGetValue("combo", out var visual) && visual.Count == 1 && visual[0] == "1";
        var receiveCombo = !parameters.TryGetValue("combo", out var receive) || receive.Count != 1 || receive[0] != "0";
        return new(key, mode == "summary", mode != "none", combo, receiveCombo);
    }
}
