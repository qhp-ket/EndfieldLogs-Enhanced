using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class EffectStackSpecs
{
    public static void Run(Action<bool, string> check)
    {
        static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
        var root = Obj("""{"stackingSettings":{"stackingType":"HighPriority","identifierType":"StackingKey","stackingKey":"shared"}}""");
        EffectStackPolicy policy = new(new Dictionary<string, EvidenceObject> { ["one"] = root, ["two"] = root });
        var first = Obj("""{"uid":"1","event_key":"one","source_character_key":"support","target_character_key":"attacker","target_actor_id":"11","start_ts_ms":1000,"end_ts_ms":2000,"zone_effects":[{"zone":"amp","rate":0.2}]}""");
        var second = Obj("""{"uid":"2","event_key":"two","source_character_key":"other","target_character_key":"attacker","target_actor_id":"11","start_ts_ms":1000,"end_ts_ms":2000,"zone_effects":[{"zone":"amp","rate":0.3}]}""");
        var hit = Obj("""{"character_key":"attacker","source_actor_id":"11","ts_ms":1500}""");
        var signature = EvidenceJsonSignature.Sorted(first);
        var unresolved = EffectStackSelection.Select(hit, [first, second], new(1500), policy);
        check(unresolved.UnresolvedZones.SetEquals(["amp"]) && first.Get("rdps_unresolved_stack_evidence") is EvidenceNull
            && EvidenceJsonSignature.Sorted(first) == signature && hit.Get("rdps_unresolved_effect_conditions") is EvidenceNull,
            "Shared native keys group different source templates without modifying source evidence");
        var isolated = EffectStackSelection.Select(hit, [first], new(1500), policy);
        check(isolated.UnresolvedZones.Count == 0 && isolated.Hit.Get("rdps_unresolved_effect_conditions") is EvidenceNull,
            "Selection quality state belongs to each hit and analysis call");
        var skipped = EffectStackSelection.Select(hit, unresolved.Windows, new(999), policy, []);
        check(skipped.Windows.All(window => window.Get("_effect_state_unresolved_at_hit") is EvidenceBoolean { Value: false }
            && window.Get("_buff_enabled_at_hit") is EvidenceNull) && skipped.EffectsAtHit.Count == 0,
            "Unselected windows reset per-hit state while keeping persistent evidence");
        var resetSignature = skipped.Windows.Select(EvidenceJsonSignature.Sorted).ToArray();
        var activeAgain = EffectStackSelection.Select(hit, skipped.Windows, new(1500), policy);
        var inactiveAgain = EffectStackSelection.Select(hit, activeAgain.Windows, new(2001), policy, []);
        check(skipped.Windows.Select(EvidenceJsonSignature.Sorted).SequenceEqual(resetSignature)
            && activeAgain.UnresolvedZones.SetEquals(["amp"])
            && inactiveAgain.Windows.All(window => window.Get("_buff_enabled_at_hit") is EvidenceNull
                && window.Get("_effect_state_unresolved_at_hit") is EvidenceBoolean { Value: false }
                && window.Get("rdps_unresolved_stack_evidence") is EvidenceBoolean { Value: true }),
            "Repeated active and inactive selections isolate transient state and retain persistent quality evidence");
        var limited = EffectWindowSet.ApplyLimits([first], policy).Single();
        check(EvidenceJson.PythonEquals(first.Get("start_ts_ms"), limited.Get("start_ts_ms"))
            && EvidenceJson.PythonEquals(first.Get("end_ts_ms"), limited.Get("end_ts_ms")) && !first.Fields.ContainsKey("stack_limit"),
            "Stack limits preserve observed lifetime and source records");
        var displayChanged = new EvidenceObject(new Dictionary<string, EvidenceValue>(first.Fields) { ["name"] = new EvidenceText("display") });
        check(EffectWindowSet.Deduplicate([first, displayChanged]).Count == 1
            && EffectWindowSet.Deduplicate([first, second]).Count == 2,
            "Repeated instance windows collapse only on evidence identity");
        Deduplication(check, first);
    }

    private static void Deduplication(Action<bool, string> check, EvidenceObject first)
    {
        static EvidenceObject Change(EvidenceObject source, string key, EvidenceValue value) =>
            new(new Dictionary<string, EvidenceValue>(source.Fields) { [key] = value });
        var shifted = Change(first, "start_ts_ms", new EvidenceInteger(1001));
        var sameTime = Change(first, "start_line_no", new EvidenceInteger(2));
        var aliases = Change(first, "uid_aliases", EvidenceJson.Parse("""["1","alias"]"""));
        var changedRate = Change(first, "zone_effects", EvidenceJson.Parse("""[{"zone":"amp","rate":0.3}]"""));
        var enabled = Change(first, "enable_observations", EvidenceJson.Parse("""[{"operationSeq":1,"enabled":false}]"""));
        var snapshot = Change(first, "snapshot_update", new EvidenceBoolean(true));
        var rows = new[] { first, shifted, aliases, changedRate, sameTime, enabled, snapshot };
        var interleaved = rows.Concat(rows.Reverse().Select(row => Change(row, "name", new EvidenceText("display"))));
        check(EffectWindowSet.Deduplicate(interleaved).SequenceEqual(rows),
            "Deduplication keeps original ordering and distinct time, line, alias, nested effect, enable and snapshot evidence");
        var realStart = Change(first, "start_ts_ms", new EvidenceReal(1000));
        var realLine = Change(first, "start_line_no", new EvidenceReal(0));
        var integerUid = Change(first, "uid", new EvidenceInteger(1));
        var realUid = Change(first, "uid", new EvidenceReal(1));
        var typed = new[] { first, realStart, realLine, integerUid, realUid };
        check(EffectWindowSet.Deduplicate(typed.Concat(typed)).SequenceEqual(typed),
            "Typed coordinate grouping and fallback signatures preserve integer, float, text and missing-field distinctions");
        check(EffectWindowSet.Deduplicate([first, Change(first, "start_line_no", EvidenceNull.Value)]).SequenceEqual([first])
            && EffectWindowSet.Deduplicate([Change(first, "uid", new EvidenceText("")), Change(first, "uid", new EvidenceText(""))]).Count == 2,
            "Absent and null identity fields remain equivalent while unidentified windows are never discarded");
        var mutable = Change(first, "zone_effects", EvidenceJson.Parse("""[{"zone":"amp","rate":0.2}]"""));
        check(EffectWindowSet.Deduplicate([first, mutable]).Count == 1, "An exact nested duplicate initially shares the original identity");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)((EvidenceArray)mutable.Get("zone_effects")).Items[0]).Fields)["rate"] = new EvidenceReal(.4);
        check(EffectWindowSet.Deduplicate([first, mutable]).Count == 2,
            "Deduplication retains no cross-call signatures that could conceal later nested evidence changes");
    }
}
