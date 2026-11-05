using System.Text;
using System.Text.Json;
using System.Threading.Channels;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Input;
using EndfieldLogs.Runtime.Tracing;

internal static class InputEvidenceSpecs
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(15);
    private static readonly TimeZoneInfo Zone = TimeZoneInfo.CreateCustomTimeZone("reference", TimeSpan.FromHours(8), "reference", "reference");
    private static readonly long StartNs = new DateTimeOffset(2026, 10, 28, 0, 0, 0, TimeSpan.FromHours(8)).ToUnixTimeMilliseconds() * 1_000_000;
    private const string Trace = "[00:00:00.000] LOADOUT reason=squad\n[00:00:00.000] LOADOUT slot=0 char=chr_0001_test\n[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100\n[00:00:01.500] HP_V2 #2 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=20\n";
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static string Input(int ms, string phase, int seq) => JsonSerializer.Serialize(new { type = "input", seq, kind = "key", code = "K:49", device = "keyboard", phase,
        wall_ns = StartNs + ms * 1_000_000L, mono_ns = ms * 1_000_000L });
    private static string Sidecar() => JsonSerializer.Serialize(new { type = "session", schema_version = 1, wall_ns = StartNs }) + "\n" + Input(1200, "down", 1) + "\n" + Input(1300, "up", 2)
        + "\n" + JsonSerializer.Serialize(new { type = "end", wall_ns = StartNs + 1500000000 }) + "\n";
    private static void Wait(Task task) => task.WaitAsync(Timeout).GetAwaiter().GetResult();
    private static T Wait<T>(Task<T> task) => task.WaitAsync(Timeout).GetAwaiter().GetResult();
    private static IReadOnlyList<EvidenceObject> Actions(EvidenceObject value) => ((EvidenceArray)value.Get("actions")).Items.Cast<EvidenceObject>().ToArray();

    public static void Run(Action<bool, string> check)
    {
        var root = Directory.CreateTempSubdirectory("endfield-input-evidence-");
        try
        {
            var trace = Path.Combine(root.FullName, "trace_20261028.log"); var sidecar = Path.ChangeExtension(trace, ".input.jsonl");
            File.WriteAllText(trace, Trace, new UTF8Encoding(false)); File.WriteAllText(sidecar, Sidecar(), new UTF8Encoding(false));
            var record = new HistoryCatalog(Zone).Read(trace, true).Single();
            var snapshot = new HistoryAnalyzer(new ResourceFiles(root.FullName), Zone).Analyze(record); var battle = (EvidenceObject)snapshot.Get("battle");
            var saved = PythonSortedJson.Serialize(snapshot); InputEvidenceLoader loader = new(Zone);
            var evidence = loader.Load(new([sidecar], trace, battle, Obj("{}"))); var action = Actions(evidence).Single();
            check(action.Get("action") is EvidenceText { Value: "skill" } && action.Get("character_key") is EvidenceText { Value: "chr_0001_test" },
                "A real indexed history report binds selected input intentions through explicit trace LOADOUT slots");
            check(action.Get("start_ms") is EvidenceReal { Value: 100 } && action.Get("end_ms") is EvidenceReal { Value: 200 }
                && action.Get("duration_ms") is EvidenceReal { Value: 100 }, "Input alignment retains observed wall anchor and monotonic hold duration");
            check(PythonSortedJson.Serialize(snapshot) == saved, "Loading presentation input evidence leaves the canonical report and contributions unchanged");
            check(evidence.Get("raw") is EvidenceArray { Items.Count: 0 } && evidence.Get("input_counts") is EvidenceObject count && count.Get("key") is EvidenceInteger { Value: var countValue } && countValue == 2,
                "Raw filtering controls presentation while battle-local recording counts remain available");
            evidence = loader.Load(new([sidecar], trace, battle, Obj("""{"show_other":true}"""), ManualSlots: new Dictionary<int, string> { [0] = "chr_0002_test" }, Verify: false));
            check(Actions(evidence).Single().Get("character_key") is EvidenceText { Value: "chr_0002_test" } && evidence.Get("raw") is EvidenceArray { Items.Count: 2 },
                "Manual slot ownership and raw visibility override display evidence independently of battle results");
            File.WriteAllText(sidecar, Sidecar().Replace("K:49", "K:69", StringComparison.Ordinal));
            check(Actions(loader.Load(new([sidecar], trace, battle, Obj("{}")))).Single().Get("action") is EvidenceText { Value: "combo" },
                "Input archive cache invalidates on source signature changes");
            loader.ClearCache();
            var midnight = new DateTimeOffset(2026, 10, 29, 0, 0, 0, TimeSpan.FromHours(8)).ToUnixTimeMilliseconds();
            check(loader.BattleStartWallMs(Obj("""{"battle_start_at":"2026-10-29T00:00:00","timeline_zero_source":"official_timer_start","timer_evidence":{"start":{"observedMs":86399900}}}""")) == midnight - 100,
                "Second-precision legacy start recovers the nearest observed timer across midnight");
            check(loader.BattleStartWallMs(Obj("""{"battle_start_at":"2026-10-29T00:00:00.123+08:00"}""")) == midnight + 123,
                "Explicit millisecond ISO anchors keep their timezone and precision");
            var fragment = Path.Combine(root.FullName, "trace_20261028.part-0001.input.jsonl"); File.Copy(sidecar, fragment);
            check(InputEvidenceLoader.Discover(trace).SequenceEqual([sidecar, fragment]), "Sidecar discovery retains base and ordered fragment files");
            var structured = Path.Combine(root.FullName, "trace_input_first.jsonl");
            var continuation = Path.Combine(root.FullName, "trace_input_next.jsonl");
            TraceHeader header = new("input-loadout-volumes", 1, null, "csharp", "test", "reference", 480, new Dictionary<string, string>());
            using (TraceJsonlWriter writer = new(File.Create(structured), header))
            {
                writer.Write(new(1, StartNs / 1_000_000, "loadout_group", Obj("""{"reason":"squad"}"""), Obj("{}")));
                writer.Write(new(2, StartNs / 1_000_000, "loadout_slot", Obj("""{"slot":0,"template":"chr_0001_test"}"""), Obj("{}")));
            }
            using (TraceJsonlWriter writer = new(File.Create(continuation), header with { Volume = 2,
                PreviousVolume = new(1, Path.GetFileName(structured)) }))
                writer.Write(new(3, StartNs / 1_000_000 + 500, "loadout_slot", Obj("""{"slot":1,"template":"chr_0002_test"}"""), Obj("{}")));
            var loadouts = loader.LoadoutHistory(continuation, StartNs / 1_000_000);
            check(loadouts.Count == 3 && loadouts[0].Slot is null && loadouts[1] is { Slot: 0, Character: "chr_0001_test" }
                && loadouts[2] is { Slot: 1, Character: "chr_0002_test" } && loadouts[2].WallMs == StartNs / 1_000_000 + 500,
                "JSONL input ownership reads structured loadout events across volumes at their exact Unix timestamps without exporting old text");
            var binding = InputBindings.Read(Obj("""{"path":"trace_20261028.input.jsonl","visible":1,"offset_ms":true,"start_override":"10","manual_slots":{"0":"chr_0001_test","4":"invalid"}}"""), trace);
            check(binding.SourcePath == sidecar && !binding.Visible && binding.OffsetMs == 0 && binding.StartOverride is null && binding.ManualSlots.Count == 1,
                "Persisted bindings require explicit visibility booleans, finite numeric offsets and valid manual slots");
            using CancellationTokenSource cancel = new(); cancel.Cancel(); var failed = false;
            try { loader.Load(new([sidecar], trace, battle, Obj("{}")), cancel.Token); } catch (OperationCanceledException) { failed = true; }
            check(failed, "Cancelled evidence requests stop before archive reads or projection");
        }
        finally { root.Delete(recursive: true); }
    }
    public static void Controller(Action<bool, string> check)
    {
        var root = Directory.CreateTempSubdirectory("endfield-input-controller-");
        try
        {
            var trace = Path.Combine(root.FullName, "trace_20261028.log"); var sidecar = Path.ChangeExtension(trace, ".input.jsonl");
            File.WriteAllText(trace, Trace); File.WriteAllText(sidecar, Sidecar()); var record = new HistoryCatalog(Zone).Read(trace, true).Single();
            SettingsContext context = new(root.FullName); SettingsStore store = new(new() { Service = ServiceSettings.Default(context) }, new(context));
            var requests = Channel.CreateUnbounded<(InputEvidenceRequest Request, TaskCompletionSource<EvidenceObject> Completion)>();
            Task<EvidenceObject> Load(InputEvidenceRequest request, CancellationToken token)
            { TaskCompletionSource<EvidenceObject> result = new(TaskCreationOptions.RunContinuationsAsynchronously); requests.Writer.TryWrite((request, result)); return result.Task; }
            (InputEvidenceRequest Request, TaskCompletionSource<EvidenceObject> Completion) Next() => Wait(requests.Reader.ReadAsync().AsTask());
            EvidenceObject Result(int id) => Obj($$"""{"actions":[{"id":{{id}}}],"raw":[],"warnings":[]}""");
            using InputEvidenceController controller = new(Obj("{}"), store, Load);
            var work = controller.SetRecordAsync(record); var first = Next();
            check(first.Request.Paths.SequenceEqual([sidecar]) && first.Request.Verify && controller.State.Pending && !controller.State.Visible,
                "Record selection discovers its sidecar and loads verified evidence while leaving visibility independently disabled");
            first.Completion.SetResult(Result(1)); Wait(work);
            check(controller.State.Pending && Actions(controller.State.Evidence).Count == 0, "Input workers cannot publish outside the owning UI thread");
            controller.Drain(); var original = controller.State.Evidence; ((Dictionary<string, EvidenceValue>)Actions(original).Single().Fields)["id"] = new EvidenceInteger(99);
            check(Actions(controller.State.Evidence).Single().Get("id") is EvidenceInteger { Value: var identifier } && identifier == 1,
                "Input view state exposes independent evidence and settings copies");
            var older = controller.ReloadAsync(); var stale = Next(); work = controller.BindAsync(sidecar); var next = Next();
            check(!next.Request.Verify && !controller.State.Visible && next.Request.OffsetMs == 0, "Manual binding disables automatic trace association checks without changing the display toggle");
            controller.SetVisible(true); next.Completion.SetResult(Result(2)); Wait(work); controller.Drain(); stale.Completion.SetResult(Result(3)); Wait(older); controller.Drain();
            check(controller.State.Visible && Actions(controller.State.Evidence).Single().Get("id") is EvidenceInteger { Value: var current } && current == 2,
                "Late evidence for a previous binding cannot replace the latest selected source");
            work = controller.SetAlignmentAsync(125, null, new Dictionary<int, string> { [0] = "chr_0002_test" }); next = Next();
            check(next.Request.OffsetMs == 125 && next.Request.ManualSlots![0] == "chr_0002_test" && controller.State.Visible,
                "Manual alignment and slot mapping reach the worker without changing visibility");
            next.Completion.SetResult(Result(4)); Wait(work); controller.Drain();
            var persisted = InputBindings.Read(store.Current.InputLogBindings.Get(record.Key), trace);
            check(persisted.Visible && persisted.Manual && persisted.OffsetMs == 125 && persisted.ManualSlots[0] == "chr_0002_test",
                "Per-battle source, visibility and manual alignment persist through the shared settings store");
            work = controller.ReloadAsync(); next = Next(); next.Completion.SetException(new InvalidDataException("synthetic source error")); Wait(work); controller.Drain();
            check(!controller.State.Pending && controller.State.Error == "synthetic source error" && Actions(controller.State.Evidence).Count == 0,
                "Input loading failure clears obsolete evidence and releases pending UI state");
            work = controller.ReloadAsync(); stale = Next(); Wait(controller.UnbindAsync()); stale.Completion.SetResult(Result(5)); Wait(work); controller.Drain();
            check(controller.State.Paths.Count == 0 && !controller.State.Pending && Actions(controller.State.Evidence).Count == 0,
                "Unbinding cancels outstanding interpretation and retains an explicit empty binding");
            work = controller.BindAsync(sidecar); next = Next(); next.Completion.SetResult(Result(6)); Wait(work); controller.Drain();
            var moved = HistoryFiles.Rename(trace, "测试"); store.Update(settings => HistoryFiles.Relocate(settings, trace, moved));
            work = controller.RelocateAsync(trace, moved); next = Next();
            check(next.Request.TracePath == moved && next.Request.Paths.Single() == Path.ChangeExtension(moved, ".input.jsonl"),
                "History rename reloads input evidence from the relocated raw source and companion binding");
            controller.Dispose(); next.Completion.SetResult(Result(7)); Wait(work);
            check(!controller.Drain() && !controller.State.Pending && Actions(controller.State.Evidence).Count == 0,
                "Closing rejects late input results and releases displayed evidence without waiting on a worker");

            store.Update(settings => settings with { InputLogBindings = Obj("{}") });
            using InputEvidenceController automatic = new(Obj("{}"), store, Load);
            work = automatic.SetRecordAsync(record with { FilePath = moved }); next = Next(); next.Completion.SetResult(Result(8)); Wait(work); automatic.Drain();
            var automaticDestination = HistoryFiles.Rename(moved, "自动发现");
            store.Update(settings => HistoryFiles.Relocate(settings, moved, automaticDestination));
            work = automatic.RelocateAsync(moved, automaticDestination); next = Next();
            check(next.Request.Paths.SequenceEqual([Path.ChangeExtension(automaticDestination, ".input.jsonl")]) && next.Request.Verify,
                "Renaming a record with an automatically discovered sidecar retains automatic discovery and trace verification");
            next.Completion.SetResult(Result(9)); Wait(work); automatic.Drain();
        }
        finally { root.Delete(recursive: true); }
    }
}
