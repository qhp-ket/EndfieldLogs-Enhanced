using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Roster, counters and current loadout evidence shared by ordered hit and BUFF handlers.</summary>
public sealed class PartyObservationState
{
    public List<string> Roster { get; } = [];
    public Dictionary<string, ParticipantHitTotals> Participants { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, EvidenceObject> Loadouts { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, HashSet<string>> ActiveSuits { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, string> ActiveWeapons { get; } = new(StringComparer.Ordinal);

    public ParticipantHitTotals ObserveCharacter(string key, string? name)
    {
        if (!Roster.Contains(key, StringComparer.Ordinal)) Roster.Add(key);
        var display = string.IsNullOrEmpty(name) ? key : name;
        if (!Participants.TryGetValue(key, out var participant)) Participants[key] = participant = new(key, display);
        participant.Name = display;
        return participant;
    }

    public void DiscardStaleLoadout(string character)
    {
        if (Loadouts.Count == 0 || Loadouts.ContainsKey(character)) return;
        Loadouts.Clear();
        ActiveSuits.Clear();
        ActiveWeapons.Clear();
    }
}
