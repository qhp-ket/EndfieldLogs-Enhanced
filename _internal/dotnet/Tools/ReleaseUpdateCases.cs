using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using EndfieldLogs.Runtime.Updates;

internal static class ReleaseUpdateCases
{
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var config = test!["config"]!; using var payload = JsonDocument.Parse(config["payload"]!.ToJsonString());
            var release = ReleaseUpdates.Parse(payload.RootElement, config["current"]!.GetValue<string>(), config["ignored"]!.GetValue<string>());
            var actual = release is null ? null : new JsonObject { ["version"] = release.Version, ["published_at"] = release.PublishedAt.ToString("yyyy-MM-dd'T'HH:mm:sszzz", CultureInfo.InvariantCulture), ["url"] = release.Url.AbsoluteUri };
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failed = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Release updates differential: {outcomes.Count} cases, {failed} differences"); return failed == 0 ? 0 : 1;
    }
}
