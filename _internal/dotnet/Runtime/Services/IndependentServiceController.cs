using System.Collections.Concurrent;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Input;
using EndfieldLogs.Runtime.Tracing;
using EndfieldLogs.Runtime.Vision;

namespace EndfieldLogs.Runtime.Services;

public sealed record IndependentServiceState(EvidenceObject InputStatus, bool InputRunning, bool InputTransitioning,
    string VisualStatus, EvidenceObject? ComboSnapshot);

/// <summary>Owner-thread coordination with serialized background commands. Settings commit only while the owner drains results.</summary>
public sealed class IndependentServiceController(IInputRecordingService input, VisionService vision,
    Action<IReadOnlySet<string>> setCaptureStreams, SettingsStore settings, string nativeDirectory,
    Action<string>? diagnostic = null) : IAsyncDisposable
{
    private sealed record Completion(long Revision, bool? Enabled, Exception? Error);
    private readonly int owner = Environment.CurrentManagedThreadId;
    private readonly ConcurrentQueue<Completion> completions = new();
    private readonly CancellationTokenSource lifetime = new();
    private Task inputTask = Task.CompletedTask, visionTask = Task.CompletedTask;
    private Task? shutdown;
    private HashSet<string> subscriptions = new(StringComparer.Ordinal);
    private bool preview, closed, inputDesired;
    private long inputRevision;
    private string? session, trace, inputError;
    private bool recording;
    public bool InputEnabled => settings.Current.InputRecordingEnabled || settings.Current.StartInputRecordingOnLaunch;

    public string GameExecutable => Path.Combine(settings.Current.Service.NativeGameDirectory, settings.Current.Service.GameExecutable);
    public bool InputTransitioning => !inputTask.IsCompleted;
    private void AssertOwner()
    { if (Environment.CurrentManagedThreadId != owner) throw new InvalidOperationException("独立服务只能由所属线程协调"); }
    public void SetRequirements(IEnumerable<string> streams)
    {
        AssertOwner(); if (closed) return;
        subscriptions = new(streams, StringComparer.Ordinal);
        setCaptureStreams(subscriptions.Where(value => value is "analysis_snapshot" or "analysis_summary").ToHashSet(StringComparer.Ordinal));
        UpdateVision();
    }
    public void SetPreview(bool active)
    { AssertOwner(); if (closed) return; preview = active; vision.SetPreview(active); UpdateVision(); }
    private void UpdateVision()
    {
        vision.SetGameExecutable(GameExecutable);
        var active = preview || subscriptions.Contains("combo_snapshot"); var before = visionTask;
        visionTask = Task.Run(() => RunVisionAsync(before, active));
    }
    private async Task RunVisionAsync(Task before, bool active)
    {
        await before.ConfigureAwait(false);
        try { await vision.SetEnabledAsync(active).ConfigureAwait(false); }
        catch (Exception error) { completions.Enqueue(new(-1, null, error)); }
    }
    public void StartInput()
    {
        AssertOwner(); if (closed || inputDesired && (!inputTask.IsCompleted || input.Running)) return;
        settings.Update(current => current with { InputRecordingEnabled = true, StartInputRecordingOnLaunch = true });
        if (recording) SetInput(true);
    }
    public void ToggleInput()
    {
        AssertOwner(); if (closed) return;
        var enabled = !InputEnabled;
        settings.Update(current => current with { InputRecordingEnabled = enabled, StartInputRecordingOnLaunch = enabled });
        SetInput(recording && enabled);
    }
    public Task SetRecording(bool active, string? path = null)
    {
        AssertOwner(); if (closed || recording == active && trace == path) return inputTask;
        recording = active; trace = path;
        SetInput(active && InputEnabled);
        return inputTask;
    }
    public void ApplyInputPreference()
    {
        AssertOwner(); if (closed) return;
        var desired = recording && InputEnabled;
        if (desired != inputDesired) SetInput(desired);
    }
    private void SetInput(bool active)
    {
        inputDesired = active; var revision = ++inputRevision;
        var service = settings.Current.Service;
        InputRecordingOptions options = new(GameExecutable, service.LogDirectory, nativeDirectory, trace);
        var before = inputTask;
        inputTask = Task.Run(() => RunInputAsync(before, revision, active, options));
    }
    private async Task RunInputAsync(Task before, long revision, bool active, InputRecordingOptions options)
    {
        await before.ConfigureAwait(false);
        try
        {
            if (active) await input.StartAsync(options, token: lifetime.Token).ConfigureAwait(false);
            else await input.StopAsync().ConfigureAwait(false);
            completions.Enqueue(new(revision, input.Running, null));
        }
        catch (Exception error) { completions.Enqueue(new(revision, false, error)); }
    }
    public void SetSession(string? value)
    {
        AssertOwner(); if (closed || value == session) return;
        session = value; vision.SetIdentity([]);
    }
    public void SetMembers(IEnumerable<VisionMember> members)
    { AssertOwner(); if (!closed) vision.SetIdentity(members.ToArray()); }
    public void SetTrace(string? path)
    {
        AssertOwner(); if (closed || trace == path) return;
        trace = path; var before = inputTask; inputTask = Task.Run(() => RunTraceAsync(before, path));
    }
    private async Task RunTraceAsync(Task before, string? path)
    {
        await before.ConfigureAwait(false);
        try { await input.SetTraceAsync(path).ConfigureAwait(false); }
        catch (Exception error) { completions.Enqueue(new(-1, null, error)); }
    }
    public void CaptureStopped()
    { AssertOwner(); if (closed) return; _ = SetRecording(false); session = null; vision.SetIdentity([]); }
    public void ConfigureVision(EvidenceObject value)
    {
        AssertOwner(); if (closed) return;
        var snapshot = (EvidenceObject)EvidenceJson.Clone(value); vision.Configure(snapshot);
        settings.Update(current => current with { VisionSettings = snapshot });
    }
    public void PreviewVisionSettings(EvidenceObject value)
    { AssertOwner(); if (!closed) vision.Configure((EvidenceObject)EvidenceJson.Clone(value)); }
    public EvidenceObject VisualState { get { AssertOwner(); return vision.State; } }
    public VisionTargets VisualTargets { get { AssertOwner(); return vision.Targets; } }
    public void RefreshGameExecutable() { AssertOwner(); if (!closed) vision.SetGameExecutable(GameExecutable); }
    public IndependentServiceState Poll()
    {
        AssertOwner();
        while (completions.TryDequeue(out var completed))
        {
            if (completed.Error is not null) diagnostic?.Invoke("独立服务操作失败：" + completed.Error.Message);
            if (closed || completed.Revision != inputRevision || completed.Enabled is not { } enabled) continue;
            inputDesired = enabled;
            // Current recording state is separate from the user's start-on-launch preference.
            // Pausing disk recording does not clear the user's input enable option.
        }
        var status = input.Status;
        var failure = status.Get("status") is EvidenceText { Value: "error" } ? TraceData.Text(status.Get("error")) : null;
        if (!string.IsNullOrEmpty(failure) && failure != inputError) diagnostic?.Invoke("输入记录故障：" + failure);
        inputError = failure;
        return new(status, input.Running, InputTransitioning, TraceData.Text(vision.State.Get("status")), closed ? null : vision.TakeSnapshot());
    }
    public VisionPreview? TakePreview() { AssertOwner(); return closed ? null : vision.TakePreview(); }
    public ValueTask DisposeAsync()
    {
        AssertOwner();
        if (shutdown is not null) return new(shutdown);
        closed = true; preview = false; subscriptions.Clear();
        lifetime.Cancel();
        setCaptureStreams(new HashSet<string>(StringComparer.Ordinal));
        vision.SetPreview(false);
        shutdown = StopAsync(inputTask, visionTask); return new(shutdown);
    }
    private async Task StopAsync(Task recording, Task visual)
    {
        // All commands have bounded waits in their service owners. Both cleanup paths always get a chance to run.
        await Task.WhenAll(recording, visual).ConfigureAwait(false);
        await Task.WhenAll(input.DisposeAsync().AsTask(), vision.DisposeAsync().AsTask()).ConfigureAwait(false);
        lifetime.Dispose();
        while (completions.TryDequeue(out _)) { }
    }
}
