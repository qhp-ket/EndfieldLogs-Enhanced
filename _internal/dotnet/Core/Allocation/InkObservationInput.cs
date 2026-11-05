using System.Collections.Immutable;
using System.Collections.ObjectModel;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Allocation;

/// <summary>Persistent, detached evidence. Capturing a prefix shares immutable entries, not ingestion state.</summary>
public sealed class InkObservationInput
{
    private readonly object owner;
    private readonly ImmutableList<InkObservation> observations;

    internal InkObservationInput(object owner, ImmutableList<InkObservation> observations)
        => (this.owner, this.observations) = (owner, observations);

    public int Count => observations.Count;
    internal bool Continues(InkObservationInput previous) => ReferenceEquals(owner, previous.owner) && Count >= previous.Count;

    public IEnumerable<InkObservation> After(int count = 0)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(count);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(count, Count);
        if (count == 0)
        {
            foreach (var item in observations) yield return item;
        }
        else
            for (var index = count; index < Count; index++) yield return observations[index];
    }
}

/// <summary>Single ingestion owner. Only relevant observations are retained; original evidence indices never change.</summary>
public sealed class InkObservationLog
{
    private ImmutableList<InkObservation> observations = [];
    private readonly object owner = new();
    public InkObservationInput Capture() => new(owner, observations);

    public void Observe(int index, string line)
    {
        if (line.Contains(" HP_V2 ", StringComparison.Ordinal) || line.Contains(" INK_RELEASE ", StringComparison.Ordinal)
            || line.Contains(" BB_MODIFY_DYNAMIC ", StringComparison.Ordinal) || line.Contains(" BB_SIMPLE_CALC ", StringComparison.Ordinal)
            || line.Contains(" ACTOR_MAP ", StringComparison.Ordinal) || line.Contains(" SKILL_CAST_START ", StringComparison.Ordinal))
            Append(InkObservation.FromLegacy(new(index, line)));
    }

    public void Observe(int index, TraceEvent item)
    {
        if (item.Type is "damage" or "ink_release" or "blackboard_dynamic" or "blackboard_calculation" or "actor_mapping"
            || item.Type == "skill_cast" && item.Data.Get("phase") is EvidenceText { Value: "start" })
            Append(InkObservation.FromEvent(index, item));
    }

    private void Append(InkObservation item) => observations = observations.Add(item with
    {
        Fields = new ReadOnlyDictionary<string, string>(new Dictionary<string, string>(item.Fields, StringComparer.Ordinal)),
        Release = item.Release is null ? null : Freeze(item.Release),
        Identity = item.Identity is null ? null : Freeze(item.Identity),
    });

    private static EvidenceValue Freeze(EvidenceValue value) => value switch
    {
        EvidenceObject obj => new EvidenceObject(new ReadOnlyDictionary<string, EvidenceValue>(
            obj.Fields.ToDictionary(pair => pair.Key, pair => Freeze(pair.Value), StringComparer.Ordinal)))
        {
            SourcePairs = obj.SourcePairs is null ? null : Array.AsReadOnly(obj.SourcePairs.Select(pair =>
                new KeyValuePair<string, EvidenceValue>(pair.Key, Freeze(pair.Value))).ToArray()),
        },
        EvidenceArray array => new EvidenceArray(Array.AsReadOnly(array.Items.Select(Freeze).ToArray())),
        _ => value,
    };
}
