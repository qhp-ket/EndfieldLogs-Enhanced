using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Capture;
using EndfieldLogs.Runtime.Tracing;

internal static class RecordingStateSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var folder = Directory.CreateTempSubdirectory("endfield-recording-state-");
        try
        {
            var fixture = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../Specs/Fixtures/trace-bridge.json"));
            var sample = JsonNode.Parse(File.ReadAllBytes(fixture))!.AsArray().Single(row => row!["name"]!.GetValue<string>() == "0328-mixed-event-order")!;
            var steps = JsonNode.Parse(sample["config_json"]!.GetValue<string>())!["steps"]!.AsArray();
            var stamp = new DateTimeOffset(2026, 11, 5, 0, 0, 0, TimeSpan.Zero).ToUnixTimeMilliseconds();
            TraceHeader header = new("live", 1, null, "csharp", "test", "UTC", 0, new Dictionary<string, string>());
            List<TraceEvent> live = [];
            CaptureArtifacts? destination = null;
            using var producer = TraceRecording.CreateStructured(batch => { live.AddRange(batch); destination?.WriteTraceEvents(batch); }, header);
            using var artifacts = new CaptureArtifacts(producer, "missing.exe", folder.FullName);
            destination = artifacts;
            void Emit(EvidenceObject row, long time)
            {
                var value = new BattleLogEvent("synthetic", stamp + time, TraceData.Text(row.Get("type")),
                    row.Fields.Where(pair => pair.Key is not ("type" or "timestamp_ms" or "session_id"))
                        .ToDictionary(pair => pair.Key, pair => (object?)pair.Value));
                producer.Handle(value); artifacts.WriteEvent(value);
            }
            foreach (var step in steps.Take(2)) Emit((EvidenceObject)EvidenceJson.Parse(step!["event_json"]!.GetValue<string>()), 0);
            var hit = JsonNode.Parse(steps[6]!["event_json"]!.GetValue<string>())!;
            hit["action"]!["damage_action"]!["details"]![0]!["value"] = -123.5;
            hit["action"]!["damage_action"]!["details"]![0]!["cur_hp"] = 10000;
            EvidenceObject Hit() => (EvidenceObject)EvidenceJson.Parse(hit.ToJsonString());
            Emit(Hit(), 1000);
            check(!artifacts.Recording && artifacts.EventFilePath is null && !Directory.EnumerateFiles(folder.FullName, "*", SearchOption.AllDirectories).Any(),
                "Capture can analyze damage before recording without creating session or trace files");
            var first = artifacts.SetRecording(true)!;
            var original = artifacts.SetRecording(true);
            check(original == first, "Repeated start requests keep the current file group");
            Emit(Hit(), 2000);
            Emit(TraceData.Make(("type", "BattleOpAddBuff"), ("buff_inst_id", 999), ("str_id", "buff_pending"), ("src_inst_id", 11), ("target_inst_id", 333)), 2001);
            artifacts.SetRecording(false);
            var firstChain = TraceVolumes.Resolve(first.TracePath);
            var events = TraceVolumes.ReadEvents(firstChain).ToArray();
            check(!artifacts.Recording && !artifacts.IsWriting(first.TracePath) && !artifacts.IsWriting(first.SessionPath)
                && artifacts.SetRecording(false) is null, "Stop closes both files and is idempotent");
            check(events.Count(row => row.Type == "damage") == 1 && events.Any(row => row.Type == "buff_start"),
                "Stopping flushes pending BUFF evidence and excludes hits observed before recording");
            var saved = File.ReadAllBytes(first.TracePath); var rawSaved = File.ReadAllBytes(first.SessionPath);
            Emit(Hit(), 3000);
            // A business call may carry both damage and BUFF creation. Only its BUFF context may seed a later recording.
            hit["action"]!["create_buff_action"] = JsonNode.Parse("""{"details":[{"buff_inst_id":1000,"str_id":"buff_seed","src_inst_id":11,"target_inst_id":333}]}""");
            Emit(Hit(), 3001);
            check(saved.SequenceEqual(File.ReadAllBytes(first.TracePath)) && rawSaved.SequenceEqual(File.ReadAllBytes(first.SessionPath)),
                "Capture continues while stopped without modifying the closed file group");
            var next = artifacts.SetRecording(true)!;
            hit["action"]!.AsObject().Remove("create_buff_action");
            Emit(Hit(), 4000);
            artifacts.SetRecording(false);
            var nextChain = TraceVolumes.Resolve(next.TracePath);
            var nextEvents = TraceVolumes.ReadEvents(nextChain).ToArray();
            check(first.TracePath != next.TracePath && first.SessionPath != next.SessionPath && nextChain.IsComplete
                && nextChain.Volumes.Count == 1 && nextChain.Volumes[0].Header.Volume == 1
                && firstChain.Volumes[0].Header.RecordingId != nextChain.Volumes[0].Header.RecordingId,
                "Every restart creates an independent first-volume trace and session with new recording identity");
            check(nextEvents.Count(row => row.Type == "damage") == 1 && live.Count(row => row.Type == "damage") == 4,
                "New recording contains only its new hit while the unchanged live producer retains all four hits");
            check(nextEvents.Select(row => row.Sequence).SequenceEqual(Enumerable.Range(1, nextEvents.Length).Select(value => (long)value)),
                "File event sequences restart continuously even when live evidence has advanced");
            foreach (var path in new[] { first.TracePath, first.SessionPath, next.TracePath, next.SessionPath })
            {
                using var exclusive = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
                check(exclusive.Length > 0, "Stopped files release their handles before returning");
            }
        }
        finally { Directory.Delete(folder.FullName, true); }
    }
}
