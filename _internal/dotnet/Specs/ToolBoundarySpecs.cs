using System.Diagnostics;
using System.Text.Json.Nodes;

internal static class ToolBoundarySpecs
{
    public static void Run(Action<bool, string> check)
    {
        var tool = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,
            "../../../../Tools/bin", new DirectoryInfo(AppContext.BaseDirectory).Parent!.Name,
            "net10.0/EndfieldLogs.Tools.dll"));
        var directory = Path.Combine(Path.GetTempPath(), "endfield-tool-spec-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var input = Path.Combine(directory, "input.json");
        var output = Path.Combine(directory, "output.json");
        try
        {
            RunCase(null, 1, "FileNotFoundException", "Missing fixture");
            RunCase("[broken", 1, "JsonReaderException", "Malformed fixture");
            RunCase("null", 1, "Exception", "Invalid fixture shape");
            RunCase("""[{"name":"null evidence","kind":"validate","evidence":null,"expected":["missing_official_timer_evidence"]}]""",
                0, "", "Null evidence is valid");
            SpecScope("foundations,foundations", true);
            SpecScope("foundations,not-a-real-group", false);
        }
        finally
        {
            File.Delete(input);
            File.Delete(output);
            Directory.Delete(directory);
        }

        void RunCase(string? contents, int expectedExit, string diagnostic, string description)
        {
            if (contents is not null) File.WriteAllText(input, contents);
            var start = new ProcessStartInfo(Environment.ProcessPath!)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            foreach (var argument in new[] { tool, "compare-official-timers", input, output })
                start.ArgumentList.Add(argument);
            using var process = Process.Start(start)!;
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(15000))
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit();
                throw new InvalidOperationException(description + " did not exit within 15 seconds");
            }
            check(process.ExitCode == expectedExit, description + " exit code: " + stdout.Result + stderr.Result);
            check(diagnostic.Length == 0 ? stderr.Result.Length == 0 : stderr.Result.Contains(diagnostic, StringComparison.Ordinal),
                description + " diagnostics");
        }

        void SpecScope(string names, bool valid)
        {
            var start = new ProcessStartInfo(Environment.ProcessPath!)
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            };
            foreach (var argument in new[] { typeof(ToolBoundarySpecs).Assembly.Location, "--groups", names })
                start.ArgumentList.Add(argument);
            using var process = Process.Start(start)!;
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(15000))
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit();
                throw new InvalidOperationException("Scoped Specs CLI did not exit within 15 seconds");
            }
            check(process.ExitCode == (valid ? 0 : 2), "Scoped Specs CLI rejects unknown groups: " + stderr.Result);
            if (valid)
            {
                var summary = JsonNode.Parse(stdout.Result)!;
                check(summary["groups"] is JsonObject { Count: 1 } groups && groups.ContainsKey("foundations")
                    && summary["not_selected"]!.AsArray().Any(value => value!.GetValue<string>() == "capture"),
                    "Scoped Specs CLI deduplicates names and reports omitted groups");
            }
            else check(stdout.Result.Length == 0 && stderr.Result.Contains("Unknown spec groups", StringComparison.Ordinal),
                "Invalid scope fails before any selected group is executed");
        }
    }
}
