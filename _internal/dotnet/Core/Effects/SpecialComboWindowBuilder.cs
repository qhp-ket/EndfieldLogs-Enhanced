using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

public sealed record SpecialComboWindowResult(IReadOnlyList<EvidenceObject> Hits, IReadOnlyList<EvidenceObject> Windows);

/// <summary>Credit only the modifier on the exact hit and its two proven forwarding origins.</summary>
public sealed class SpecialComboWindowBuilder(IReadOnlyDictionary<string, EvidenceObject> roots,
    IReadOnlyDictionary<string, string> numbers, EffectApproval approval)
{
    private readonly Lazy<double?> factor = new(() => ComboResourceContract.Resolve(roots));
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static EvidenceText Text(string value) => new(value);
    private static string String(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, Text("")));
    private static bool Same(EvidenceValue left, EvidenceValue right) => EvidenceJson.PythonEquals(left, right);
    private static bool Is(EvidenceObject value, string key, string expected) => value.Get(key) is EvidenceText text && text.Value == expected;
    private static bool Truth(EvidenceValue value) => CatalogValues.Truth(value);
    private static EvidenceObject Obj(EvidenceValue value) => value as EvidenceObject ?? throw new InvalidDataException("Expected combo evidence object");
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([])));
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => Items(value).Select(Obj);
    private static EvidenceArray Array(IEnumerable<EvidenceValue> values) => new(values.ToArray());
    private static bool PacketId(EvidenceValue value, bool bounded = true) => value is EvidenceText text && Regex.IsMatch(text.Value, @"\A[1-9]\d*\z")
        && (!bounded || BigInteger.Parse(text.Value) < BigInteger.One << 64);
    private static (BigInteger Time, BigInteger Line)? Point(EvidenceValue time, EvidenceValue line) => time is EvidenceInteger t && line is EvidenceInteger l ? (t.Value, l.Value) : null;

    public SpecialComboWindowResult Build(IReadOnlyList<EvidenceObject> sourceHits, IReadOnlyList<EvidenceObject> records)
        => BuildCore(sourceHits, records, ownsHits: false);

    internal SpecialComboWindowResult BuildOwned(IReadOnlyList<EvidenceObject> sourceHits, IReadOnlyList<EvidenceObject> records)
        => BuildCore(sourceHits, records, ownsHits: true);

    private SpecialComboWindowResult BuildCore(IReadOnlyList<EvidenceObject> sourceHits, IReadOnlyList<EvidenceObject> records, bool ownsHits)
    {
        var hits = ownsHits ? sourceHits.ToArray() : sourceHits.Select(hit => (EvidenceObject)BuffEvidence.Clone(hit)).ToArray();
        List<EvidenceObject> windows = [];
        if (factor.Value is not double skillFactor) return new(hits, windows);
        var byUid = records.Where(record => String(record.Get("event_key")) is ComboResourceContract.Trigger or ComboResourceContract.Imbue or ComboResourceContract.Modifier)
            .GroupBy(record => String(record.Get("uid"))).ToDictionary(group => group.Key, group => group.ToArray(), StringComparer.Ordinal);
        for (var hitIndex = 0; hitIndex < hits.Length; hitIndex++)
        {
            var hit = hits[hitIndex];
            var handles = Items(Obj(CatalogValues.Or(hit.Get("packet_modifier_handles"), Empty)).Get("attacker")).OfType<EvidenceObject>()
                .Where(handle => byUid.ContainsKey(String(handle.Get("buff_inst_id")))).GroupBy(handle => String(handle.Get("buff_inst_id")));
            foreach (var handleGroup in handles)
            {
                var uid = handleGroup.Key;
                if (!byUid[uid].Any(row => Is(row, "event_key", ComboResourceContract.Modifier))) continue;
                string? rejection = null;
                var session = hit.Get("packet_session_id");
                var sequence = hit.Get("packet_seq_id") as EvidenceInteger;
                var stamp = Point(hit.Get("ts_ms"), hit.Get("line_no"));
                if (session is not EvidenceText { Value.Length: > 0 } || sequence is null || sequence.Value.Sign < 0 || stamp is null || stamp.Value.Line <= 0)
                    rejection = "missing_combo_hit_identity";
                else if (handleGroup.Any(row => row.Get("index") is not EvidenceInteger { Value.IsZero: true })
                    || handleGroup.Select(EvidenceJsonSignature.Sorted).Distinct(StringComparer.Ordinal).Count() != 1)
                    rejection = "conflicting_combo_modifier_handle";
                var mask = hit.Get("damage_decorate_mask");
                EvidenceValue scopeSource = Text("observed_damage_decorate_mask");
                if (mask is EvidenceNull)
                {
                    mask = hit.Get("static_damage_decorate_mask");
                    scopeSource = hit.Get("static_damage_decorate_mask_source");
                    if (!Same(scopeSource, Text("current_typed_skill_or_buff_exact_unit_generation_only"))) mask = EvidenceNull.Value;
                }
                if (mask is not EvidenceInteger { Value.Sign: >= 0 } scopeMask || (scopeMask.Value & 0x300) == 0)
                    rejection ??= "unresolved_or_inapplicable_combo_skill_scope";
                List<EvidenceObject> chain = [], originsUsed = [], anchorsUsed = [];
                List<double> selected = [];
                var currentUid = uid;
                var expected = ComboResourceContract.Modifier;
                var point = stamp;
                foreach (var (parent, action) in new (string? Parent, int? Action)[] { (ComboResourceContract.Imbue, 0), (ComboResourceContract.Trigger, 4), (null, null) })
                {
                    if (rejection is not null) break;
                    var candidates = byUid.GetValueOrDefault(currentUid, []).Where(record =>
                    {
                        if (!Is(record, "event_key", expected)) return false;
                        var start = Point(record.Fields.GetValueOrDefault("ts_ms", record.Get("start_ts_ms")), record.Fields.GetValueOrDefault("line_no", new EvidenceInteger(0)));
                        if (start is null || point!.Value.CompareTo(start.Value) < 0) return false;
                        return !new[] { ("end_ts_ms", "end_line_no"), ("snapshot_end_ts_ms", "snapshot_end_line_no") }.Any(cutoff =>
                            record.Get(cutoff.Item1) is EvidenceInteger end && (point.Value.Time > end.Value
                                || point.Value.Time == end.Value && record.Get(cutoff.Item2) is EvidenceInteger line && point.Value.Line >= line.Value));
                    }).ToArray();
                    if (candidates is not [var record]) { rejection = "ambiguous_or_missing_combo_instance"; break; }
                    if (Truth(record.Get("rdps_live_identity_conflict")) || Truth(record.Get("rdps_dynamic_identity_conflict"))
                        || !Truth(record.Get("source_character_key")) || !Same(record.Get("target_actor_id"), hit.Get("source_actor_id"))
                        || !Same(record.Get("target_character_key"), hit.Get("character_key"))
                        || new[] { "uid", "source_actor_id", "target_actor_id" }.Any(key => !PacketId(record.Get(key)))
                        || chain.Count > 0 && (!Same(record.Get("source_actor_id"), chain[0].Get("source_actor_id"))
                            || !Same(record.Get("source_character_key"), chain[0].Get("source_character_key"))))
                    { rejection = "conflicting_combo_provider_or_recipient"; break; }
                    chain.Add(record);
                    if (parent is null) break;
                    List<EvidenceObject> origins = [];
                    foreach (var origin in Rows(record.Get("origin_observations")))
                    {
                        var declaredParent = origin.Get("templateStrId");
                        if (declaredParent is EvidenceNull or EvidenceText { Value: "" } && origin.Get("templateIntId") is EvidenceInteger number)
                            declaredParent = numbers.TryGetValue(CatalogValues.Text(number), out var name) ? Text(name) : EvidenceNull.Value;
                        else if (declaredParent is not EvidenceText { Value.Length: > 0 } || origin.Get("templateIntId") is not EvidenceNull)
                            declaredParent = EvidenceNull.Value;
                        if (origin.Get("_boundCreateRecord") is not EvidenceBoolean { Value: true } || !Same(declaredParent, Text(parent))
                            || !Is(origin, "buffUid", currentUid) || !Is(origin, "buffTemplate", expected)
                            || !Same(origin.Get("sourceActorId"), record.Get("source_actor_id")) || !Same(origin.Get("targetActorId"), record.Get("target_actor_id"))
                            || String(origin.Get("environmentType")).ToLowerInvariant() != "buff" || CatalogValues.Text(origin.Get("ownerType")) != "1"
                            || origin.Get("actionId") is not EvidenceInteger actionId || actionId.Value != action
                            || !Same(origin.Get("triggerType"), new EvidenceInteger(0)) || origin.Get("operationSeq") is not EvidenceInteger
                            || !PacketId(origin.Get("environmentInstId"), bounded: false))
                        { rejection = "invalid_combo_creation_origin"; break; }
                        origins.Add(origin);
                    }
                    var parentUids = origins.Select(row => String(row.Get("environmentInstId"))).Distinct(StringComparer.Ordinal).ToArray();
                    if (rejection is not null || origins.Count == 0 || parentUids.Length != 1)
                    { rejection ??= "missing_or_conflicting_combo_creation_origin"; break; }
                    var anchors = Rows(record.Get("creation_observations")).Where(row => Same(row.Get("sessionId"), session)
                        && Is(row, "buffUid", currentUid) && Is(row, "buffTemplate", expected)
                        && Same(row.Get("sourceActorId"), record.Get("source_actor_id")) && Same(row.Get("targetActorId"), record.Get("target_actor_id"))
                        && Is(row, "sourceEvent", "BattleOpTriggerAction") && row.Get("operationSeq") is EvidenceInteger seq && seq.Value <= sequence!.Value
                        && origins.Any(origin => Same(row.Get("operationSeq"), origin.Get("operationSeq")))).ToArray();
                    if (anchors.Length == 0 || anchors.Any(row => row.Get("assignedItems") is not EvidenceArray))
                    { rejection = "missing_combo_creation_parameters"; break; }
                    HashSet<double> rates = [];
                    foreach (var anchor in anchors)
                    {
                        var values = Items(anchor.Get("assignedItems")).OfType<EvidenceObject>().Where(row => Is(row, "target_key", "imbue_scale")).ToArray();
                        if (values.Length == 0 || values.Any(row => row.Get("use_direct_value") is not EvidenceBoolean { Value: true }
                                || Truth(row.Get("string_value")) || BuffEvidence.OptionalFloat(row.Get("numeric_value")) is null)
                            || Items(anchor.Get("bb_conflicts")).Any(key => Same(key, Text("imbue_scale")) || Same(key, Text("*"))))
                        { rejection = "invalid_combo_creation_rate"; break; }
                        rates.UnionWith(values.Select(row => BuffEvidence.OptionalFloat(row.Get("numeric_value"))!.Value));
                    }
                    if (rejection is not null || rates.Count != 1 || rates.Single() <= 0)
                    { rejection ??= "conflicting_combo_creation_rate"; break; }
                    selected.Add(rates.Single());
                    var points = anchors.Select(row => Point(row.Get("ts_ms"), row.Get("line_no"))).Distinct().ToArray();
                    if (points is not [{ } boundary]) { rejection = "ambiguous_combo_creation_boundary"; break; }
                    point = boundary;
                    currentUid = parentUids[0];
                    expected = parent;
                    originsUsed.AddRange(origins);
                    anchorsUsed.AddRange(anchors);
                }
                if (rejection is null && (chain.Count != 3 || selected.Count != 2 || selected[0] != selected[1])) rejection = "combo_forwarded_rate_conflict";
                if (rejection is null)
                {
                    var prior = Rows(chain[0].Get("enable_observations")).Where(row => row.Get("operationSeq") is EvidenceInteger seq && seq.Value <= sequence!.Value).ToArray();
                    if (prior.Length > 0)
                    {
                        var latest = prior.Max(row => ((EvidenceInteger)row.Get("operationSeq")).Value);
                        if (prior.Where(row => ((EvidenceInteger)row.Get("operationSeq")).Value == latest)
                            .Any(row => !Same(row.Get("enabled"), new EvidenceBoolean(true)))) rejection = "disabled_or_conflicting_combo_modifier";
                    }
                    else if (Truth(chain[0].Get("rdps_conflicting_enable_state"))) rejection = "disabled_or_conflicting_combo_modifier";
                }
                if (rejection is not null)
                {
                    var reasons = hit.Fields.TryGetValue("combo_unresolved_reasons", out var existing) ? Items(existing).ToList() : [];
                    reasons.Add(BuffEvidence.Object(("uid", Text(uid)), ("reason", Text(rejection))));
                    hit = new(new Dictionary<string, EvidenceValue>(hit.Fields, StringComparer.Ordinal)
                    {
                        ["rdps_unresolved_effect_conditions"] = new EvidenceBoolean(true), ["combo_unresolved_reasons"] = Array(reasons),
                    });
                    hits[hitIndex] = hit;
                    continue;
                }
                var projection = $"{ComboResourceContract.Trigger}::packet/{String(session)}/{sequence!.Value}/{stamp!.Value.Line}";
                var authorized = approval.Match(BuffEvidence.Object(("event_key", Text(projection)), ("source_character_key", chain[0].Get("source_character_key")),
                    ("target_character_key", hit.Get("character_key"))));
                if (authorized is null || !Truth(authorized.Get("_rdps_whitelist_keys"))
                    || !Rows(authorized.Get("effects")).Any(row => Is(row, "zone", "combo") && Is(row, "element", "all"))) continue;
                var scope = ((EvidenceInteger)mask).Value;
                var rate = selected[0] * ((scope & 0x100) != 0 ? skillFactor : 1);
                if (!double.IsFinite(rate) || rate <= 0) continue;
                windows.Add(new(new Dictionary<string, EvidenceValue>
                {
                    ["uid"] = Text(uid), ["start_ts_ms"] = new EvidenceInteger(stamp.Value.Time), ["end_ts_ms"] = new EvidenceInteger(stamp.Value.Time),
                    ["start_line_no"] = new EvidenceInteger(stamp.Value.Line), ["end_line_no"] = new EvidenceInteger(stamp.Value.Line + 1), ["line_no"] = new EvidenceInteger(stamp.Value.Line),
                    ["snapshot_update"] = new EvidenceBoolean(true), ["snapshot_end_ts_ms"] = new EvidenceInteger(stamp.Value.Time), ["snapshot_end_line_no"] = new EvidenceInteger(stamp.Value.Line + 1),
                    ["duration_ms"] = new EvidenceInteger(1), ["stacking_type"] = Obj(CatalogValues.Or(roots[ComboResourceContract.Modifier].Get("stackingSettings"), Empty)).Get("stackingType"),
                    ["stack_limit"] = EvidenceNull.Value, ["source_character_key"] = chain[0].Get("source_character_key"), ["source_character_name"] = chain[0].Get("source_character_name"),
                    ["source_actor_id"] = chain[0].Get("source_actor_id"), ["target_character_key"] = hit.Get("character_key"), ["target_character_name"] = CatalogValues.Or(hit.Get("character_name"), hit.Get("character_key")),
                    ["target_actor_id"] = hit.Get("source_actor_id"), ["target_player_key"] = hit.Get("character_key"), ["target_enemy_key"] = EvidenceNull.Value,
                    ["event_key"] = Text(projection), ["event_name"] = Text("连击增伤"), ["skill_family_key"] = EvidenceNull.Value,
                    ["zone_effects"] = new EvidenceArray([BuffEvidence.Object(("zone", Text("combo")), ("element", Text("all")), ("rate", new EvidenceReal(rate)),
                        ("external_rdps_allowed", new EvidenceBoolean(true)), ("rdps_whitelist_keys", Array(Items(authorized.Get("_rdps_whitelist_keys")))))]),
                    ["combo_rate_model"] = Text("exact_packet_modifier_and_creation_chain"), ["combo_imbue_scale"] = new EvidenceReal(selected[0]),
                    ["combo_skill_scope_mask"] = new EvidenceInteger(scope & 0x300), ["combo_skill_scope_source"] = scopeSource,
                    ["combo_source_uids"] = Array(chain.AsEnumerable().Reverse().Select(row => row.Get("uid"))),
                    ["combo_origins"] = Array(originsUsed.Select(row => BuffEvidence.Clone(row))), ["combo_creation_observations"] = Array(anchorsUsed.Select(row => BuffEvidence.Clone(row))),
                    ["combo_hit_identity"] = BuffEvidence.Object(("sessionId", session), ("operationSeq", sequence), ("lineNo", new EvidenceInteger(stamp.Value.Line)),
                        ("targetActorId", hit.Get("target_actor_id")), ("damageUnitIndex", hit.Get("damage_unit_index"))),
                }));
            }
        }
        return new(hits, windows);
    }
}
