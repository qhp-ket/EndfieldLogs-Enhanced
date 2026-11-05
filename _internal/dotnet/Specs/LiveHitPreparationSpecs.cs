using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class LiveHitPreparationSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static ReportHitInput Input(string json) => new((EvidenceObject)FrozenEvidence.Capture(Obj(json)),
        FrozenEvidence.CaptureNumbers(new Dictionary<System.Numerics.BigInteger, EvidenceValue>()),
        FrozenEvidence.CaptureNumbers(new Dictionary<System.Numerics.BigInteger, EvidenceValue>()),
        FrozenEvidence.CaptureNumbers(new Dictionary<System.Numerics.BigInteger, EvidenceValue>()));
    private static ReportHitInput Change(ReportHitInput input, string key, EvidenceValue value)
    {
        var fields = new Dictionary<string, EvidenceValue>(input.Evidence.Fields) { [key] = value };
        return input with { Evidence = (EvidenceObject)FrozenEvidence.Capture(new EvidenceObject(fields)) };
    }
    private static bool Same(IReadOnlyList<ReportHitInput> actual, IReadOnlyList<ReportHitInput> input)
        => actual.Select(hit => hit.Evidence).Zip(EnemyHpEvidence.Annotate(input.Select(hit => hit.Evidence).ToArray()))
            .All(pair => EffectivelySame(pair.First, pair.Second)) && actual.Count == input.Count;
    private static bool EffectivelySame(EvidenceObject a, EvidenceObject b)
        => EndfieldLogs.Core.Effects.EffectRecordCache.Same(a, b);

    public static void Run(Action<bool, string> check)
    {
        var source = (EvidenceObject)FrozenEvidence.Capture(Obj("""{"a":{"values":[1]},"b":2}"""));
        var patch = (EvidenceObject)FrozenEvidence.Capture(Obj("""{"b":3,"c":4}"""));
        var merged = FrozenEvidence.MergeRoot(source, patch);
        var detached = FrozenEvidence.MutableRoot(merged);
        ((Dictionary<string, EvidenceValue>)detached.Fields)["b"] = new EvidenceInteger(99);
        var publicCopy = (EvidenceObject)EvidenceJson.Clone(merged);
        ((IList<EvidenceValue>)((EvidenceArray)((EvidenceObject)publicCopy.Get("a")).Get("values")).Items)[0] = EvidenceNull.Value;
        check(merged.Fields.Keys.SequenceEqual(["a", "b", "c"]) && merged.Fields.Count == 3
            && merged.Get("b") is EvidenceInteger { Value: var b } && b == 3
            && ((EvidenceArray)((EvidenceObject)merged.Get("a")).Get("values")).Items[0] is EvidenceInteger
            && ReferenceEquals(merged, FrozenEvidence.Capture(merged)),
            "Immutable merged roots preserve replacement/insertion order and detach both writable roots and public descendants");

        var one = Input("""{"target_enemy_key":"eny_test","target_actor_id":"7","enemy_hp_after":900,"hit_value":100,"target_enemy_max_hp":2000}""");
        var two = Change(one, "enemy_hp_after", new EvidenceInteger(800));
        var three = Change(one, "enemy_hp_after", new EvidenceInteger(700));
        LiveHitPreparationCache cache = new();
        var initial = cache.Annotate([one, two]);
        var projected = cache.ProjectedHpHits;
        var appended = cache.Annotate([one, two, three]);
        check(Same(appended, [one, two, three]) && cache.ProjectedHpHits == projected + 1
            && cache.RetractedHpHits == 0 && ReferenceEquals(initial[0], appended[0]) && ReferenceEquals(initial[1], appended[1]),
            "Appending a lower observed HP processes the new hit while retaining the completed HP prefix");
        var healed = Change(three, "enemy_hp_after", new EvidenceInteger(1500));
        var increased = cache.Annotate([one, two, healed]);
        check(Same(increased, [one, two, healed]) && !ReferenceEquals(increased[0], appended[0])
            && appended[0].Evidence.Get("target_enemy_observed_max_hp") is EvidenceInteger { Value: var oldMaximum } && oldMaximum == 1000,
            "A higher later HP observation revises the target's earlier observed maximum without changing an older snapshot");
        var corrected = Change(two, "enemy_hp_after", new EvidenceInteger(600));
        check(Same(cache.Annotate([one, corrected, healed]), [one, corrected, healed])
            && Same(cache.Annotate([one]), [one]) && Same(cache.Annotate([]), [])
            && Same(cache.Annotate([one, two]), [one, two]),
            "Late HP changes, truncation, empty scope and renewed appends restore exact predecessor and maximum state");
        var anotherActor = Change(healed, "target_actor_id", new EvidenceText("8"));
        var noHp = Change(one, "enemy_hp_after", EvidenceNull.Value);
        var noTarget = Change(healed, "target_enemy_key", new EvidenceText(""));
        ReportHitInput[][] transitions = [[one, noHp, anotherActor], [noHp, one, noTarget], [noTarget, two],
            [noHp], [Change(two,"target_actor_id",new EvidenceText("0")), one, anotherActor], [anotherActor, anotherActor], [], [one, two]];
        check(transitions.All(rows => Same(cache.Annotate(rows), rows)),
            "HP prefix retraction preserves missing observations, actor/template grouping, duplicate rows and unknown target semantics");

        LiveHitPreparationCache preparation = new();
        preparation.Begin(new object(), new Dictionary<string, EvidenceObject>());
        var writable = Obj("""{"details":{"sources":[{"value":1}]},"label":"old"}""");
        var published = preparation.Prepare(one, () => one with { Evidence = writable });
        ((Dictionary<string, EvidenceValue>)writable.Fields)["label"] = new EvidenceText("changed");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)((EvidenceArray)((EvidenceObject)writable.Get("details"))
            .Get("sources")).Items[0]).Fields)["value"] = new EvidenceInteger(99);
        preparation.Begin(new object(), new Dictionary<string, EvidenceObject>());
        var replacement = preparation.Prepare(one, () => one with
        {
            Evidence = Obj("""{"label":"new","details":{"sources":[{"value":2}]}}"""),
        });
        var copy = (EvidenceObject)EvidenceJson.Clone(published.Evidence);
        ((Dictionary<string, EvidenceValue>)copy.Fields)["details"] = EvidenceNull.Value;
        check(published.Evidence.Fields.Keys.SequenceEqual(["details", "label"])
            && EvidenceJson.PythonEquals(published.Evidence, Obj("""{"details":{"sources":[{"value":1}]},"label":"old"}"""))
            && EvidenceJson.PythonEquals(replacement.Evidence, Obj("""{"label":"new","details":{"sources":[{"value":2}]}}""")),
            "Published nested hit evidence remains isolated from input mutation, public copies and later preparation context resets");

        (long Observed, long Projected, long Retracted) AppendCost(int count)
        {
            var rows = Enumerable.Range(0, count + 1).Select(index => Change(one, "enemy_hp_after", new EvidenceInteger(100000 - index))).ToArray();
            LiveHitPreparationCache sized = new();
            sized.Annotate(rows[..count]);
            var observed = sized.ObservedHpHits; var written = sized.ProjectedHpHits; var undone = sized.RetractedHpHits;
            sized.Annotate(rows);
            return (sized.ObservedHpHits - observed, sized.ProjectedHpHits - written, sized.RetractedHpHits - undone);
        }
        check(AppendCost(8) == (1, 1, 0) && AppendCost(1024) == (1, 1, 0),
            "The same appended HP observation prepares one new row after either short or long completed history");
    }
}
