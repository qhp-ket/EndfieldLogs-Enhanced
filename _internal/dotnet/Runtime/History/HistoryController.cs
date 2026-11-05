using System.Collections.Concurrent;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Runtime.History;

public sealed record HistoryAnalysisItem(string Key, EvidenceObject? Snapshot, string? Error, HistoryFileSignature? Signature = null);
public sealed record HistoryNotification(string Kind, IReadOnlyList<string> Errors, bool OpenDetails = false);

/// <summary>Owner-thread state and disposable worker requests; stale tasks can never commit into a new selection.</summary>
public sealed class HistoryController(SettingsStore settings, HistoryIndex index, Func<HistoryRecord, CancellationToken, Task<EvidenceObject>> analyze,
    Func<string, bool>? isWriting = null) : IDisposable
{
    // Only the sealed production analyzer promises a detached result on every call.
    // Arbitrary delegates retain the defensive copy boundary of the public constructor.
    private readonly bool ownsAnalysisResult;
    public HistoryController(SettingsStore settings, HistoryIndex index, HistoryAnalyzer analyzer, Func<string, bool>? isWriting = null)
        : this(settings, index, analyzer.AnalyzeAsync, isWriting) { ownsAnalysisResult = true; }

    private sealed record Completion(string Kind, long Generation, IReadOnlyList<HistoryRecord> Records, IReadOnlyList<string> Errors,
        IReadOnlyList<HistoryAnalysisItem>? Analysis = null, bool OpenDetails = false, bool RestoreRemoved = false);
    private readonly int owner = Environment.CurrentManagedThreadId;
    private readonly ConcurrentQueue<Completion> completions = new();
    private readonly CancellationTokenSource lifetime = new();
    private CancellationTokenSource? analysisCancel;
    private long generation, listingGeneration, importGeneration;
    private bool closed;
    private string? logDirectory, detailKey;
    private EvidenceObject? detailSnapshot;
    private HistoryFileSignature? detailSignature;
    private List<HistoryRecord> rawRecords = [];
    private readonly Dictionary<string, IReadOnlyList<HistoryRecord>> traces = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> pending = new(StringComparer.Ordinal);
    private List<string> selection = [];
    public IReadOnlyList<HistoryRecord> Records { get; private set; } = [];
    public HistoryRecord? Record { get; private set; }
    public string? DisplayedKey { get; private set; }
    public bool RecordsPending { get; private set; }
    public bool ImportPending { get; private set; }
    public bool Busy => RecordsPending || ImportPending || pending.Count > 0;
    public IReadOnlyList<HistoryRecord> SelectedRecords => selection.Select(key => Records.FirstOrDefault(row => row.Key == key)).OfType<HistoryRecord>().ToArray();
    public IReadOnlyList<string> PendingKeys => pending.ToArray();
    private void Owner()
    { if (Environment.CurrentManagedThreadId != owner) throw new InvalidOperationException("历史记录只能在所属线程提交"); }
    private void RefreshList()
    {
        var hidden = settings.Current.HiddenHistoryRecords.ToHashSet(StringComparer.Ordinal);
        Records = rawRecords.Concat(traces.Values.SelectMany(rows => rows)).Where(row => !hidden.Contains(row.Key)).OrderByDescending(row => row.StartedAtMs).ToArray();
        var keys = Records.Select(row => row.Key).ToHashSet(StringComparer.Ordinal); selection = selection.Where(keys.Contains).ToList();
    }
    public void Select(IEnumerable<string> keys, string? current = null)
    {
        Owner(); var requested = keys.Distinct(StringComparer.Ordinal).ToArray(); var order = selection.Where(requested.Contains).Concat(requested.Where(key => !selection.Contains(key))).ToList();
        if (current is not null && order.Remove(current)) order.Add(current);
        if (!order.SequenceEqual(selection) && pending.Count > 0) { InvalidateAnalysis(); Record = Records.FirstOrDefault(row => row.Key == DisplayedKey); }
        selection = order;
    }
    public Task RefreshAsync()
    {
        Owner(); if (closed) return Task.CompletedTask;
        var directory = HistoryIndex.ResolveLogDirectory(settings.Current.Service.LogDirectory, settings.Context);
        if (!string.Equals(logDirectory, directory, StringComparison.OrdinalIgnoreCase))
        { listingGeneration++; RecordsPending = false; rawRecords = []; logDirectory = directory; }
        RefreshList(); Task listing = Task.CompletedTask;
        if (!RecordsPending)
        {
            RecordsPending = true; var request = ++listingGeneration; var token = lifetime.Token;
            listing = Task.Run(() =>
            {
                List<HistoryRecord> records = []; List<string> errors = [];
                HashSet<string> indexedFiles = new(StringComparer.OrdinalIgnoreCase);
                try
                {
                    if (Directory.Exists(directory))
                        foreach (var path in Directory.EnumerateFiles(directory, "session_*.ndjson", SearchOption.AllDirectories).OrderDescending(StringComparer.Ordinal))
                        {
                            token.ThrowIfCancellationRequested();
                            if (!indexedFiles.Add(path)) continue;
                            try
                            {
                                var rows = index.Records(path, cancellationToken: token);
                                records.AddRange(rows);
                                if (rows.FirstOrDefault()?.SessionSource is { } chain)
                                    foreach (var volume in chain.Volumes) indexedFiles.Add(volume.FilePath);
                            }
                            catch (Exception error) when (error is not OperationCanceledException) { errors.Add(Path.GetFileName(path) + ": " + error.Message); }
                        }
                }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException) { errors.Add(error.Message); }
                completions.Enqueue(new("listing", request, records, errors));
            }, token);
        }
        var changed = settings.Current.ImportedTraceFiles.Where(path => Path.GetExtension(path).Equals(".jsonl", StringComparison.OrdinalIgnoreCase)
            || !traces.TryGetValue(path, out var rows) || rows.Count == 0 || !HistoryCatalog.SourcesUnchanged(rows[0])).ToArray();
        return Task.WhenAll(listing, ImportFilesAsync(changed, restoreRemoved: false));
    }
    public Task ImportFilesAsync(IEnumerable<string> paths, bool restoreRemoved = true)
    {
        Owner(); var files = paths.Select(Path.GetFullPath).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        if (closed || ImportPending || files.Length == 0) return Task.CompletedTask;
        ImportPending = true; var request = ++importGeneration; var token = lifetime.Token;
        return Task.Run(() =>
        {
            List<HistoryRecord> records = []; List<string> errors = [];
            foreach (var file in files)
            {
                token.ThrowIfCancellationRequested();
                try { records.AddRange(index.Records(file, trace: true, token)); }
                catch (Exception error) when (error is not OperationCanceledException) { errors.Add(Path.GetFileName(file) + ": " + error.Message); }
            }
            completions.Enqueue(new("import", request, records, errors, RestoreRemoved: restoreRemoved));
        }, token);
    }
    private void InvalidateAnalysis()
    { analysisCancel?.Cancel(); analysisCancel?.Dispose(); analysisCancel = null; generation++; pending.Clear(); }
    public Task LoadAsync(IEnumerable<string> keys, bool openDetails = false)
    {
        Owner(); if (closed) return Task.CompletedTask;
        var indexed = Records.ToDictionary(row => row.Key); var requests = keys.Distinct(StringComparer.Ordinal).Where(indexed.ContainsKey).Select(key => indexed[key] with { Players = indexed[key].Players.ToArray() }).ToArray();
        if (requests.Length == 0) return Task.CompletedTask;
        InvalidateAnalysis(); analysisCancel = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
        var token = analysisCancel.Token; var request = generation; Record = requests[^1]; pending.UnionWith(requests.Select(row => row.Key));
        return Task.Run(async () =>
        {
            List<HistoryAnalysisItem> results = [];
            try
            {
                for (var position = 0; position < requests.Length; position++)
                {
                    var record = requests[position];
                    token.ThrowIfCancellationRequested();
                    try
                    {
                        var signature = Signature(record.FilePath);
                        var analyzed = await analyze(record, token).ConfigureAwait(false);
                        // Earlier selections only update list statistics. Keep the final full
                        // report for details instead of retaining the entire batch until Drain.
                        var selected = position == requests.Length - 1 ? analyzed : new EvidenceObject(analyzed.Fields
                            .Where(pair => pair.Key is "battle" or "participants").ToDictionary());
                        var snapshot = ownsAnalysisResult ? selected : (EvidenceObject)EvidenceJson.Clone(selected);
                        if (openDetails && position == requests.Length - 1)
                            snapshot = (EvidenceObject)EvidenceJson.TakeReadOnlyOwnership(snapshot);
                        if (signature != Signature(record.FilePath) || !HistoryCatalog.SourcesUnchanged(record)) throw new InvalidDataException("日志在分析时发生变化，请刷新记录后重试");
                        results.Add(new(record.Key, snapshot, null, signature));
                    }
                    catch (Exception error) when (error is not OperationCanceledException) { results.Add(new(record.Key, null, error.Message)); }
                }
                token.ThrowIfCancellationRequested(); completions.Enqueue(new("analysis", request, [], [], results, openDetails));
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        }, CancellationToken.None);
    }
    public IReadOnlyList<HistoryNotification> Drain()
    {
        Owner(); List<HistoryNotification> notifications = [];
        while (completions.TryDequeue(out var value))
        {
            if (closed) continue;
            if (value.Kind == "analysis")
            {
                if (value.Generation != generation) continue;
                pending.Clear(); var results = value.Analysis!;
                var updates = results.Where(row => row.Snapshot is not null).ToDictionary(row => row.Key, row => row.Snapshot!);
                rawRecords = rawRecords.Select(row => updates.TryGetValue(row.Key, out var snapshot) ? HistoryAnalyzer.ApplySummary(row, snapshot) : row).ToList();
                foreach (var path in traces.Keys.ToArray()) traces[path] = traces[path].Select(row => updates.TryGetValue(row.Key, out var snapshot) ? HistoryAnalyzer.ApplySummary(row, snapshot) : row).ToArray();
                RefreshList(); var last = results[^1]; Record = Records.FirstOrDefault(row => row.Key == last.Key);
                if (last.Snapshot is not null && Record is not null)
                { DisplayedKey = detailKey = last.Key; detailSnapshot = last.Snapshot; detailSignature = last.Signature; }
                notifications.Add(new("analysis", results.Select(row => row.Error).OfType<string>().ToArray(), value.OpenDetails));
            }
            else if (value.Kind == "listing")
            { if (value.Generation != listingGeneration) continue; RecordsPending = false; rawRecords = value.Records.ToList(); notifications.Add(new("listing", value.Errors)); }
            else
            {
                if (value.Generation != importGeneration) continue;
                ImportPending = false;
                foreach (var group in value.Records.GroupBy(row => row.FilePath, StringComparer.OrdinalIgnoreCase)) traces[group.Key] = group.ToArray();
                if (value.Records.Count > 0)
                {
                    var keys = value.Records.Select(row => row.Key).ToHashSet(StringComparer.Ordinal);
                    settings.Update(current => current with
                    {
                        ImportedTraceFiles = current.ImportedTraceFiles.Concat(value.Records.Select(row => row.FilePath)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray(),
                        HiddenHistoryRecords = value.RestoreRemoved ? current.HiddenHistoryRecords.Where(key => !keys.Contains(key)).ToArray() : current.HiddenHistoryRecords,
                    });
                }
                notifications.Add(new("import", value.Errors));
            }
            RefreshList();
        }
        return notifications;
    }
    private static HistoryFileSignature? Signature(string path)
    { try { return HistoryFileSignature.Read(path); } catch (Exception error) when (error is IOException or UnauthorizedAccessException) { return null; } }
    private EvidenceObject? ValidSnapshot(HistoryRecord record) => detailKey == record.Key && detailSignature == Signature(record.FilePath)
        && HistoryCatalog.SourcesUnchanged(record) ? detailSnapshot : null;
    public EvidenceObject? CachedSnapshot(HistoryRecord record) => ValidSnapshot(record) is { } snapshot ? (EvidenceObject)EvidenceJson.Clone(snapshot) : null;
    public EvidenceObject? ReadSnapshot() => DisplayedKey is not null && Record is not null && Record.Key == DisplayedKey ? CachedSnapshot(Record) : null;
    /// <summary>Shared recursively read-only detail data; public editable reads keep their copy boundary.</summary>
    public EvidenceObject? ReadOnlySnapshot()
    {
        Owner();
        if (DisplayedKey is null || Record is null || Record.Key != DisplayedKey || ValidSnapshot(Record) is not { } snapshot) return null;
        // Explicit detail loads prepare this in the worker. A later detail request
        // can protect the privately owned cache once; home-only loads do no extra work.
        return detailSnapshot = (EvidenceObject)EvidenceJson.TakeReadOnlyOwnership(snapshot);
    }
    /// <summary>Independent home/overlay data, projected before cloning; full evidence stays in the detail cache.</summary>
    public EvidenceObject? ReadSummarySnapshot()
    {
        if (DisplayedKey is null || Record is null || Record.Key != DisplayedKey || ValidSnapshot(Record) is not { } snapshot) return null;
        var fields = snapshot.Fields.Where(pair => pair.Key is "battle" or "participants" or "snapshot_quality" or "quality_summary").ToDictionary();
        if (snapshot.Get("rdps_preflight") is EvidenceObject preflight)
            fields["rdps_preflight"] = new EvidenceObject(new Dictionary<string, EvidenceValue> { ["ok"] = preflight.Get("ok") });
        return (EvidenceObject)EvidenceJson.Clone(new EvidenceObject(fields));
    }
    public void ReturnLive() { Owner(); InvalidateAnalysis(); Record = null; DisplayedKey = null; }
    public void ReleaseCache() { Owner(); detailKey = null; detailSnapshot = null; detailSignature = null; }
    public void Remove(IEnumerable<string> keys)
    {
        Owner(); var removed = keys.ToHashSet(StringComparer.Ordinal);
        if (removed.Contains(DisplayedKey ?? "") || Record is not null && removed.Contains(Record.Key) || pending.Overlaps(removed)) ReturnLive();
        if (removed.Contains(detailKey ?? "")) ReleaseCache();
        settings.Update(current => current with { HiddenHistoryRecords = current.HiddenHistoryRecords.Concat(removed.Order(StringComparer.Ordinal)).Distinct(StringComparer.Ordinal).ToArray() }); RefreshList();
    }
    public string Rename(string path, string label)
    {
        Owner(); if (closed || Busy) throw new InvalidOperationException("请等待当前索引或分析结束后重命名");
        path = Path.GetFullPath(path); var destination = HistoryFiles.Rename(path, label, isWriting);
        if (destination == path) return path;
        rawRecords = rawRecords.Select(row => HistoryFiles.Relocate(row, path, destination)).ToList();
        foreach (var file in traces.Keys.ToArray()) traces[file] = traces[file].Select(row => HistoryFiles.Relocate(row, path, destination)).ToArray();
        if (traces.Remove(path, out var moved)) traces[destination] = moved;
        Record = Record is null ? null : HistoryFiles.Relocate(Record, path, destination);
        DisplayedKey = DisplayedKey is null ? null : HistoryFiles.RelocateKey(DisplayedKey, path, destination);
        detailKey = detailKey is null ? null : HistoryFiles.RelocateKey(detailKey, path, destination);
        selection = selection.Select(key => HistoryFiles.RelocateKey(key, path, destination)).ToList();
        if (detailSnapshot is not null && detailSnapshot.Get("battle") is EvidenceObject battle)
        {
            var fields = battle.Fields.ToDictionary();
            foreach (var key in new[] { "source_file_name", "file_name" }) if (fields.GetValueOrDefault(key) is EvidenceText name && name.Value == Path.GetFileName(path)) fields[key] = new EvidenceText(Path.GetFileName(destination));
            var outer = detailSnapshot.Fields.ToDictionary(); outer["battle"] = new EvidenceObject(fields); detailSnapshot = new(outer);
        }
        index.Relocate(path, destination); settings.Update(current => HistoryFiles.Relocate(current, path, destination)); RefreshList(); return destination;
    }
    public void Dispose()
    {
        Owner(); if (closed) return; closed = true; lifetime.Cancel(); ReturnLive(); ReleaseCache(); listingGeneration++; importGeneration++;
        RecordsPending = ImportPending = false; lifetime.Dispose(); while (completions.TryDequeue(out _)) { }
    }
}
