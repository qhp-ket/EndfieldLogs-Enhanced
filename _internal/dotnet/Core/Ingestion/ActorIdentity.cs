using System.Text.RegularExpressions;

namespace EndfieldLogs.Core.Ingestion;

public static partial class ActorIdentity
{
    [GeneratedRegex(@"(chr_\d{4}_[a-z0-9]+)")]
    private static partial Regex CharacterPattern();
    [GeneratedRegex(@"(chr_\d{4}_[a-z0-9]+)_(\d+)")]
    private static partial Regex SquadPattern();
    [GeneratedRegex(@"(eny_\d{4}_[a-z0-9]+)")]
    private static partial Regex EnemyPattern();
    [GeneratedRegex(@"^(eny_\d{4}_[a-z0-9]+(?:_[a-z0-9]+)*)$")]
    private static partial Regex FullEnemyPattern();

    public static string? CharacterKey(params string?[] values) => ExtractKey(values, false);
    public static string? EnemyKey(params string?[] values) => ExtractKey(values, true);

    private static string? ExtractKey(IEnumerable<string?> values, bool enemy)
    {
        foreach (var value in values)
        {
            if (string.IsNullOrEmpty(value)) continue;
            var match = enemy ? FullEnemyPattern().Match(value) : CharacterPattern().Match(value);
            if (!match.Success && enemy) match = EnemyPattern().Match(value);
            if (match.Success) return match.Groups[1].Value;
        }
        return null;
    }

    public static IReadOnlySet<string> PartyActorIds(string line)
    {
        HashSet<string> result = new(StringComparer.Ordinal);
        if (line.Contains(" SQUAD ", StringComparison.Ordinal))
            foreach (Match match in SquadPattern().Matches(line)) result.Add(match.Groups[2].Value);
        if (line.Contains(" ENTITY_STATS ", StringComparison.Ordinal))
        {
            var fields = TraceFields.Extract(line);
            if (fields.GetValueOrDefault("kind") == "character" && CharacterKey(fields.GetValueOrDefault("template")) is not null
                && fields.GetValueOrDefault("id") is { Length: > 0 } id) result.Add(id);
        }
        return result;
    }

    public static bool IsGenericRuntimeSkill(string? skill) => Regex.IsMatch(skill ?? "", @"\Askill_\d+\z");

    public static IReadOnlyList<(string Id, string Template)> SquadBindings(IEnumerable<(string Template, string Identity)> members)
    {
        List<(string, string)> result = [];
        foreach (var (template, identity) in members)
        {
            foreach (Match match in SquadPattern().Matches(template)) result.Add((match.Groups[2].Value, match.Groups[1].Value));
            var names = CharacterPattern().Matches(template);
            var prefix = Regex.Match(identity, @"\A\d+");
            if (names.Count > 0 && names[^1].Index + names[^1].Length == template.Length && prefix.Success)
                result.Add((prefix.Value, names[^1].Groups[1].Value));
            foreach (Match match in SquadPattern().Matches(identity)) result.Add((match.Groups[2].Value, match.Groups[1].Value));
        }
        return result;
    }

    public static void ApplySquad(IEnumerable<(string Id, string Template)> bindings, ISet<string> partyIds, IDictionary<string, string> squad)
    {
        var members = bindings.ToArray();
        foreach (var (id, _) in members) partyIds.Add(id);
        squad.Clear();
        foreach (var (id, template) in members)
            if (!squad.TryAdd(id, template)) { squad.Clear(); break; }
    }

    public static void ObserveSquad(string line, ISet<string> partyIds, IDictionary<string, string> squad) =>
        ApplySquad(SquadPattern().Matches(line).Select(match => (match.Groups[2].Value, match.Groups[1].Value)), partyIds, squad);
}
