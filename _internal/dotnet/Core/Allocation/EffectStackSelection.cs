using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

namespace EndfieldLogs.Core.Allocation;

public sealed record EffectStackResult(EvidenceObject Hit, IReadOnlyList<EvidenceObject> Windows,
    IReadOnlyDictionary<int, IReadOnlyList<EvidenceValue>> EffectsAtHit, IReadOnlySet<string> UnresolvedZones,
    IReadOnlyList<EvidenceObject> IgnoredEffects);

/// <summary>Select observable stack baselines without inventing an enabled winner or suppressed self effect.</summary>
public static class EffectStackSelection
{
    private static string Text(EvidenceValue value) => EffectStackPolicy.Text(value);
    private static bool Truth(EvidenceValue value) => CatalogValues.Truth(value);
    private static EvidenceObject Reset(EvidenceObject window)
    {
        // Most historical windows are already reset. Evaluation and flags replace their
        // dictionaries on change, so an unchanged window can keep its owned evidence.
        if (window.Get("_enable_state_unobserved_at_hit") is EvidenceBoolean { Value: false }
            && window.Get("_effect_state_unresolved_at_hit") is EvidenceBoolean { Value: false }
            && window.Fields.TryGetValue("_buff_enabled_at_hit", out var enabled) && enabled is EvidenceNull) return window;
        return new(new Dictionary<string, EvidenceValue>(window.Fields, StringComparer.Ordinal)
        {
            ["_enable_state_unobserved_at_hit"] = new EvidenceBoolean(false), ["_effect_state_unresolved_at_hit"] = new EvidenceBoolean(false), ["_buff_enabled_at_hit"] = EvidenceNull.Value,
        });
    }
    private static EvidenceObject Flag(EvidenceObject window, string key) => new(new Dictionary<string, EvidenceValue>(window.Fields, StringComparer.Ordinal) { [key] = new EvidenceBoolean(true) });

    public static EffectStackResult Select(EvidenceObject hit, IReadOnlyList<EvidenceObject> source, EffectHitPosition position,
        EffectStackPolicy policy, IReadOnlyList<int>? selected = null, bool includeDebug = false)
        => SelectTracked(hit, source, position, policy, selected, null, includeDebug);

    internal static EffectStackResult SelectTracked(EvidenceObject hit, IReadOnlyList<EvidenceObject> source, EffectHitPosition position,
        EffectStackPolicy policy, IReadOnlyList<int>? selected, IReadOnlyList<int>? resetIndices, bool includeDebug,
        bool ownsWindows = false)
    {
        var windows = ownsWindows && source is EvidenceObject[] owned ? owned : source.ToArray();
        if (resetIndices is null)
            for (var index = 0; index < windows.Length; index++) windows[index] = Reset(windows[index]);
        else
            foreach (var index in resetIndices) windows[index] = Reset(windows[index]);
        var indices = selected ?? Enumerable.Range(0, windows.Length).ToArray();
        var updatedHit = hit;
        Dictionary<int, IReadOnlyList<EvidenceValue>> effects = [];
        foreach (var index in indices)
        {
            var evaluated = EffectWindowEvaluation.At(windows[index], position);
            windows[index] = evaluated.Window;
            effects[index] = evaluated.Effects;
        }
        Dictionary<EffectStackGroup, List<int>> groups = [], disabledSelf = [];
        HashSet<string> unresolved = new(StringComparer.Ordinal);
        List<EvidenceObject> ignored = [];
        var attacker = hit.Get("character_key");
        var enemy = hit.Get("target_enemy_key");
        var element = (hit.Get("damage_element") as EvidenceText)?.Value;
        var school = (hit.Get("damage_school") as EvidenceText)?.Value;
        static void Add(Dictionary<EffectStackGroup, List<int>> table, EffectStackGroup key, int index)
        {
            if (!table.TryGetValue(key, out var rows)) table[key] = rows = [];
            rows.Add(index);
        }
        IEnumerable<EvidenceObject> Potential(EvidenceObject window) => new[] { "zone_effects", "dynamic_effects" }
            .SelectMany(key => window.Get(key) is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : []);
        HashSet<string> Zones(IEnumerable<EvidenceValue> rows) => rows.OfType<EvidenceObject>()
            .Where(effect => EffectConditions.AppliesToHit(effect, element, school))
            .Select(effect => CatalogValues.Text(effect.Get("zone"))).ToHashSet(StringComparer.Ordinal);
        void Mark(int index, HashSet<string> zones, string reason, bool stack, EffectStackGroup? group = null, IEnumerable<string>? uids = null)
        {
            if (zones.Count == 0) return;
            unresolved.UnionWith(zones);
            updatedHit = Flag(updatedHit, "rdps_unresolved_effect_conditions");
            if (stack) windows[index] = Flag(windows[index], "rdps_unresolved_stack_evidence");
            if (!includeDebug) return;
            var window = windows[index];
            Dictionary<string, EvidenceValue> fields = new(StringComparer.Ordinal)
            {
                ["uid"] = window.Get("uid"), ["event_key"] = window.Get("event_key"),
                ["reason"] = new EvidenceText(reason), ["reason_group"] = new EvidenceText("condition_unobservable"),
            };
            if (group is not null) fields["stack_group"] = new EvidenceArray(group.Fields.Select(value => (EvidenceValue)new EvidenceText(value)).ToArray());
            if (uids is not null) fields["candidate_uids"] = new EvidenceArray(uids.Order(PythonDisplay.CodePointComparer).Select(value => (EvidenceValue)new EvidenceText(value)).ToArray());
            ignored.Add(new(fields));
        }
        foreach (var index in indices)
        {
            var window = windows[index];
            var owner = window.Get("target_character_key");
            var selfOwner = EvidenceJson.PythonEquals(owner, attacker);
            var actor = Text(hit.Get(selfOwner ? "source_actor_id" : "target_actor_id"));
            var targetActor = Text(window.Get("target_actor_id"));
            if (!selfOwner && !EvidenceJson.PythonEquals(owner, enemy) || actor.Length > 0 && targetActor.Length > 0 && actor != targetActor) continue;
            if (Truth(window.Get("_effect_state_unresolved_at_hit")))
                Mark(index, Zones(Potential(window)), "unresolved_buff_state_zone_baseline", false);
            var group = policy.Group(window);
            if (window.Get("_buff_enabled_at_hit") is EvidenceBoolean { Value: false } && EvidenceJson.PythonEquals(window.Get("source_character_key"), attacker))
                Add(disabledSelf, group, index);
            if (effects[index].Count > 0) Add(groups, group, index);
        }
        foreach (var (group, members) in groups)
        {
            HashSet<string> policies = new(StringComparer.Ordinal);
            HashSet<BigInteger?> limits = [];
            foreach (var index in members)
            {
                var window = windows[index];
                var key = Text(window.Get("event_key"));
                var settings = policy.Settings(key);
                policies.Add(EvidenceJsonSignature.Sorted(settings?.Get("stackingType") ?? window.Get("stacking_type")));
                limits.Add(settings is null ? EffectStackPolicy.Positive(window.Get("stack_limit")) : policy.Limit(key, window.Get("bb_values") as EvidenceObject));
            }
            bool HasPolicy(string value) => policies.Contains(EvidenceJsonSignature.Sorted(new EvidenceText(value)));
            if (policies.Count == 1 && HasPolicy("Unlimited")) continue;
            if ((HasPolicy("HighPriority") || HasPolicy("HighPriorityWithMaxStack")) && disabledSelf.TryGetValue(group, out var suppressed)
                && members.Any(index => !EvidenceJson.PythonEquals(windows[index].Get("source_character_key"), attacker)))
                foreach (var index in members.Concat(suppressed)) Mark(index, Zones(Potential(windows[index])), "unresolved_priority_self_baseline", true);
            var uids = members.Select(index => Text(windows[index].Get("uid")) is { Length: > 0 } uid ? uid : $"unknown:{index}").ToHashSet(StringComparer.Ordinal);
            if (uids.Count <= 1) continue;
            var limit = limits.Count == 1 ? limits.First() : null;
            if (policies.Count == 1 && limit is not null && uids.Count <= limit) continue;
            foreach (var index in members) Mark(index, Zones(effects[index]), "unresolved_buff_stack_selection", true, group, uids);
        }
        return new(updatedHit, windows, effects, unresolved, ignored);
    }
}
