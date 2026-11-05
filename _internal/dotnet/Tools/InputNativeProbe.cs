using System.Diagnostics;
using System.Text.Json;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Input;

internal static class InputNativeProbe
{
    // Runs the real Desktop worker with a deliberately nonexistent target; no foreground input is recorded.
    public static int Run(string executable, string nativeDirectory, string output)
    {
        var root = Directory.CreateTempSubdirectory("endfield-native-input-");
        try
        {
            var trace = Path.Combine(root.FullName, "probe.log"); File.WriteAllText(trace, "synthetic probe\n");
            InputRecordingOptions options = new(Path.Combine(root.FullName, "missing-game.exe"), root.FullName, Path.GetFullPath(nativeDirectory), trace);
            var controller = new InputRecordingController(Path.GetFullPath(executable));
            EvidenceObject observed;
            try
            {
                controller.StartAsync(options, elevate: false).GetAwaiter().GetResult(); var start = Stopwatch.GetTimestamp();
                do
                {
                    Thread.Sleep(20); observed = controller.Status;
                    if (observed.Get("status") is EvidenceText { Value: "error" }) throw new IOException(PythonSortedJson.Serialize(observed));
                    if (Stopwatch.GetElapsedTime(start).TotalSeconds > 15) throw new TimeoutException("Native worker did not publish waiting_game");
                } while (observed.Get("status") is not EvidenceText { Value: "waiting_game" });
                Thread.Sleep(300); observed = controller.Status; controller.StopAsync().GetAwaiter().GetResult();
                if (controller.Running || observed.Get("errors") is EvidenceArray { Items.Count: > 0 }) throw new IOException("Native input initialization reported a backend error");
            }
            finally { controller.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
            var archive = new InputArchive(InputLogWriter.Companion(trace)); archive.VerifyTrace(trace);
            var success = archive.InputCounts.Count == 0 && archive.Warnings.Count == 0 && observed.Get("capture_health") is EvidenceObject health
                && health.Get("message_thread_alive") is EvidenceBoolean { Value: true };
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
            File.WriteAllText(output, JsonSerializer.Serialize(new { passed = success, windows_message_backend = true, sdl_initialization = true,
                foreground_input_events = archive.InputCounts.Values.Sum(), trace_prefix_verified = true, status = JsonSerializer.Deserialize<JsonElement>(PythonSortedJson.Serialize(observed)),
                limitations = new[] { "未触发管理员授权", "未测试真实游戏前台输入", "未测试实物手柄操作" } }));
            Console.WriteLine("Native Desktop input worker probe: " + (success ? "passed" : "failed")); return success ? 0 : 1;
        }
        finally { root.Delete(true); }
    }
}
