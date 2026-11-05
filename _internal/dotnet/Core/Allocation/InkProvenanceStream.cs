using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Allocation;

public sealed record InkProvenanceResult(IReadOnlyList<EvidenceObject> Hits, EvidenceObject Summary);
public sealed record InkTraceLine(BigInteger Number, string Text);

/// <summary>One ordered analysis owns this ledger. Releases keep source-time shares across accumulator resets.</summary>
public sealed class InkProvenanceStream
{
    public const string Buff = "buff_chr_0036_jsspsi_xianjing_inkhurteffect";
    public const string Explosion = "chr_0036_jsspsi_normal_skill_inkmark_projhit";
    public const string Owner = "chr_0036_jsspsi";
    public const string Policy = "whole_ink_damage_log_zones_v1";
    private readonly bool profileVerified;
    private readonly Dictionary<(string Uid, BigInteger Line), Ledger> registered = [];
    private readonly Dictionary<string, List<Ledger>> byUid = new(StringComparer.Ordinal);
    private readonly Dictionary<EffectSignature, List<EvidenceObject>> observedSources = [];
    private readonly Dictionary<string, Release> releases = new(StringComparer.Ordinal);
    private readonly Dictionary<string, BigInteger> counters = new(StringComparer.Ordinal);
    private Preparation? preparation;

    private sealed record Pending(BigInteger Sequence, BigInteger Tick, EvidenceObject? Source);
    private sealed record Preparation(Ledger Ledger, BigInteger Sequence, BigInteger Tick, List<Projectile> Projectiles, Release Frozen);
    private sealed class Projectile(string? id)
    {
        public string? Id = id;
        public string? Cast;
        public BigInteger? Sequence;
    }
    private sealed class Ledger(EvidenceObject record, string session)
    {
        public EvidenceObject Record = record;
        public readonly string Session = session;
        public double Total;
        public Dictionary<string, double> Shares = new(StringComparer.Ordinal);
        public Pending? Pending;
        public BigInteger LastSequence = -1;
        public readonly Dictionary<BigInteger, IReadOnlyDictionary<string, string>> Seen = [];
        public readonly HashSet<BigInteger> UsedHits = [];
        public HashSet<string> Reasons = new(StringComparer.Ordinal);
        public List<EvidenceValue> SourceHits = [];
        public void Reset()
        {
            Total = 0; Shares = new(StringComparer.Ordinal); Pending = null;
            Reasons = new(StringComparer.Ordinal); SourceHits = [];
        }
        public Release Freeze(string projectile, BigInteger sequence, string binding) => new()
        {
            Projectile = projectile, Sequence = sequence, Binding = binding, Session = Session,
            Target = Str(Record.Get("target_actor_id")), Source = Str(Record.Get("source_actor_id")), Uid = Str(Record.Get("uid")),
            Total = Total, Shares = new(Shares, StringComparer.Ordinal), Reasons = new(Reasons, StringComparer.Ordinal), SourceHits = [.. SourceHits],
        };
    }
    private sealed class Release
    {
        public required string Projectile, Binding, Session, Target, Source, Uid;
        public required BigInteger Sequence;
        public required double Total;
        public required Dictionary<string, double> Shares;
        public required HashSet<string> Reasons;
        public required List<EvidenceValue> SourceHits;
        public string? Cast;
        public bool Consumed;
    }
    private static string Str(EvidenceValue value) => PythonDisplay.String(value);
    private static EvidenceObject Copy(EvidenceObject value) => (EvidenceObject)BuffEvidence.Clone(value);
    private static EvidenceObject ObjectOrEmpty(EvidenceValue value) => !Truth(value) ? BuffEvidence.Object()
        : value as EvidenceObject ?? throw new InvalidDataException("Ink evidence must be an object");
    private static bool Is(EvidenceObject value, string key, string text) => value.Get(key) is EvidenceText item && item.Value == text;
    private static bool Truth(EvidenceValue value) => CatalogValues.Truth(value);
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => value is EvidenceArray array ? array.Items : [];
    private static BigInteger? Integer(EvidenceValue value)
    {
        try { return EffectIdentity.Integer(value); }
        catch (Exception error) when (error is InvalidCastException or FormatException or OverflowException) { return null; }
    }
    private static double? Number(EvidenceValue value)
    {
        try { var number = EffectIdentity.Float(value); return double.IsFinite(number) ? number : null; }
        catch (Exception error) when (error is InvalidCastException or FormatException or OverflowException) { return null; }
    }
    private static double? Number(string? value) => value is null ? null : Number(new EvidenceText(value));
    private static bool Close(double? a, double? b, double relative = 1e-5, double absolute = 2e-5) => a is double x && b is double y
        && (x == y || double.IsFinite(x) && double.IsFinite(y) && Math.Abs(x - y) <= Math.Max(absolute, relative * Math.Max(Math.Abs(x), Math.Abs(y))));
    private static void Add(Dictionary<string, double> values, string key, double amount) => values[key] = values.GetValueOrDefault(key) + amount;
    private static void Set(EvidenceObject value, string key, EvidenceValue item) => ((Dictionary<string, EvidenceValue>)value.Fields)[key] = item;
    private static EvidenceObject Shares(IReadOnlyDictionary<string, double> values) => new(values.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceReal(pair.Value), StringComparer.Ordinal));
    private void Count(string key) => counters[key]++;
    private EvidenceObject Summary()
    {
        var fields = counters.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceInteger(pair.Value), StringComparer.Ordinal);
        fields["policy"] = new EvidenceText(Policy);
        return new(fields);
    }

    public InkProvenanceStream(IReadOnlyDictionary<string, EvidenceObject> roots)
    {
        profileVerified = VerifyProfile(roots.GetValueOrDefault(Buff));
        Reset();
    }

    public void Reset()
    {
        registered.Clear(); byUid.Clear(); observedSources.Clear(); releases.Clear(); preparation = null; counters.Clear();
        foreach (var key in new[] { "explosions", "resolved", "partial", "unresolved", "paired_records", "unpaired_records" }) counters[key] = 0;
    }

    public static bool VerifyProfile(EvidenceObject? root)
    {
        Dictionary<BigInteger, List<EvidenceObject>> actions = [];
        void Visit(EvidenceValue? value, bool enabled)
        {
            if (value is EvidenceObject node)
            {
                enabled = enabled && (!node.Fields.ContainsKey("serverActionIndex") || node.Get("isEnable") is EvidenceBoolean { Value: true });
                if (enabled && node.Get("serverActionIndex") is EvidenceInteger index)
                {
                    if (!actions.TryGetValue(index.Value, out var entries)) actions[index.Value] = entries = [];
                    entries.Add(node);
                }
                foreach (var child in node.Fields.Values) Visit(child, enabled);
            }
            else if (value is EvidenceArray array) foreach (var child in array.Items) Visit(child, enabled);
        }
        Visit(root, true);
        bool Exact(int index, string kind, params (string Key, string Value)[] fields) => actions.TryGetValue(index, out var nodes) && nodes.Count == 1
            && Is(nodes[0], "$type", "Beyond.Gameplay.Core." + kind + ".Data") && fields.All(pair => Is(nodes[0], pair.Key, pair.Value));
        bool Operand(int index, string key, string name)
        {
            var operand = ObjectOrEmpty(actions[index][0].Get(key));
            return operand.Get("useBlackboardKey") is EvidenceBoolean { Value: true } && Is(operand, "blackboardKey", name);
        }
        return Exact(45, "SaveDamageContext", ("saveTo", "ink_damage"), ("valueType", "RealValue"))
            && Exact(46, "SimpleCalcBBAction", ("key", "ink_damage2"), ("operation", "Multiply"))
            && Exact(47, "SimpleCalcBBAction", ("key", "EntityBB_ink_damage"), ("operation", "Add"))
            && Exact(14, "LaunchProjectile") && Exact(15, "ModifyDynamicBlackboard", ("key", "EntityBB_ink_damage"), ("operation", "Assign"))
            && Operand(46, "value1", "ink_damage") && Operand(46, "value2", "ink_damage_rate")
            && Operand(47, "value1", "EntityBB_ink_damage") && Operand(47, "value2", "ink_damage2")
            && Number(ObjectOrEmpty(actions[15][0].Get("value")).Get("value")) == 0;
    }

    internal static Dictionary<string, double>? RecordWeights(EvidenceObject source, double increment)
    {
        var shares = source.Get("rdps_contributions") as EvidenceObject ?? BuffEvidence.Object();
        var basis = EffectIdentity.Float(PythonNumericSum.Sum(shares.Fields.Values));
        var owner = Str(source.Fields["character_key"]);
        var baseline = shares.Fields.TryGetValue(owner, out var own) ? EffectIdentity.Float(own) : 0;
        var raw = Math.Abs(EffectIdentity.Float(CatalogValues.Or(source.Get("packet_final_value"), new EvidenceInteger(0))));
        if (source.Get("_ink_allocation") is not EvidenceNull || raw <= 0 || increment <= 0 || baseline <= 0 || basis < baseline || !double.IsFinite(basis)) return null;
        Dictionary<string, double> weights = new(StringComparer.Ordinal) { [Owner] = PythonMath.LogOnePlus(increment / raw) };
        var pool = basis - baseline;
        if (pool > 0)
        {
            var externalLog = Math.Log(basis) - Math.Log(baseline);
            foreach (var (key, value) in shares.Fields)
            {
                var credit = EffectIdentity.Float(value);
                if (key != owner && credit > 0) Add(weights, key, externalLog * credit / pool);
            }
        }
        return weights.Values.All(double.IsFinite) ? weights : null;
    }

    private void Register(IReadOnlyList<EvidenceObject> records)
    {
        foreach (var record in records)
        {
            if (!Is(record, "event_key", Buff)) continue;
            var sessions = Items(record.Get("packet_creation_contexts")).Cast<EvidenceObject>().Select(row => row.Get("session_id")).ToArray();
            var distinct = sessions.DistinctBy(value => EvidenceJsonSignature.Sorted(value)).ToArray();
            if (distinct.Length != 1 || distinct[0] is EvidenceNull || !Is(record, "source_character_key", Owner)
                || !Truth(record.Get("source_actor_id")) || !Truth(record.Get("target_actor_id")) || Truth(record.Get("rdps_live_identity_conflict"))) continue;
            var key = (Str(record.Get("uid")), Integer(record.Get("line_no")) ?? throw new InvalidDataException("Ink record needs a line number"));
            if (registered.TryGetValue(key, out var existing)) existing.Record = Copy(record);
            else
            {
                var ledger = new Ledger(Copy(record), Str(distinct[0])); registered[key] = ledger;
                if (!byUid.TryGetValue(key.Item1, out var ledgers)) byUid[key.Item1] = ledgers = [];
                ledgers.Add(ledger);
            }
        }
    }

    private Ledger? Bind(string? uid, string? owner, BigInteger line)
    {
        if (uid is null || !byUid.TryGetValue(uid, out var rows)) return null;
        var candidates = rows.Where(state => Str(state.Record.Get("target_actor_id")) == owner
            && Integer(state.Record.Get("line_no")) < line
            && (!Truth(state.Record.Get("end_line_no")) || line < Integer(state.Record.Get("end_line_no")))).Take(2).ToArray();
        return candidates.Length == 1 ? candidates[0] : null;
    }

    /// <summary>Inputs are copied at the owner boundary. Returned snapshots cannot mutate the continuing ledger.</summary>
    public InkProvenanceResult Advance(IEnumerable<InkTraceLine> lines, IReadOnlyList<EvidenceObject> hits, IReadOnlyList<EvidenceObject> records)
        => AdvanceCore(lines.Select(line => (line.Number, (object)line)), hits, records);

    public InkProvenanceResult AdvanceEvents(IEnumerable<(BigInteger EvidenceIndex, TraceEvent Event)> events, IReadOnlyList<EvidenceObject> hits, IReadOnlyList<EvidenceObject> records)
        => AdvanceCore(events.Select(row => (row.EvidenceIndex, (object)row.Event)), hits, records);

    public InkProvenanceResult AdvanceObservations(IEnumerable<InkObservation> observations, IReadOnlyList<EvidenceObject> hits, IReadOnlyList<EvidenceObject> records)
        => AdvanceCore(observations.Select(row => (row.Number, (object)row)), hits, records);

    internal InkProvenanceResult AdvanceOwnedObservations(IEnumerable<InkObservation> observations, IReadOnlyList<EvidenceObject> hits, IReadOnlyList<EvidenceObject> records)
        => AdvanceCore(observations.Select(row => (row.Number, (object)row)), hits, records, ownsHits: true);

    private InkProvenanceResult AdvanceCore(IEnumerable<(BigInteger Number, object Input)> inputs, IReadOnlyList<EvidenceObject> hits, IReadOnlyList<EvidenceObject> records, bool ownsHits = false)
    {
        Register(records);
        var owned = ownsHits ? hits.Select(hit => Is(hit,"skill_key",Explosion) ? FrozenEvidence.OwnedMutableRoot(hit) : hit).ToArray()
            : hits.Select(Copy).ToArray();
        var byLine = new Dictionary<BigInteger, EvidenceObject>();
        foreach (var hit in owned) byLine[Integer(hit.Fields["line_no"])!.Value] = hit;
        foreach (var (number, input) in inputs)
        {
            if (byLine.TryGetValue(number, out var hit))
            {
                if (Is(hit, "skill_key", Explosion)) AllocateExplosion(hit);
                var key = new EffectSignature([hit.Get("packet_session_id"), new EvidenceText(Str(hit.Get("target_actor_id"))), hit.Get("client_tick_ms"), hit.Get("packet_seq_id")]);
                if (!observedSources.TryGetValue(key, out var sources)) observedSources[key] = sources = [];
                sources.Add((EvidenceObject)FrozenEvidence.Capture(hit));
                continue;
            }
            Consume(input switch
            {
                InkTraceLine line => InkObservation.FromLegacy(line),
                TraceEvent item => InkObservation.FromEvent(number, item),
                InkObservation observation => observation,
                _ => throw new InvalidDataException("Expected ink observation"),
            });
        }
        return new(owned, Summary());
    }

    public static InkProvenanceResult Apply(string text, IReadOnlyList<EvidenceObject> hits, IReadOnlyList<EvidenceObject> records,
        IReadOnlyDictionary<string, EvidenceObject> roots)
    {
        if (!hits.Any(hit => Is(hit, "skill_key", Explosion))) return new(hits.Select(Copy).ToArray(), BuffEvidence.Object());
        return new InkProvenanceStream(roots).Advance(PythonTextLines.Split(text).Select((line, index) => new InkTraceLine(index + 1, line)), hits, records);
    }

    public static InkProvenanceResult Apply(InkObservationInput input, IReadOnlyList<EvidenceObject> hits,
        IReadOnlyList<EvidenceObject> records, IReadOnlyDictionary<string, EvidenceObject> roots)
    {
        if (!hits.Any(hit => Is(hit, "skill_key", Explosion))) return new(hits.Select(Copy).ToArray(), BuffEvidence.Object());
        return new InkProvenanceStream(roots).AdvanceObservations(input.After(), hits, records);
    }

    private void Fail(EvidenceObject hit, string reason)
    {
        var shares = BuffEvidence.Object((Str(hit.Fields["character_key"]), new EvidenceReal(EffectIdentity.Float(hit.Fields["hit_value"]))));
        Set(hit, "_ink_allocation", shares); Set(hit, "rdps_contributions", Copy(shares));
        Set(hit, "ink_provenance", BuffEvidence.Object(("status", new EvidenceText("unresolved")), ("reason", new EvidenceText(reason))));
        Set(hit, "rdps_unresolved_effect_conditions", new EvidenceBoolean(true)); Count("unresolved");
    }

    private void AllocateExplosion(EvidenceObject hit)
    {
        Count("explosions");
        releases.TryGetValue(Str(hit.Get("event_owner_id")), out var release);
        var operand = ObjectOrEmpty(ObjectOrEmpty(ObjectOrEmpty(hit.Get("damage_calculation")).Get("atkCalculation")).Get("value"));
        if (!profileVerified || !Is(operand, "blackboardKey", "EntityBB_ink_damage") || operand.Get("useBlackboardKey") is not EvidenceBoolean { Value: true })
            Fail(hit, "typed_ink_formula_unverified");
        else if (release is null) Fail(hit, "missing_ink_projectile_ledger");
        else if (!Is(hit, "packet_session_id", release.Session) || release.Target != Str(hit.Get("target_actor_id"))
            || release.Source != Str(hit.Get("source_actor_id")) || release.Cast is not null && release.Cast != Str(hit.Get("event_inst_id"))
            || hit.Get("packet_seq_id") is EvidenceNull || EffectIdentity.CompareKeys(hit.Get("packet_seq_id"), new EvidenceInteger(release.Sequence)) <= 0) Fail(hit, "ink_projectile_context_mismatch");
        else if (release.Consumed) Fail(hit, "ink_projectile_already_consumed");
        else if (release.Reasons.Overlaps(["duplicate_projectile_release", "conflicting_ink_operation", "out_of_order_ink_operation", "invalid_ink_accumulator",
            "ink_operation_context_mismatch", "invalid_ink_operation_identity", "ink_operation_session_mismatch", "missing_ink_operation_identity"])) Fail(hit, "invalid_ink_ledger");
        else if (release.Total <= 0 || !Close(Math.Abs(EffectIdentity.Float(CatalogValues.Or(hit.Get("packet_final_value"), new EvidenceInteger(0)))), release.Total))
            Fail(hit, "ink_explosion_amount_mismatch");
        else
        {
            release.Consumed = true;
            var total = PythonFloatSum.Sum(release.Shares.Values);
            if (!Close(total, release.Total)) { Fail(hit, "ink_ledger_not_conserved"); return; }
            var amount = EffectIdentity.Float(hit.Fields["hit_value"]);
            var shares = Shares(release.Shares.Where(pair => pair.Value > 0).ToDictionary(pair => pair.Key, pair => pair.Value * amount / total));
            Set(hit, "rdps_contributions", shares); Set(hit, "_ink_allocation", Copy(shares));
            var reasons = release.Reasons.Order(PythonDisplay.CodePointComparer).Select(value => (EvidenceValue)new EvidenceText(value)).ToArray();
            var status = reasons.Length > 0 ? "partial" : "resolved";
            Set(hit, "ink_provenance", BuffEvidence.Object(("status", new EvidenceText(status)), ("policy", new EvidenceText(Policy)),
                ("buff_uid", new EvidenceText(release.Uid)), ("projectile_id", new EvidenceText(release.Projectile)), ("binding", new EvidenceText(release.Binding)),
                ("recorded_total", new EvidenceReal(release.Total)), ("source_hits", new EvidenceArray(release.SourceHits.ToArray())), ("reasons", new EvidenceArray(reasons))));
            if (reasons.Length > 0) Set(hit, "rdps_unresolved_effect_conditions", new EvidenceBoolean(true));
            Count(status);
        }
    }

    private void Consume(InkObservation input)
    {
        if (input.Kind == "release" && profileVerified)
        {
            try
            {
                var item = input.Release as EvidenceObject;
                if (item is null) return;
                var state = Bind((item.Get("buff_uid") as EvidenceText)?.Value, (item.Get("owner_id") as EvidenceText)?.Value, input.Number);
                if (state is null || !EvidenceJson.PythonEquals(item.Get("schema_version"), new EvidenceInteger(1)) || !Is(item, "session_id", state.Session)
                    || !Is(item, "template_key", Buff) || !EvidenceJson.PythonEquals(item.Get("action_id"), new EvidenceInteger(14))
                    || !Is(item, "source_actor_id", Str(state.Record.Get("source_actor_id"))) || item.Get("operation_seq") is not EvidenceInteger sequence || sequence.Value <= state.LastSequence) return;
                var projectile = ((EvidenceText)item.Fields["projectile_id"]).Value;
                if (releases.TryGetValue(projectile, out var release)) release.Reasons.Add("duplicate_projectile_release");
                else releases[projectile] = state.Freeze(projectile, sequence.Value, "packet_projectile_id");
            }
            catch (Exception error) when (error is FormatException or InvalidCastException or KeyNotFoundException or InvalidDataException) { }
            return;
        }
        var fields = input.Fields;
        string? Get(string key) => fields.GetValueOrDefault(key);
        if (input.Kind == "mapping" && preparation is not null)
        {
            if (Get("source") == "launch_projectile" && Get("template") == Owner) preparation.Projectiles.Add(new(Get("id")));
            return;
        }
        if (input.Kind == "cast" && preparation is not null)
        {
            foreach (var candidate in preparation.Projectiles)
                if (Get("ownerId") == candidate.Id && Get("skill") == Explosion && TraceFields.OptionalInteger(Get("startMs")) == preparation.Tick)
                { candidate.Cast = Get("inst"); candidate.Sequence = TraceFields.OptionalInteger(Get("seq")); }
            return;
        }
        if (!profileVerified || input.Kind != "operation" || Get("skill") != Buff) return;
        var ledger = Bind(Get("inst"), Get("ownerId"), input.Number);
        if (ledger is null) return;
        if (TraceFields.OptionalInteger(Get("seq")) is not BigInteger seq || TraceFields.OptionalInteger(Get("tick")) is not BigInteger tick || TraceFields.OptionalInteger(Get("actionId")) is not BigInteger action)
        { ledger.Reasons.Add("missing_ink_operation_identity"); return; }
        if (input.IdentityPresent)
        {
            try
            {
                var id = !input.InvalidIdentity ? input.Identity as EvidenceObject
                    ?? throw new InvalidDataException("Ink identity must be an object")
                    : throw new InvalidDataException("Invalid ink identity");
                bool Eq(string key, BigInteger value) => EvidenceJson.PythonEquals(id.Get(key), new EvidenceInteger(value));
                if (!Eq("schemaVersion", 1) || !(Eq("ownerType", 1) || Is(id, "ownerType", "1")) || !Eq("triggerType", 0) || !Eq("actionType", 7)
                    || !Is(id, "actionRuntimeCase", "modify_dynamic_blackboard_action") || !Is(id, "operationPayloadCase", "trigger_action_op_data")
                    || !Is(id, "sessionId", ledger.Session) || !Eq("operationSeq", seq) || !Is(id, "ownerId", Get("ownerId")!)
                    || !Is(id, "environmentInstId", Get("inst")!) || !Is(id, "templateType", "Buff") || !Eq("actionId", action)
                    || Str(id.Get("clientTickMs")) != tick.ToString(System.Globalization.CultureInfo.InvariantCulture))
                { ledger.Reasons.Add("ink_operation_context_mismatch"); ledger.Pending = null; return; }
            }
            catch (Exception error) when (error is FormatException or InvalidCastException or InvalidDataException)
            { ledger.Reasons.Add("invalid_ink_operation_identity"); return; }
        }
        else if (Get("packetSessionId") is string session && session != ledger.Session) { ledger.Reasons.Add("ink_operation_session_mismatch"); return; }
        if (ledger.Seen.TryGetValue(seq, out var previous))
        {
            if (previous.Count != fields.Count || previous.Any(pair => !fields.TryGetValue(pair.Key, out var value) || value != pair.Value)) ledger.Reasons.Add("conflicting_ink_operation");
            return;
        }
        ledger.Seen[seq] = fields;
        if (seq <= ledger.LastSequence) { ledger.Reasons.Add("out_of_order_ink_operation"); return; }
        ledger.LastSequence = seq;
        if (action == 45)
        {
            var value = Number(Get("value"));
            var key = new EffectSignature([new EvidenceText(ledger.Session), new EvidenceText(Get("ownerId")!), new EvidenceInteger(tick), new EvidenceInteger(seq - 1)]);
            var matched = (observedSources.GetValueOrDefault(key) ?? []).Where(source => value is not null && source.Get("packet_final_value") is not EvidenceNull
                && Close(Math.Abs(EffectIdentity.Float(source.Get("packet_final_value"))), value, 1e-8, 1e-6)
                && !ledger.UsedHits.Contains(Integer(source.Fields["line_no"])!.Value)).Take(2).ToArray();
            var source = matched.Length == 1 ? matched[0] : null;
            ledger.Pending = new(seq, tick, source);
            if (source is not null) { ledger.UsedHits.Add(Integer(source.Fields["line_no"])!.Value); Count("paired_records"); }
            else Count("unpaired_records");
        }
        else if (action == 47 && Get("key") == "EntityBB_ink_damage") Accumulate(ledger, seq, tick, Number(Get("valueA")), Number(Get("valueB")), Number(Get("final")));
        else if (action == 66 && Get("key") == "EntityBB_ink_damage")
        {
            if (Number(Get("valueA")) is double prior && Number(Get("final")) is double final && final >= prior && Close(prior, ledger.Total))
            { Add(ledger.Shares, Owner, Math.Max(0, final - ledger.Total)); ledger.Total = final; ledger.Reasons.Add("kill_bonus_provenance_unresolved"); }
        }
        else if (action == 13) preparation = new(ledger, seq, tick, [], ledger.Freeze("", seq, "legacy_typed_release_block"));
        else if (action == 15 && Number(Get("value")) == 0)
        {
            if (preparation is { } prepared && ReferenceEquals(prepared.Ledger, ledger) && prepared.Tick == tick && prepared.Projectiles.Count == 1)
            {
                var projectile = prepared.Projectiles[0];
                if (!string.IsNullOrEmpty(projectile.Cast) && prepared.Sequence < (projectile.Sequence ?? 0) && (projectile.Sequence ?? 0) < seq
                    && projectile.Id is not null && !releases.ContainsKey(projectile.Id))
                { prepared.Frozen.Projectile = projectile.Id; prepared.Frozen.Cast = projectile.Cast; releases[projectile.Id] = prepared.Frozen; }
            }
            preparation = null; ledger.Reset();
        }
    }

    private static void Accumulate(Ledger state, BigInteger sequence, BigInteger tick, double? previous, double? increment, double? final)
    {
        if (previous is not double prior || increment is not double added || final is not double result || Math.Min(Math.Min(prior, added), result) < 0
            || !Close(prior + added, result) || prior < state.Total && !Close(prior, state.Total))
        { state.Reasons.Add("invalid_ink_accumulator"); state.Pending = null; return; }
        if (!Close(prior, state.Total))
        { Add(state.Shares, Owner, Math.Max(0, prior - state.Total)); state.Total = prior; state.Reasons.Add("unobserved_ink_accumulation"); }
        var delta = Math.Max(0, result - state.Total);
        var pending = state.Pending;
        var source = pending is not null && pending.Tick == tick && sequence - pending.Sequence >= 1 && sequence - pending.Sequence <= 2 ? pending.Source : null;
        var weights = source is null ? null : RecordWeights(source, added);
        if (weights is null || PythonFloatSum.Sum(weights.Values) <= 0)
        { Add(state.Shares, Owner, delta); state.Reasons.Add(source is null ? "unpaired_ink_source_hit" : "source_hit_attribution_unavailable"); }
        else
        {
            var total = PythonFloatSum.Sum(weights.Values);
            foreach (var (key, value) in weights) Add(state.Shares, key, delta * value / total);
            state.SourceHits.Add(source!.Fields["seq"]);
            if (Truth(source.Get("rdps_unresolved_effect_conditions"))) state.Reasons.Add("source_hit_attribution_unresolved");
        }
        state.Total = result; state.Pending = null;
    }
}
