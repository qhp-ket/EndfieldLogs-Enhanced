using System.Collections.Concurrent;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Runtime.Input;

public sealed record InputEvidenceState(string? TracePath, IReadOnlyList<string> Paths, bool Visible, double OffsetMs, double? StartOverride,
    IReadOnlyDictionary<int, string> ManualSlots, EvidenceObject Settings, bool Pending, string? Error, EvidenceObject Evidence);

/// <summary>One battle's independent input binding and generation-checked display evidence.</summary>
public sealed class InputEvidenceController : IDisposable
{
    private sealed record Result(long Generation, EvidenceObject? Evidence, string? Error);
    private readonly int owner = Environment.CurrentManagedThreadId;
    private readonly SettingsStore store;
    private readonly EvidenceObject battle;
    private readonly Func<InputEvidenceRequest, CancellationToken, Task<EvidenceObject>> loader;
    private readonly InputEvidenceLoader? ownedLoader;
    private readonly ConcurrentQueue<Result> results = new();
    private CancellationTokenSource cancel = new();
    private long generation;
    private bool closed, pending;
    private string? recordKey, tracePath, error;
    private InputBinding binding = new(null, false, 0, null, new Dictionary<int, string>(), false);
    private IReadOnlyList<string> paths = [];
    private EvidenceObject settings;
    private EvidenceObject evidence = Empty();
    public InputEvidenceController(EvidenceObject battle, SettingsStore store, Func<InputEvidenceRequest, CancellationToken, Task<EvidenceObject>>? loader = null)
    {
        this.store = store; this.battle = Copy(battle);
        if (loader is null) { ownedLoader = new(); this.loader = ownedLoader.LoadAsync; } else this.loader = loader;
        settings = InputInterpretationSettings.Normalize(store.Current.InputSettings).ToEvidence();
    }
    private static EvidenceObject Copy(EvidenceObject value) => (EvidenceObject)EvidenceJson.Clone(value);
    private static EvidenceObject Empty() => (EvidenceObject)EvidenceJson.Parse("""{"actions":[],"raw":[],"warnings":[]}""");
    private void Owner() { if (Environment.CurrentManagedThreadId != owner) throw new InvalidOperationException("输入证据只能在所属线程提交"); }
    public InputEvidenceState State => new(tracePath, paths.ToArray(), binding.Visible, binding.OffsetMs, binding.StartOverride,
        new Dictionary<int, string>(binding.ManualSlots), Copy(settings), pending, error, Copy(evidence));
    public Task SetRecordAsync(HistoryRecord record)
    {
        Owner(); if (closed) return Task.CompletedTask;
        recordKey = record.Key; tracePath = record.FilePath;
        binding = InputBindings.Read(store.Current.InputLogBindings.Get(recordKey), tracePath);
        paths = ResolvePaths(store.Current.InputLogBindings.Fields.ContainsKey(recordKey), binding, tracePath);
        return ReloadAsync();
    }
    private static IReadOnlyList<string> ResolvePaths(bool saved, InputBinding binding, string path) =>
        saved && binding.SourcePath is null ? [] : saved && binding.Manual ? binding.SourcePaths ?? [binding.SourcePath!] : InputEvidenceLoader.Discover(path);
    public Task BindAsync(string path)
    {
        Owner(); if (closed) return Task.CompletedTask; paths = [Path.GetFullPath(path)];
        binding = binding with { SourcePath = paths[0], Manual = true, OffsetMs = 0, StartOverride = null, ManualSlots = new Dictionary<int, string>() };
        SaveBinding(); return ReloadAsync();
    }
    public Task UnbindAsync()
    {
        Owner(); if (closed) return Task.CompletedTask; paths = []; binding = binding with { SourcePath = null, Manual = false };
        SaveBinding(); return ReloadAsync();
    }
    public void SetVisible(bool visible)
    { Owner(); if (closed) return; binding = binding with { Visible = visible }; SaveBinding(); }
    public Task SetAlignmentAsync(double offsetMs, double? startOverride, IReadOnlyDictionary<int, string> manualSlots)
    {
        Owner(); if (closed) return Task.CompletedTask;
        binding = binding with { OffsetMs = offsetMs, StartOverride = startOverride, ManualSlots = new Dictionary<int, string>(manualSlots), Manual = true };
        SaveBinding(); return ReloadAsync();
    }
    public Task SetSettingsAsync(EvidenceObject value)
    {
        Owner(); if (closed) return Task.CompletedTask; settings = InputInterpretationSettings.Normalize(value).ToEvidence();
        store.Update(current => current with { InputSettings = Copy(settings) }); return ReloadAsync();
    }
    private void SaveBinding()
    {
        if (recordKey is null || tracePath is null) return;
        store.Update(current =>
        {
            var values = current.InputLogBindings.Fields.ToDictionary(); values[recordKey] = InputBindings.Write(tracePath,
                binding with { SourcePath = paths.FirstOrDefault(), SourcePaths = paths.ToArray() });
            return current with { InputLogBindings = new(values) };
        });
    }
    private void Invalidate()
    {
        cancel.Cancel(); cancel.Dispose(); cancel = new(); generation++; pending = false; evidence = Empty(); error = null;
        while (results.TryDequeue(out _)) { }
    }
    public Task ReloadAsync()
    {
        Owner(); if (closed) return Task.CompletedTask; Invalidate();
        if (recordKey is null || tracePath is null || paths.Count == 0) return Task.CompletedTask;
        pending = true; var request = generation; var token = cancel.Token;
        InputEvidenceRequest input = new(paths.ToArray(), tracePath, Copy(battle), Copy(settings), binding.OffsetMs,
            new Dictionary<int, string>(binding.ManualSlots), binding.StartOverride, !binding.Manual);
        return Task.Run(async () =>
        {
            Result result;
            try { result = new(request, Copy(await loader(input, token).ConfigureAwait(false)), null); }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { return; }
            catch (Exception failure) { result = new(request, null, failure.Message); }
            if (!token.IsCancellationRequested) results.Enqueue(result);
        }, CancellationToken.None);
    }
    public Task RelocateAsync(string oldPath, string newPath)
    {
        Owner(); if (closed || !string.Equals(tracePath, oldPath, StringComparison.OrdinalIgnoreCase)) return Task.CompletedTask;
        if (recordKey is not null) recordKey = HistoryFiles.RelocateKey(recordKey, oldPath, newPath); tracePath = newPath;
        var saved = InputBindings.Read(recordKey is null ? null : store.Current.InputLogBindings.Get(recordKey), newPath);
        paths = ResolvePaths(store.Current.InputLogBindings.Fields.ContainsKey(recordKey ?? ""), saved, newPath); return ReloadAsync();
    }
    public bool Drain()
    {
        Owner(); var changed = false;
        while (results.TryDequeue(out var result))
        {
            if (closed || result.Generation != generation) continue;
            pending = false; error = result.Error; evidence = result.Evidence ?? Empty(); changed = true;
        }
        return changed;
    }
    public void Dispose()
    { Owner(); if (closed) return; closed = true; Invalidate(); cancel.Dispose(); ownedLoader?.ClearCache(); }
}
