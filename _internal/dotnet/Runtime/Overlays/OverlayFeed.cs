using System.Collections.ObjectModel;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Runtime.Overlays;

/// <summary>One ordered stream per publisher. Returning to a retired publisher cannot revive stale state.</summary>
public sealed class OverlaySnapshotGate
{
    private readonly HashSet<string> retired = new(StringComparer.Ordinal);
    private string? stream;
    private System.Numerics.BigInteger sequence = -1;
    public bool Accept(EvidenceObject message, string type, int version)
    {
        if (message.Get("type") is not EvidenceText kind || kind.Value != type
            || !EvidenceJson.PythonEquals(message.Get("schema_version"), new EvidenceInteger(version))
            || message.Get("stream_id") is not EvidenceText { Value.Length: > 0 } id
            || message.Get("sequence") is not EvidenceInteger { Value.Sign: >= 0 } next
            || message.Get("snapshot") is not (EvidenceNull or EvidenceObject)
            || retired.Contains(id.Value) || stream == id.Value && next.Value <= sequence) return false;
        if (stream is not null && stream != id.Value) retired.Add(stream);
        stream = id.Value; sequence = next.Value; return true;
    }
}

/// <summary>Owner-thread live/history presentation; a history report never overwrites the live mailbox.</summary>
public sealed class OverlayFeed
{
    private readonly OverlaySnapshotGate damageGate = new(), comboGate = new();
    private readonly string stream = Guid.NewGuid().ToString();
    private long sequence;
    private EvidenceObject? live;
    public EvidenceObject? Damage { get; private set; }
    public EvidenceObject? Combo { get; private set; }
    public bool Historical { get; private set; }
    public bool Recording { get; private set; }
    public event Action<string, EvidenceObject>? Changed;
    public bool Receive(EvidenceObject message)
    {
        if (message.Get("type") is EvidenceText { Value: "recording_state" })
        {
            var active = message.Get("recording") is EvidenceBoolean { Value: true };
            if (active == Recording) return false;
            Recording = active; Changed?.Invoke("recording_state", message); return true;
        }
        if (damageGate.Accept(message, "analysis_summary", 1))
        {
            live = (EvidenceObject)Capture(message);
            if (!Historical) Present(live.Get("snapshot") as EvidenceObject, SettingsData.Empty(), live.Get("error"));
            return true;
        }
        if (message.Get("snapshot") is EvidenceObject snapshot && snapshot.Get("slots") is EvidenceArray
            && comboGate.Accept(message, "combo_snapshot", 2))
        { Combo = (EvidenceObject)Capture(message); Changed?.Invoke("combo_snapshot", Combo); return true; }
        return false;
    }
    public void ShowHistory(EvidenceObject snapshot, string label)
    {
        Historical = true;
        Present((EvidenceObject)Capture(snapshot), SettingsData.Make(("mode", "history"), ("label", label)));
    }
    public void ReturnLive()
    { Historical = false; Present(live?.Get("snapshot") as EvidenceObject, SettingsData.Empty(), live?.Get("error")); }
    public void ClearLive()
    { live = null; if (!Historical) Present(null, SettingsData.Empty()); }
    private void Present(EvidenceObject? snapshot, EvidenceObject source, EvidenceValue? error = null)
    {
        // The mailbox owns one recursively read-only capture. Live/history switches and
        // all window instances share it; neither producers nor subscribers can mutate it.
        Damage = new(new ReadOnlyDictionary<string, EvidenceValue>(new Dictionary<string, EvidenceValue>
        {
            ["type"] = new EvidenceText("analysis_summary"), ["schema_version"] = new EvidenceInteger(1),
            ["stream_id"] = new EvidenceText(stream), ["sequence"] = new EvidenceInteger(++sequence),
            ["snapshot"] = snapshot is null ? EvidenceNull.Value : snapshot,
            ["source"] = Capture(source), ["error"] = error ?? EvidenceNull.Value,
        }));
        Changed?.Invoke("analysis_summary", Damage);
    }

    private static EvidenceValue Capture(EvidenceValue value) => value switch
    {
        EvidenceObject obj => new EvidenceObject(new ReadOnlyDictionary<string, EvidenceValue>(
            obj.Fields.ToDictionary(pair => pair.Key, pair => Capture(pair.Value), StringComparer.Ordinal)))
        {
            SourcePairs = obj.SourcePairs is null ? null : Array.AsReadOnly(obj.SourcePairs.Select(pair =>
                new KeyValuePair<string, EvidenceValue>(pair.Key, Capture(pair.Value))).ToArray()),
        },
        EvidenceArray array => new EvidenceArray(Array.AsReadOnly(array.Items.Select(Capture).ToArray())),
        _ => value,
    };
}
