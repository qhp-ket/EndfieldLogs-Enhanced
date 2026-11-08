using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Tracing;

internal static class TraceVolumeSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var folder = Directory.CreateTempSubdirectory("endfield-trace-volumes-");
        try
        {
            var fixture = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../Specs/Fixtures/trace-bridge.json"));
            var bytes = File.ReadAllBytes(fixture);
            check(Convert.ToHexStringLower(SHA256.HashData(bytes)) == "e23935c6e40f3ae3ec0ddd2653fe82ee7b447bed9653315096438c3b22e8632e",
                "Volume/export verification uses the unchanged independent legacy TraceBridge reference");
            var sample = JsonNode.Parse(bytes)!.AsArray().Single(row => row!["name"]!.GetValue<string>() == "0328-mixed-event-order")!;
            var config = JsonNode.Parse(sample["config_json"]!.GetValue<string>())!;
            var table = Path.Combine(folder.FullName, "data/local_tables"); Directory.CreateDirectory(table);
            File.WriteAllText(Path.Combine(table, "NumIdStrTable.json"), config["table"]!.ToJsonString());
            var firstPath = Path.Combine(folder.FullName, "part1.jsonl"); var lastPath = Path.Combine(folder.FullName, "part2.jsonl");
            TraceHeader header = new("synthetic-volume-reference", 1, null, "csharp", "test", "Asia/Shanghai", 480, new Dictionary<string, string>());
            TraceJsonlWriter? writer = null;
            List<TraceEvent> expectedEvents = [];
            TraceBridge bridge = new(_ => throw new InvalidOperationException("Legacy output in typed recording"),
                new SkillResourceCatalog(new ResourceFiles(folder.FullName)), TimeZoneInfo.FindSystemTimeZoneById("China Standard Time"),
                () => 0, eventSink: item => { writer!.Write(item); expectedEvents.Add(item); });
            try
            {
                writer = new(File.Create(firstPath), header);
                var steps = config["steps"]!.AsArray();
                for (var index = 0; index < steps.Count; index++)
                {
                    var step = steps[index]!;
                    if (step["begin"] is { } begin) bridge.BeginCaptureSession(begin.GetValue<long>());
                    else if (step["end"] is not null) bridge.EndCaptureSession();
                    else bridge.Handle((EvidenceObject)EvidenceJson.Parse(step["event_json"]!.GetValue<string>()));
                    if (index != steps.Count / 2) continue;
                    writer.Dispose();
                    writer = new(File.Create(lastPath), header with { Volume = 2, PreviousVolume = new(1, Path.GetFileName(firstPath)) });
                }
            }
            finally { writer?.Dispose(); }
            File.WriteAllText(Path.Combine(folder.FullName, "unrelated.jsonl"), "invalid unrelated file\n");
            var chain = TraceVolumes.Resolve(lastPath);
            check(chain.IsComplete && chain.Volumes.Count == 2 && chain.Volumes[0].FilePath == firstPath,
                "Selecting either volume discovers the complete recording and ignores unrelated JSONL/input files");
            check(TraceVolumes.ReadEvents(chain).Select(TraceJsonl.Serialize).SequenceEqual(expectedEvents.Select(TraceJsonl.Serialize)),
                "Linked replay streams the exact original evidence objects in continuous sequence order");
            var expected = string.Concat(sample["expected"]!.AsArray().Last()!.AsArray().Select(row => row!.GetValue<string>()));
            check(Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(expected))) == "67c66dbbe838934cda9512236bb8d17c03684391967c359e96d8dd11de2f89e7",
                "The selected fixed mixed legacy body is independently pinned");
            var destination = Path.Combine(folder.FullName, "uploader.log");
            var proof = TraceExportService.Export(lastPath, destination, "2026-11-01T12:00:00+08:00");
            var exported = TraceExportService.LoadIntegrity(destination);
            var files = new ResourceFiles(folder.FullName);
            var analysis = BattleReportAnalysis.Load(files, TimeZoneInfo.Utc);
            EvidenceObject? ParseBody(string text)
            {
                BattleIngestionStream stream = new(BattleIngestionResources.Load(files));
                stream.Accept(text.Split('\n').Select((line, index) => (index + 1, line)));
                return analysis.BuildReport(BattleReportInput.Capture(stream, new(1970, 1, 1)), text);
            }
            check(exported.Verified && EvidenceJson.PythonEquals(ParseBody(exported.RawContent)!, ParseBody(expected)!),
                "V2 export preserves the complete parsed legacy report and its final-body integrity proof verifies");
            check(((EvidenceObject)proof.Get("meta")).Get("source_recording_id") is EvidenceText { Value: "synthetic-volume-reference" }
                && ((EvidenceObject)proof.Get("meta")).Get("source_volumes") is EvidenceArray { Items.Count: 2 },
                "Export provenance identifies the recording and every source volume separately from the body");
            HistoryCatalog catalog = new(TimeZoneInfo.Utc);
            HistoryIndex indexCache = new(Path.Combine(folder.FullName, "index"), catalog);
            var record = indexCache.Records(lastPath, trace: true).Single();
            check(record.StructuredSource is { Volumes.Count: 2 } && record.FilePath == firstPath && !record.AnalysisLoaded
                && record.TotalDamage == 0 && record.Players.Count == 0 && record.ReferenceDate == "1970-01-01",
                "Structured history stores linked event bounds and original recording date without calculating a report");
            check(indexCache.Records(lastPath, trace: true).Single().Key == record.Key,
                "The persisted structured index retains recording identity across reloads");
            HistoryAnalyzer analyzer = new(new ResourceFiles(folder.FullName), TimeZoneInfo.Utc);
            var history = analyzer.Analyze(record);
            var oldHistory = analyzer.Analyze(catalog.Read(destination, trace: true).Single());
            var typedBattle = (EvidenceObject)history.Get("battle"); var oldBattle = (EvidenceObject)oldHistory.Get("battle");
            // This old sample has eHP=0 on every hit: existing accounting caps five subsequent hits.
            check(EvidenceJson.PythonEquals(typedBattle.Get("total_damage"), new EvidenceInteger(197_967))
                && typedBattle.Get("rdps_damage_basis") is EvidenceObject basis
                && EvidenceJson.PythonEquals(basis.Get("hit_count"), new EvidenceInteger(6))
                && EvidenceJson.PythonEquals(basis.Get("overkill_capped_hit_count"), new EvidenceInteger(5)),
                "Typed bounded history preserves all six hits and the existing packet-HP overkill cap");
            check(EvidenceJson.PythonEquals(typedBattle.Get("duration_ms"), oldBattle.Get("duration_ms")),
                "Typed bounded history preserves legacy duration: " + PythonSortedJson.Serialize(typedBattle.Get("duration_ms"))
                    + " / " + PythonSortedJson.Serialize(oldBattle.Get("duration_ms")));
            check(EvidenceJson.PythonEquals(history.Get("participants"), oldHistory.Get("participants")),
                "Typed bounded history preserves participant contributions from the independent legacy body");
            check(history.Get("timeline_events") is EvidenceArray { Items.Count: 6 }
                && history.Get("snapshot_quality") is EvidenceObject,
                "Structured history retains every damage timeline point and report quality evidence");
            var singleExport = Path.Combine(folder.FullName, "selected-cross-volume.log");
            TraceExportService.ExportBattle(record, singleExport);
            var selectedExportRows = catalog.Read(singleExport, true);
            check(selectedExportRows.Count == 1 && TraceExportService.LoadIntegrity(singleExport).Verified
                && EvidenceJson.PythonEquals(analyzer.Analyze(selectedExportRows.Single()).Get("participants"), history.Get("participants")),
                "Selected battle export spanning volumes retains all hit and participant evidence with one compatible battle");
            var renamed = Path.Combine(folder.FullName, "renamed.jsonl"); File.Move(firstPath, renamed);
            var relocated = HistoryFiles.Relocate(record, firstPath, renamed);
            check(HistoryCatalog.SourcesUnchanged(relocated)
                && EvidenceJson.PythonEquals(((EvidenceObject)analyzer.Analyze(relocated).Get("battle")).Get("total_damage"), new EvidenceInteger(197_967)),
                "History rename relocates every retained source reference and preserves typed analysis");
            TraceExportService.Export(lastPath, destination);
            check(TraceVolumes.Resolve(renamed).Volumes.Count == 2 && TraceExportService.LoadIntegrity(destination).RawContent == exported.RawContent,
                "Renaming a volume preserves identity-based discovery and deterministic compatibility output");
            var moved = Directory.CreateDirectory(Path.Combine(folder.FullName, "missing"));
            var outside = Path.Combine(moved.FullName, Path.GetFileName(renamed)); File.Move(renamed, outside);
            var incomplete = TraceVolumes.Resolve(lastPath);
            check(!incomplete.IsComplete && incomplete.Issues.Count == 1, "A missing predecessor is explicitly marked incomplete");
            check(!HistoryCatalog.SourcesUnchanged(relocated), "Removing a linked volume invalidates the owned history snapshot");
            var refused = Path.Combine(folder.FullName, "refused.log");
            try { TraceExportService.Export(lastPath, refused); throw new InvalidOperationException("Missing volume accepted"); }
            catch (InvalidDataException) { check(!File.Exists(refused), "Missing evidence cannot be sealed into a complete uploader snapshot"); }
            File.Move(outside, renamed);
            var secondEvents = TraceVolumes.ReadEvents(TraceVolumes.Resolve(lastPath)).ToArray();
            var secondHeader = chain.Volumes[1].Header;
            int firstCount;
            using (TraceJsonlReader reader = new())
                firstCount = reader.Feed(File.ReadAllBytes(renamed)).OfType<TraceEvent>().Count();
            using (TraceJsonlWriter corrupt = new(File.Create(lastPath), secondHeader))
                foreach (var item in secondEvents.Skip(firstCount)) corrupt.Write(item with { Sequence = item.Sequence + 1 });
            try { TraceExportService.Export(lastPath, refused); throw new InvalidOperationException("Cross-volume gap accepted"); }
            catch (InvalidDataException) { check(!File.Exists(refused), "Cross-volume sequence gaps are rejected before creating export output"); }
        }
        finally { folder.Delete(recursive: true); }
    }
}
