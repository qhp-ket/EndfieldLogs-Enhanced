using System.Security.Cryptography;
using System.Text;
using System.Threading.Channels;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Realtime;

internal static class HistorySpecs
{
    private const string Hit = "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100";
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(15);
    private static void Wait(Task task) => task.WaitAsync(Timeout).GetAwaiter().GetResult();
    private static T Wait<T>(Task<T> task) => task.WaitAsync(Timeout).GetAwaiter().GetResult();
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Snapshot(int value) => Obj($$"""{"battle":{"total_damage":{{value}},"duration_ms":2000,"source_file_name":"trace_20261028.log"},"participants":[{"character_key":"chr_0001_test","character_name":"测试角色","total_damage":{{value}},"hit_count":1,"max_hit":{{value}},"crit_hits":1}]}""");
    private static EvidenceObject Battle(EvidenceObject snapshot) => (EvidenceObject)snapshot.Get("battle");
    private static int Total(EvidenceObject? snapshot) => snapshot?.Get("battle") is EvidenceObject battle
        ? battle.Get("total_damage") switch { EvidenceInteger number => (int)number.Value, EvidenceReal number => (int)number.Value, _ => -1 } : -1;

    public static void Storage(Action<bool, string> check)
    {
        var folder = Directory.CreateTempSubdirectory("endfield-history-storage-"); var root = folder.FullName;
        try
        {
            var path = Path.Combine(root, "trace_20261028.log"); var cache = Path.Combine(root, "index");
            var longLine = new string('中', 16 * 1024 - 1);
            using (StringReader reader = new(longLine + "\r\nx\ry\u2028z\u0085\n尾\r"))
                check(PythonTextLines.ReadKeepEnds(reader).SequenceEqual([longLine + "\r\n", "x\r", "y\u2028", "z\u0085", "\n", "尾\r"]),
                    "Streaming trace lines preserve CRLF across read blocks, Unicode separators and terminal CR");
            var large = "[00:00:00.000] SQUAD note=" + string.Concat(Enumerable.Repeat("角色😀", 12000)) + "\r\n"
                + Hit + "\u2028[00:00:01.200] NOTE completed=1\u0085";
            File.WriteAllText(path, large, new UTF8Encoding(true));
            var streamed = new HistoryCatalog(TimeZoneInfo.Utc).Read(path, true).Single();
            check(streamed.SourceByteStart == 3 && streamed.SourceByteEnd == new FileInfo(path).Length
                && streamed.SourceStartLine == 0 && streamed.SourceEndLine == 3,
                "Production history indexing preserves BOM and byte ranges across long multilingual lines and Unicode endings");
            File.WriteAllBytes(path, [0xef, 0xbb, 0xbf, 0xff]); var invalidUtf8 = false;
            try { new HistoryCatalog(TimeZoneInfo.Utc).Read(path, true); } catch (DecoderFallbackException) { invalidUtf8 = true; }
            check(invalidUtf8, "Streaming history indexing rejects invalid UTF-8 instead of changing evidence bytes");
            File.WriteAllText(path, "[00:00:00.000] SQUAD members=[测试]\r\n" + Hit + "\r\n", new UTF8Encoding(true));
            var raw = File.ReadAllBytes(path); HistoryIndex index = new(cache, new(TimeZoneInfo.Utc));
            var row = index.Records(path, trace: true).Single();
            check(!row.AnalysisLoaded && row.TotalDamage == 0 && row.Players.Count == 0, "Trace listing stores only range metadata and never computes a full report");
            check(row.SourceByteStart == 3 && row.SourceByteEnd == raw.Length && row.SourceStartLine == 0 && row.SourceEndLine == 2,
                "UTF-8 BOM, multibyte context and CRLF retain exact raw byte boundaries");
            var cachePath = Directory.GetFiles(cache).Single();
            check(!File.ReadAllText(cachePath).Contains("snapshot", StringComparison.OrdinalIgnoreCase) && File.ReadAllBytes(path).SequenceEqual(raw),
                "Disposable history index contains no report snapshots and leaves source bytes unchanged");
            check(index.Records(path, true).Single() == row, "Persisted trace metadata round trips without changing row identity");
            File.WriteAllText(cachePath, "{broken");
            check(index.Records(path, true).Single().Key == row.Key, "A corrupt history index is rebuilt from the immutable source");
            File.AppendAllText(path, Hit.Replace("00:00:01.100", "00:01:01.100", StringComparison.Ordinal) + "\n");
            var appended = index.Records(path, true);
            check(appended.Count == 2 && appended[0].Key == row.Key && appended[0].SourceSignature != row.SourceSignature,
                "Appending a battle invalidates the disposable cache and preserves previous stable record keys");
            var occupied = Path.Combine(root, "read-only-cache"); File.WriteAllText(occupied, "file");
            check(new HistoryIndex(occupied).Records(path, true).Count == 2, "History remains available when cache storage cannot be created");
            SettingsContext context = new(root, Path.Combine(root, "cwd"));
            var fallback = Path.Combine(root, "_internal", "logs"); Directory.CreateDirectory(fallback); File.WriteAllText(Path.Combine(fallback, "session_1.ndjson"), "x");
            var preferred = Path.Combine(root, "preferred");
            check(HistoryIndex.ResolveLogDirectory(preferred, context) == fallback, "Historical installations retain the internal logs directory fallback");
            Directory.CreateDirectory(preferred); File.WriteAllText(Path.Combine(preferred, "session_1.ndjson"), "x");
            check(HistoryIndex.ResolveLogDirectory(preferred, context) == preferred, "A configured directory containing events takes priority over legacy fallbacks");

            File.WriteAllText(path, Hit + "\n"); row = index.Records(path, true).Single();
            var companion = Path.ChangeExtension(path, ".input.jsonl"); File.WriteAllText(companion, "input bytes\r\n");
            var fragment = Path.Combine(root, "trace_20261028.part-0001.input.jsonl"); File.WriteAllText(fragment, "fragment bytes");
            TraceExportService.Export(path, Path.Combine(root, "export.log"));
            File.WriteAllText(path + ".integrity.json", "proof-one"); File.WriteAllText(Path.ChangeExtension(path, ".integrity.json"), "proof-two");
            File.WriteAllText(path + ".status.json", "status");
            string[] sources = [path, companion, fragment, path + ".integrity.json", Path.ChangeExtension(path, ".integrity.json"), path + ".status.json"];
            var hashes = sources.Select(file => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(file)))).ToArray();
            var stamp = File.GetLastWriteTimeUtc(path); var destination = HistoryFiles.RenamedPath(path, "测试新名称");
            File.WriteAllText(destination + ".integrity.json", "orphan"); var refused = false;
            try { HistoryFiles.Rename(path, "测试新名称"); } catch (IOException) { refused = true; }
            check(refused && sources.All(File.Exists), "Orphan destination proofs reject a rename before any raw or companion file moves");
            File.Delete(destination + ".integrity.json"); refused = false;
            try { HistoryFiles.Rename(path, "测试新名称", file => file == fragment); } catch (InvalidOperationException) { refused = true; }
            check(refused && sources.All(File.Exists), "An active input fragment prevents renaming its linked raw trace");
            if (OperatingSystem.IsWindows())
            {
                using (var held = new FileStream(companion, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    refused = false; try { HistoryFiles.Rename(path, "测试新名称"); } catch (IOException) { refused = true; }
                    check(refused && sources.All(File.Exists) && !File.Exists(destination), "Windows companion sharing failure rolls the already moved raw log back");
                }
            }
            var moved = HistoryFiles.Rename(path, "测试新名称"); index.Relocate(path, moved);
            var destinations = new[] { moved, Path.ChangeExtension(moved, ".input.jsonl"), Path.Combine(root, "trace_20261028 -- 测试新名称.part-0001.input.jsonl"),
                moved + ".integrity.json", Path.ChangeExtension(moved, ".integrity.json"), moved + ".status.json" };
            check(destinations.Select(file => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(file)))).SequenceEqual(hashes)
                && sources.All(file => !File.Exists(file)) && File.GetLastWriteTimeUtc(moved) == stamp, "Raw log, both proofs, status, input and fragments move with exact bytes and source date intact");
            var relocated = index.Records(moved, true).Single();
            check(relocated.Key == HistoryFiles.RelocateKey(row.Key, path, moved) && relocated.Label.Contains("测试新名称", StringComparison.Ordinal),
                "Index relocation updates source metadata and record keys without canonical analysis");
            var exported = Path.Combine(root, "renamed-export.log"); File.Delete(moved + ".integrity.json"); File.Delete(Path.ChangeExtension(moved, ".integrity.json"));
            TraceExportService.Export(moved, exported);
            check(TraceExportService.LoadIntegrity(exported).Verified, "A renamed raw source retains uploader-compatible export capability");
        }
        finally { folder.Delete(recursive: true); }
    }

    public static void Analysis(Action<bool, string> check)
    {
        var folder = Directory.CreateTempSubdirectory("endfield-history-analysis-");
        try
        {
            var root = folder.FullName; HistoryCatalog catalog = new(TimeZoneInfo.Utc); HistoryAnalyzer analyzer = new(new ResourceFiles(root), TimeZoneInfo.Utc);
            var path = Path.Combine(root, "trace_20261028.log");
            File.WriteAllText(path, Hit + "\n" + Hit.Replace("00:00:01.100", "00:01:01.100", StringComparison.Ordinal).Replace("hit=100", "hit=60", StringComparison.Ordinal) + "\n", new UTF8Encoding(true));
            var rows = catalog.Read(path, true); var hash = SHA256.HashData(File.ReadAllBytes(path));
            var snapshot = analyzer.Analyze(rows[1]);
            check(Total(snapshot) == 60 && Battle(snapshot).Get("battle_start_at") is EvidenceText date && date.Value.StartsWith("2026-10-28", StringComparison.Ordinal),
                "Selected trace byte range reaches the production canonical calculation with the original reference date");
            check(snapshot.Get("timeline_events") is EvidenceArray { Items.Count: 1 } && snapshot.Get("snapshot_quality") is EvidenceObject,
                "On-demand history preserves timeline evidence and quality in addition to damage totals");
            check(SHA256.HashData(File.ReadAllBytes(path)).SequenceEqual(hash), "History analysis leaves original signed trace bytes unchanged");
            File.AppendAllText(path, "tail"); var failed = false;
            try { analyzer.Analyze(rows[1]); } catch (InvalidDataException) { failed = true; }
            check(failed, "A changed trace source cannot be analyzed with stale byte boundaries");
            var unicode = string.Concat(Enumerable.Repeat("中🙂", 20000));
            File.WriteAllText(path, Hit + " note=" + unicode + "\r\n" + Hit.Replace("00:00:01.100", "00:01:01.100", StringComparison.Ordinal).Replace("hit=100", "hit=60", StringComparison.Ordinal) + "\r\n", new UTF8Encoding(true));
            var wideRows = catalog.Read(path, true);
            check(wideRows[0].SourceByteEnd - wideRows[0].SourceByteStart > 64 * 1024
                && Total(analyzer.Analyze(wideRows[0])) == 100 && Total(analyzer.Analyze(wideRows[1])) == 60,
                "Bounded UTF-8 decoding keeps multibyte characters across chunks and excludes the next battle");
            var eventPath = Path.Combine(root, "session_synthetic.ndjson");
            const long start = 1793188800000;
            string Damage(long stamp, int damage) => $$$$"""{"type":"BattleOpTriggerAction","timestamp_ms":{{{{stamp}}}},"owner_id":11,"inst_id":77,"action":{"action_type":"BattleActionDamage","damage_action":{"attacker_id":11,"details":[{"target_id":33,"value":-{{{{damage}}}},"cur_hp":{{{{10000 - damage}}}}}]}}}""";
            string[] events = [
                $$"""{"type":"SC_SELF_SCENE_INFO","timestamp_ms":{{start}},"char_list":[{"id":101,"battle_inst_id":11,"templateid":"chr_0001_test"}]}""",
                $$"""{"type":"SC_OBJECT_ENTER_VIEW","timestamp_ms":{{start}},"objects":[{"battle_inst_id":33,"templateid":"eny_0001_test"}]}""",
                $$"""{"type":"BattleOpSkillAttach","timestamp_ms":{{start}},"skill_inst_id":77,"src_inst_id":11,"template_str_id":"chr_0001_test_normal_skill"}""",
                $$"""{"type":"BattleOpModifyBattleState","timestamp_ms":{{start + 100}},"is_in_battle":true,"client_tick_tms":100}""",
                Damage(start + 200, 1000),
                $$"""{"type":"SC_GAME_MECHANICS_SYNC_CHALLENGE_START","timestamp_ms":{{start + 1000}},"game_id":"challenge","challenge_start_ts":123}""",
                $$"""{"type":"BattleOpModifyBattleState","timestamp_ms":{{start + 1100}},"is_in_battle":true,"client_tick_tms":1100}""",
                Damage(start + 1200, 80),
                $$"""{"type":"SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE","timestamp_ms":{{start + 1500}},"game_id":"challenge","is_pass":true,"pass_time":500}""",
            ];
            File.WriteAllText(eventPath, string.Join('\n', events) + "\n", new UTF8Encoding(false));
            var record = catalog.Read(eventPath, false).Last(); var result = analyzer.Analyze(record); var battle = Battle(result);
            check(Total(result) == 80 && battle.Get("official_timer_start_seen") is EvidenceBoolean { Value: true }
                && battle.Get("duration_ms") is EvidenceInteger { Value: var duration } && duration == 500,
                "NDJSON range replay retains an earlier active official start but excludes previous-battle hits");
            check(result.Get("participants") is EvidenceArray participants && participants.Items.OfType<EvidenceObject>().Any(row => row.Get("character_key") is EvidenceText { Value: "chr_0001_test" }),
                "NDJSON replay preserves prefix entity and skill bindings for the selected combat record");
            foreach (var newline in new[] { "\r\n", "\r" })
            {
                File.WriteAllText(eventPath, string.Join(newline, events) + newline, new UTF8Encoding(false));
                check(Total(analyzer.Analyze(catalog.Read(eventPath, false).Last())) == 80, "Universal NDJSON file newlines preserve indexed replay boundaries");
            }
            File.WriteAllText(eventPath, string.Join('\n', events) + "\n", new UTF8Encoding(false));
            var selectedRecords = catalog.Read(eventPath, false);
            File.AppendAllText(eventPath, Damage(start + 2000, 99999) + "\n");
            foreach (var selectedRecord in selectedRecords)
            {
                var exported = Path.Combine(root, $"selected-{selectedRecord.RecordIndex}.log");
                TraceExportService.ExportBattle(selectedRecord, exported);
                var selected = catalog.Read(exported, true);
                check(selected.Count == 1 && TraceExportService.LoadIntegrity(exported).Verified
                    && Total(analyzer.Analyze(selected.Single())) == Total(analyzer.Analyze(selectedRecord)),
                    "Selected session export keeps prefix bindings and timer, excluding earlier battles and hits after official completion");
            }
            var growingPath = Path.Combine(root, "session_growing.ndjson");
            File.WriteAllText(growingPath, string.Join('\n', events[..^1]) + "\n", new UTF8Encoding(false));
            var growing = catalog.Read(growingPath, false).Last();
            File.AppendAllText(growingPath, Damage(start + 1300, 30) + "\n" + events[^1] + "\n");
            var growingExport = Path.Combine(root, "growing-export.log");
            TraceExportService.ExportBattle(growing, growingExport);
            var grown = catalog.Read(growingExport, true).Single();
            var grownSnapshot = analyzer.Analyze(grown);
            check(Total(grownSnapshot) == 110 && EvidenceJson.PythonEquals(Battle(grownSnapshot).Get("duration_ms"), new EvidenceInteger(500)),
                "Export refresh includes new same-battle hits and the official completion written after the row was selected: "
                    + Total(grownSnapshot) + " / " + PythonSortedJson.Serialize(Battle(grownSnapshot).Get("duration_ms")));
            File.WriteAllText(eventPath, File.ReadAllText(eventPath).Replace("\"is_in_battle\":true", "\"is_in_battle\":false", StringComparison.Ordinal));
            failed = false;
            try { TraceExportService.ExportBattle(selectedRecords.Last(), Path.Combine(root, "tampered.log")); }
            catch (InvalidDataException) { failed = true; }
            check(failed && !File.Exists(Path.Combine(root, "tampered.log")), "Changed selected session evidence cannot be exported or resealed");
            using var prefix = new LiveBattleSession(() => throw new InvalidOperationException("no calculation"));
            prefix.FeedLine("[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge"); prefix.FeedLine(Hit);
            check(prefix.HistoryContext().Count == 1 && prefix.HistoryContext()[0].Contains("OFFICIAL_TIMER_START", StringComparison.Ordinal),
                "Extracting active prefix context removes old hit evidence without invoking the calculator");
            var updated = HistoryAnalyzer.ApplySummary(record, Snapshot(80));
            check(updated.AnalysisLoaded && updated.TotalDamage == 80 && updated.Players.Single().CritRate == 100 && record.TotalDamage == 80,
                "Completed summary updates have independent player statistics and retain immutable source row metadata");
            using CancellationTokenSource cancel = new(); cancel.Cancel(); failed = false;
            try { analyzer.Analyze(record, cancel.Token); } catch (OperationCanceledException) { failed = true; }
            check(failed, "Cancelled selection stops before resource loading or canonical history calculation");
        }
        finally { folder.Delete(recursive: true); }
    }

    public static void Controller(Action<bool, string> check)
    {
        var folder = Directory.CreateTempSubdirectory("endfield-history-controller-");
        try
        {
            var root = folder.FullName; SettingsContext context = new(root); SettingsCodec codec = new(context);
            SettingsStore settings = new(new() { Service = ServiceSettings.Default(context) }, codec);
            HistoryIndex index = new(Path.Combine(root, "index"), new(TimeZoneInfo.Utc));
            var path = Path.Combine(root, "trace_20261028.log");
            File.WriteAllText(path, Hit + "\n" + Hit.Replace("00:00:01.100", "00:01:01.100", StringComparison.Ordinal) + "\n");
            var requests = Channel.CreateUnbounded<(HistoryRecord Record, TaskCompletionSource<EvidenceObject> Completion)>();
            Task<EvidenceObject> Analyze(HistoryRecord row, CancellationToken token)
            { TaskCompletionSource<EvidenceObject> completion = new(TaskCreationOptions.RunContinuationsAsynchronously); requests.Writer.TryWrite((row, completion)); return completion.Task; }
            (HistoryRecord Record, TaskCompletionSource<EvidenceObject> Completion) Next() => Wait(requests.Reader.ReadAsync().AsTask());
            using HistoryController controller = new(settings, index, Analyze);
            Wait(controller.ImportFilesAsync([path]));
            check(controller.ImportPending && controller.Records.Count == 0, "Workers cannot mutate history rows or settings before owner-thread drain");
            controller.Drain(); var keys = controller.Records.OrderBy(row => row.RecordIndex).Select(row => row.Key).ToArray();
            check(keys.Length == 2 && settings.Current.ImportedTraceFiles.SequenceEqual([path]) && !controller.Busy,
                "Import commits lightweight records and persistent source references on the owner thread");
            controller.Select(keys, keys[^1]); var work = controller.LoadAsync(keys, openDetails: true);
            var first = Next(); var earlier = Snapshot(10); first.Completion.SetResult(earlier); var last = Next(); var owned = Snapshot(20);
            var ownedFields = (Dictionary<string, EvidenceValue>)owned.Fields;
            ownedFields["timeline_events"] = EvidenceJson.Parse("""[{"value":20}]""");
            ownedFields["snapshot_quality"] = EvidenceJson.Parse("""{"status":"provisional","reasons":[{"code":"test"}]}""");
            ownedFields["rdps_preflight"] = EvidenceJson.Parse("""{"ok":false,"hits":[{"value":20}]}""");
            last.Completion.SetResult(owned); Wait(work);
            ((Dictionary<string, EvidenceValue>)Battle(earlier).Fields)["total_damage"] = new EvidenceInteger(-10);
            var notifications = controller.Drain();
            check(Total(controller.ReadSnapshot()) == 20 && controller.DisplayedKey == keys[^1] && notifications.Single().OpenDetails,
                "A batch publishes only its final selected report and retains the explicit details-open request");
            check(controller.Records.All(row => row.AnalysisLoaded) && controller.CachedSnapshot(first.Record) is null
                && controller.Records.Single(row => row.Key == first.Record.Key).TotalDamage == 10,
                "Batch rows retain independent summaries while the controller caches only the final full report");
            ((Dictionary<string, EvidenceValue>)Battle(owned).Fields)["total_damage"] = new EvidenceInteger(-1);
            var detached = controller.ReadSnapshot()!; ((Dictionary<string, EvidenceValue>)Battle(detached).Fields)["total_damage"] = new EvidenceInteger(-2);
            check(Total(controller.ReadSnapshot()) == 20, "Worker and UI snapshot mutation cannot change the owned history cache");
            var sharedView = controller.ReadOnlySnapshot()!;
            check(ReferenceEquals(sharedView, controller.ReadOnlySnapshot()) && Total(sharedView) == 20
                && ((IDictionary<string, EvidenceValue>)sharedView.Fields).IsReadOnly
                && ((IDictionary<string, EvidenceValue>)Battle(sharedView).Fields).IsReadOnly
                && ((IList<EvidenceValue>)((EvidenceArray)sharedView.Get("timeline_events")).Items).IsReadOnly,
                "Details share recursively read-only history data without exposing the cache through editable snapshots");
            var compact = controller.ReadSummarySnapshot()!;
            check(Total(compact) == 20 && compact.Get("timeline_events") is EvidenceNull
                && EvidenceJson.PythonEquals(compact.Get("participants"), controller.ReadSnapshot()!.Get("participants"))
                && EvidenceJson.PythonEquals(compact.Get("snapshot_quality"), controller.ReadSnapshot()!.Get("snapshot_quality"))
                && ((EvidenceObject)compact.Get("rdps_preflight")).Fields.Keys.SequenceEqual(["ok"]),
                "Home projection retains totals, participants and full quality while excluding detailed timeline/preflight evidence");
            ((Dictionary<string, EvidenceValue>)Battle(compact).Fields)["total_damage"] = new EvidenceInteger(-3);
            var reason = (EvidenceObject)((EvidenceArray)((EvidenceObject)compact.Get("snapshot_quality")).Get("reasons")).Items[0];
            ((Dictionary<string, EvidenceValue>)reason.Fields)["code"] = new EvidenceText("changed");
            check(Total(controller.ReadSummarySnapshot()) == 20
                && EvidenceJson.PythonEquals(controller.ReadSummarySnapshot()!.Get("snapshot_quality"), owned.Get("snapshot_quality"))
                && controller.ReadSnapshot()!.Get("timeline_events") is EvidenceArray { Items.Count: 1 },
                "Summary mutations cannot alter cached totals, nested quality evidence or complete details");
            work = controller.LoadAsync([keys[0]]); var stale = Next(); controller.Select([keys[^1]], keys[^1]); stale.Completion.SetResult(Snapshot(99)); Wait(work); controller.Drain();
            check(Total(controller.ReadSnapshot()) == 20 && controller.PendingKeys.Count == 0, "Selection changes invalidate a late result even when its worker ignores cancellation");
            work = controller.LoadAsync([keys[0]]); stale = Next(); controller.ReturnLive(); stale.Completion.SetResult(Snapshot(88)); Wait(work); controller.Drain();
            check(controller.Record is null && controller.DisplayedKey is null && controller.ReadSnapshot() is null && controller.ReadSummarySnapshot() is null && controller.ReadOnlySnapshot() is null,
                "Returning live cannot be reversed by a late historical analysis result");
            work = controller.LoadAsync([keys[^1]]); last = Next(); last.Completion.SetResult(Snapshot(20)); Wait(work); controller.Drain();
            var previous = controller.Record!; var companion = Path.ChangeExtension(path, ".input.jsonl"); File.WriteAllText(companion, "input");
            settings.Update(current => current with { HiddenHistoryRecords = [keys[0]], InputLogBindings = new(new Dictionary<string, EvidenceValue>
                { [previous.Key] = Obj("""{"path":"trace_20261028.input.jsonl","visible":true,"manual":true,"offset_ms":12}""") }) });
            var moved = controller.Rename(path, "角色测试"); var newKey = HistoryFiles.RelocateKey(previous.Key, path, moved);
            check(controller.DisplayedKey == newKey && controller.Record?.FilePath == moved && controller.SelectedRecords.Single().Key == newKey
                && Total(controller.ReadSnapshot()) == 20, "Rename relocates the displayed record, selection and full cache without altering calculations");
            check(controller.ReadOnlySnapshot() is { } renamedView
                && ((IDictionary<string, EvidenceValue>)renamedView.Fields).IsReadOnly
                && ((IDictionary<string, EvidenceValue>)Battle(renamedView).Fields).IsReadOnly
                && Total(sharedView) == 20,
                "Rename retains protected detail ownership while an earlier shared view stays valid");
            check(settings.Current.ImportedTraceFiles.SequenceEqual([moved]) && settings.Current.HiddenHistoryRecords.Single() == HistoryFiles.RelocateKey(keys[0], path, moved)
                && settings.Current.InputLogBindings.Get(newKey) is EvidenceObject binding && binding.Get("path") is EvidenceText input && input.Value.Contains("角色测试", StringComparison.Ordinal),
                "Rename atomically relocates imported sources, hidden records and relative input bindings in settings");
            controller.Remove([newKey]);
            check(controller.Record is null && controller.CachedSnapshot(previous) is null && File.Exists(moved), "Removing a history row hides it and releases its cached report while preserving the raw log");
            Wait(controller.ImportFilesAsync([moved])); controller.Drain();
            check(controller.Records.Count == 2 && settings.Current.HiddenHistoryRecords.Count == 0, "Explicit reimport restores hidden records from that source");
            work = controller.LoadAsync([newKey]); last = Next(); last.Completion.SetResult(Snapshot(30)); Wait(work); controller.Drain();
            File.AppendAllText(moved, "tail"); check(controller.ReadSnapshot() is null && controller.ReadSummarySnapshot() is null && controller.ReadOnlySnapshot() is null, "A source signature change invalidates full, summary and read-only detail reads");
            controller.ReleaseCache(); check(controller.CachedSnapshot(controller.Record!) is null, "Explicit cache release drops the owned full report");
            work = controller.LoadAsync([newKey]); last = Next(); last.Completion.SetResult(Snapshot(40)); Wait(work);
            File.AppendAllText(moved, "after-worker"); controller.Drain();
            check(controller.ReadSnapshot() is null, "A completed worker cannot cache its report under a later source signature at owner-thread drain");
            work = controller.LoadAsync([newKey]); last = Next(); File.AppendAllText(moved, "during-worker"); last.Completion.SetResult(Snapshot(50)); Wait(work);
            check(controller.Drain().Single().Errors.Count == 1 && !controller.Busy && controller.ReadSnapshot() is null,
                "Source changes during analysis report an error and release pending state without publishing stale data");
            work = controller.LoadAsync([newKey]); last = Next(); last.Completion.SetException(new InvalidDataException("synthetic analysis failure")); Wait(work);
            check(controller.Drain().Single().Errors.Single() == "synthetic analysis failure" && !controller.Busy,
                "Analysis failures become owner-thread notifications and do not strand the history request");
            work = controller.LoadAsync([newKey]); stale = Next(); controller.Dispose(); stale.Completion.SetResult(Snapshot(77)); Wait(work);
            check(controller.Drain().Count == 0 && controller.ReadSnapshot() is null && !controller.Busy, "Closing cancels pending state and rejects late worker completions");
        }
        finally { folder.Delete(recursive: true); }
    }
}
