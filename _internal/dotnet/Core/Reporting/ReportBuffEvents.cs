using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record ReportBuffEventProjection(IReadOnlyList<EvidenceObject> Records, IReadOnlyList<EvidenceObject> Events);

/// <summary>Full report descriptions, including effects excluded from allocation and packet boundaries.</summary>
public sealed class ReportBuffEvents(IReadOnlyDictionary<string, EvidenceObject> roots, BuffLabelCatalog labels,
    EffectSpecificationCatalog specifications, DynamicEffectSpecificationCatalog dynamics)
{
    public static ReportBuffEvents Load(ResourceFiles files)
    {
        var roots = new BuffRootCatalog(files).Roots;
        SkillResourceCatalog skills = new(files);
        var packets = PacketBuffCatalog.Load(files, skills);
        EffectApproval approval = new(EffectApprovalCatalog.Load(files), roots, skills.Buffs, skills.Skills);
        SemanticEffectCatalog semantics = new(roots, DamageZoneCatalog.Load(files), approval);
        EffectSpecificationCatalog specifications = new(approval, semantics, new(roots));
        PacketEffectDisplayCatalog display = new(packets, EnhancedChildEffectCatalog.Load(files));
        return new(roots, new(semantics, BuffDisplayClassification.Load(files, packets), display), specifications,
            new(approval, specifications, roots, packets));
    }

    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static EvidenceText TextValue(string text) => new(text);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, TextValue("")));
    private static EvidenceArray Array(IEnumerable<EvidenceValue> values) => new(values.ToArray());
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([])));
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => Items(value).Cast<EvidenceObject>();
    private static BigInteger Int(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static BigInteger? OptionalInt(EvidenceValue value) => value is EvidenceNull ? null : EffectIdentity.Integer(value);
    private static EvidenceValue Element(EvidenceObject effect) => CatalogValues.Or(effect.Get("element"), TextValue("all"));
    private static EvidenceText Time(BigInteger value) => TextValue(TraceFields.MillisecondTimeText((long)(value % 86400000))!);
    private static double Number(EvidenceValue value) => EffectIdentity.Float(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static double? OptionalNumber(EvidenceValue value)
    {
        try { return EffectIdentity.Float(value); }
        catch (Exception error) when (error is FormatException or InvalidCastException) { return null; }
    }
    private static string Fixed(double value) => double.IsFinite(value)
        ? value.ToString("F2", CultureInfo.InvariantCulture) : PythonDisplay.Float(value);
    private static string General(double value) => double.IsFinite(value)
        ? value.ToString("g6", CultureInfo.InvariantCulture) : PythonDisplay.Float(value);
    private static string Percent(double? value) => value is double number ? Fixed(number * 100) + "%" : "未确认";

    private static EffectSignature Identity(EvidenceObject row, bool record)
    {
        var uid = Text(row.Get("uid"));
        return uid.Length > 0 ? new([TextValue("uid"), TextValue(uid)])
            : new([TextValue("tuple"), row.Get("event_key"), row.Get("source_character_key"),
                record ? CatalogValues.Or(row.Get("target_character_key"), row.Get("target_enemy_key")) : row.Get("target_character_key"),
                new EvidenceInteger(Int(row.Get(record ? "ts_ms" : "start_ts_ms")))]);
    }

    public ReportBuffEventProjection Build(IReadOnlyList<EvidenceObject> source, IReadOnlyList<EvidenceObject> windows,
        BigInteger battleStartMs, BigInteger battleEndMs)
        => BuildCore(source, windows, battleStartMs, battleEndMs, ownsEvidence: false);

    internal ReportBuffEventProjection BuildOwned(IReadOnlyList<EvidenceObject> source, IReadOnlyList<EvidenceObject> windows,
        BigInteger battleStartMs, BigInteger battleEndMs, IReadOnlyDictionary<EvidenceObject, EffectRecordAnalysis>? analyses = null)
        => BuildCore(source, windows, battleStartMs, battleEndMs, ownsEvidence: true, analyses);

    private ReportBuffEventProjection BuildCore(IReadOnlyList<EvidenceObject> source, IReadOnlyList<EvidenceObject> windows,
        BigInteger battleStartMs, BigInteger battleEndMs, bool ownsEvidence, IReadOnlyDictionary<EvidenceObject, EffectRecordAnalysis>? analyses = null)
    {
        var included = windows.Select(window => Identity(window, false)).ToHashSet();
        List<EvidenceObject> records = [], events = [];
        foreach (var original in source)
        {
            var start = Int(original.Get("ts_ms"));
            var root = roots.GetValueOrDefault(Text(original.Get("event_key")));
            var end = BuffLifetime.EndAt(start, OptionalInt(original.Get("end_ts_ms")), OptionalInt(original.Get("raw_duration_ms")),
                battleEndMs, root?.Get("lifeType") is EvidenceText { Value: "Infinity" }, OptionalInt(original.Get("snapshot_end_ts_ms")));
            var prepared = analyses?.GetValueOrDefault(original);
            var description = prepared is null ? labels.Collect(original) : new BuffLabelsResult(original, prepared.Labels);
            var current = prepared is not null ? new RegistryEffectsResult(original, prepared.StaticEffects)
                : ownsEvidence ? specifications.CollectStaticOwned(description.Record) : specifications.CollectStatic(description.Record);
            var dynamic = prepared is not null ? new RegistryEffectsResult(original, prepared.DynamicEffects)
                : ownsEvidence ? dynamics.CollectOwned(current.Record) : dynamics.Collect(current.Record);
            var record = dynamic.Record;
            records.Add(record);
            var hasEffects = current.Effects.Count > 0 || dynamic.Effects.Count > 0;
            var selected = hasEffects && included.Contains(Identity(record, true));
            Dictionary<string, EvidenceValue> fields = new(StringComparer.Ordinal);
            foreach (var name in new[] { "line_no", "uid", "event_key", "raw_event_key", "packet_mapping", "source_character_key",
                "source_character_name", "source_skill_key", "source_skill_family_key", "raw_source", "target_enemy_key", "owner_raw",
                "target_actor_id", "source_actor_id", "source_weapon_template", "snapshot_end_ts_ms", "snapshot_end_line_no",
                "instance_start_line_no", "raw_duration_ms", "lifetime_mode", "lifetime_source" })
                fields[name] = BuffEvidence.Clone(record.Get(name));
            foreach (var name in new[] { "origin_observations", "enable_observations", "creation_observations", "repeated_creation_observations",
                "attribute_refresh_snapshots", "dynamic_bb_events", "attr_types", "attr_mods" })
                fields[name] = BuffEvidence.Clone(CatalogValues.Or(record.Get(name), new EvidenceArray([])));
            fields["status"] = TextValue(selected ? "included" : hasEffects ? "merged" : "filtered");
            fields["status_label"] = TextValue(selected ? "纳入" : hasEffects ? "合并/未参与窗口" : "过滤");
            fields["event_name"] = description.Labels.Count > 0 ? TextValue(string.Join(" / ", description.Labels)) : record.Get("event_key");
            fields["packet_classification"] = PacketBuffClassification.Classify(record);
            fields["semantic_candidates"] = new EvidenceArray([]);
            fields["target_character_key"] = CatalogValues.Or(record.Get("target_character_key"), record.Get("target_enemy_key"));
            fields["target_character_name"] = CatalogValues.Or(record.Get("target_character_name"), record.Get("target_enemy_name"));
            fields["target_player_key"] = record.Get("target_character_key");
            fields["start_ts_ms"] = new EvidenceInteger(start);
            fields["start_time"] = Time(start);
            fields["end_ts_ms"] = new EvidenceInteger(end);
            fields["end_time"] = Time(end);
            fields["start_ms_from_battle"] = new EvidenceInteger(start - battleStartMs);
            fields["end_ms_from_battle"] = new EvidenceInteger(end - battleStartMs);
            fields["duration_ms"] = new EvidenceInteger(BigInteger.Max(0, end - start));
            fields["raw_end_ts_ms"] = record.Get("end_ts_ms");
            fields["raw_end_time"] = record.Get("end_ts_ms") is EvidenceNull ? EvidenceNull.Value : Time(EffectIdentity.Integer(record.Get("end_ts_ms")));
            fields["snapshot_update"] = new EvidenceBoolean(CatalogValues.Truth(record.Get("snapshot_update")));
            fields["end_is_observation_boundary"] = new EvidenceBoolean(record.Get("end_ts_ms") is EvidenceNull
                && record.Get("snapshot_end_ts_ms") is EvidenceNull && record.Get("lifetime_mode") is EvidenceText { Value: "Infinity" });
            fields["end_source"] = TextValue(EvidenceJson.PythonEquals(record.Get("snapshot_end_ts_ms"), new EvidenceInteger(end)) ? "snapshot_update"
                : EvidenceJson.PythonEquals(record.Get("end_ts_ms"), new EvidenceInteger(end)) ? "buff_end" : "duration_or_capture_boundary");
            fields["overlaps_battle"] = new EvidenceBoolean(end >= battleStartMs && start <= battleEndMs);
            fields["bb_keys"] = Array(Items(record.Get("bb_keys")).Select(PythonDisplay.String).Distinct(StringComparer.Ordinal)
                .Order(PythonDisplay.CodePointComparer).Select(TextValue));
            fields["bb_values"] = BuffEvidence.Clone(CatalogValues.Or(record.Get("bb_values"), Empty));
            fields["zone_effects"] = Array(current.Effects);
            fields["dynamic_effects"] = Array(dynamic.Effects);
            fields["effect_segments"] = Array(Segments(start, end, current.Effects, dynamic.Effects));
            fields["effect_summary"] = Array(Summaries(current.Effects.Concat(dynamic.Effects)).Select(TextValue));
            fields["is_weapon_buff"] = new EvidenceBoolean(CatalogValues.Truth(record.Get("is_weapon_buff")));
            events.Add(new(fields));
        }
        return new(records, events.OrderBy(row => Int(row.Get("start_ts_ms"))).ThenBy(row => Int(row.Get("line_no"))).ToArray());
    }

    public static IReadOnlyList<string> Summaries(IEnumerable<EvidenceObject> effects)
    {
        List<string> result = [];
        HashSet<string> seen = new(StringComparer.Ordinal);
        foreach (var effect in effects)
        {
            var zone = Text(effect.Get("zone"));
            var element = PythonDisplay.String(Element(effect));
            var rate = OptionalNumber(effect.Get("rate") is EvidenceNull ? effect.Get("base_rate") : effect.Get("rate"));
            var prefix = BuffLabelCatalog.ZoneLabel(zone) + "/" + element + " ";
            string text;
            if (effect.Fields.ContainsKey("keyword_rate_snapshots"))
            {
                List<double?> rates = [rate];
                foreach (var row in Rows(effect.Get("keyword_rate_snapshots")).OrderBy(row => Int(row.Get("operation_seq"))).ThenBy(row => Int(row.Get("line_no"))))
                {
                    if (!EvidenceJson.PythonEquals(row.Get("session_id"), effect.Get("keyword_session_id"))) continue;
                    var next = row.Get("status") is EvidenceText { Value: "observed" } ? OptionalNumber(row.Get("rate_after")) : null;
                    if (next != rates[^1]) rates.Add(next);
                }
                text = prefix + string.Join(" -> ", rates.Select(Percent));
            }
            else if (zone == "res" && effect.Fields.ContainsKey("parameter_snapshots")) text = prefix + "按包内实际减抗点数更新";
            else if (zone == "res" && rate is double points) text = prefix + General(points) + " 点";
            else if (rate is null) text = prefix + "-";
            else
            {
                var delayed = OptionalNumber(effect.Get("delayed_add_rate")) is double positive && positive > 0 ? positive : 0;
                var delay = Number(effect.Get("delay_sec"));
                var tick = Number(effect.Get("tick_rate"));
                var maximum = Number(effect.Get("max_rate"));
                text = prefix + Percent(rate);
                if (delayed > 0 && delay > 0) text += " -> " + Percent(rate + delayed) + " @ " + General(delay) + "s";
                else if (tick > 0 && maximum > rate) text += " -> " + Percent(maximum) + " over time";
            }
            if (effect.Get("condition") is EvidenceObject condition)
            {
                var type = Text(condition.Get("type"));
                if (type is "target_hp_ratio_lte" or "target_hp_compare" && OptionalNumber(condition.Get("threshold")) is double threshold)
                {
                    var legacy = type == "target_hp_ratio_lte";
                    var compare = legacy ? "LE" : Text(condition.Get("compare"));
                    var op = compare switch { "LT" => "<", "LE" => "<=", "GT" => ">", "GE" => ">=", "EQ" => "=", "NE" => "!=", _ => "?" };
                    var value = legacy || condition.Get("is_ratio") is EvidenceBoolean { Value: true } ? Percent(threshold) : PythonDisplay.Float(threshold);
                    text += $" (target HP {op} {value})";
                }
                else if (type == "damage_type_in")
                {
                    var elements = Items(condition.Get("elements")).Where(item => Text(item).Length > 0).Select(PythonDisplay.String).ToArray();
                    if (elements.Length > 0) text += " (damage type: " + string.Join(", ", elements) + ")";
                }
            }
            if (seen.Add(text)) result.Add(text);
        }
        return result;
    }

    public static IReadOnlyList<EvidenceObject> Segments(BigInteger startMs, BigInteger endMs,
        IReadOnlyList<EvidenceObject> staticEffects, IReadOnlyList<EvidenceObject> dynamicEffects)
    {
        List<EvidenceObject> result = [];
        Dictionary<string, EvidenceValue> Segment(BigInteger start, BigInteger end, EvidenceObject effect, EvidenceValue rate, string mode) => new(StringComparer.Ordinal)
        {
            ["start_ts_ms"] = new EvidenceInteger(start), ["start_time"] = Time(start),
            ["end_ts_ms"] = new EvidenceInteger(end), ["end_time"] = Time(end),
            ["zone"] = TextValue(Text(effect.Get("zone"))), ["element"] = BuffEvidence.Clone(Element(effect)),
            ["rate"] = rate, ["mode"] = TextValue(mode),
        };
        foreach (var effect in staticEffects) result.Add(new(Segment(startMs, endMs, effect, BuffEvidence.Clone(effect.Get("rate")), "static")));
        foreach (var effect in dynamicEffects)
        {
            if (effect.Fields.ContainsKey("keyword_rate_snapshots"))
            {
                List<EvidenceObject> states = [new(new Dictionary<string, EvidenceValue>
                {
                    ["ts_ms"] = new EvidenceInteger(startMs), ["rate_after"] = effect.Get("base_rate"), ["status"] = TextValue("observed"),
                    ["operation_seq"] = EvidenceNull.Value, ["line_no"] = EvidenceNull.Value,
                })];
                BigInteger latest = -1;
                foreach (var row in Rows(effect.Get("keyword_rate_snapshots")).OrderBy(row => Int(row.Get("ts_ms")))
                    .ThenBy(row => Int(row.Get("line_no"))).ThenBy(row => Int(row.Get("operation_seq"))))
                {
                    var sequence = Int(row.Get("operation_seq"));
                    if (!EvidenceJson.PythonEquals(row.Get("session_id"), effect.Get("keyword_session_id")) || Int(row.Get("ts_ms")) > endMs || sequence < latest) continue;
                    latest = sequence;
                    states.Add(row);
                }
                for (var index = 0; index < states.Count; index++)
                {
                    var state = states[index];
                    var next = index + 1 < states.Count ? states[index + 1] : null;
                    var start = BigInteger.Max(startMs, Int(state.Get("ts_ms")));
                    var end = BigInteger.Min(endMs, next is null ? endMs : Int(next.Get("ts_ms")));
                    if (end < start) continue;
                    var value = state.Get("status") is EvidenceText { Value: "observed" } ? OptionalNumber(state.Get("rate_after")) : null;
                    var segment = Segment(start, end, effect, value is double rate ? new EvidenceReal(rate) : EvidenceNull.Value, "packet_keyword_update");
                    segment["operation_seq"] = state.Get("operation_seq");
                    segment["line_no"] = state.Get("line_no");
                    segment["end_operation_seq"] = next?.Get("operation_seq") ?? EvidenceNull.Value;
                    segment["end_line_no"] = next?.Get("line_no") ?? EvidenceNull.Value;
                    segment["session_id"] = effect.Get("keyword_session_id");
                    result.Add(new(segment));
                }
                continue;
            }
            if (effect.Fields.ContainsKey("parameter_snapshots"))
            {
                var states = Rows(effect.Get("parameter_snapshots")).ToArray();
                var keys = Items(effect.Get("parameter_keys")).Select(PythonDisplay.String).ToArray();
                for (var index = 0; index < states.Length; index++)
                {
                    var state = states[index];
                    var bb = state.Get("bb_values") as EvidenceObject ?? Empty;
                    var values = keys.Select(key => OptionalNumber(bb.Get(key))).ToArray();
                    var resolved = state.Get("status") is EvidenceText { Value: "attribute_parameters_observed" }
                        && values.Length > 0 && values.All(value => value is <= 0);
                    var start = BigInteger.Max(startMs, Int(state.Get("ts_ms")));
                    var end = BigInteger.Min(endMs, index + 1 < states.Length ? Int(states[index + 1].Get("ts_ms")) : endMs);
                    if (end < start) continue;
                    var total = resolved ? PythonFloatSum.Sum(values.Select(value => value!.Value)) : 0;
                    var segment = Segment(start, end, effect, resolved ? new EvidenceReal(-total) : EvidenceNull.Value, "packet_refresh");
                    segment["zone"] = TextValue("res");
                    segment["element"] = effect.Get("element");
                    segment["rate_unit"] = TextValue("resistance_points");
                    segment["operation_seq"] = state.Get("operation_seq");
                    result.Add(new(segment));
                }
                continue;
            }
            var baseRate = Number(effect.Get("base_rate"));
            var add = Number(effect.Get("delayed_add_rate"));
            var delay = new BigInteger(Math.Max(0, Number(effect.Get("delay_sec"))) * 1000);
            var tick = Number(effect.Get("tick_rate"));
            var maximum = Number(effect.Get("max_rate"));
            var points = Items(effect.Get("observed_points")).OfType<EvidenceArray>().Where(row => row.Items.Count == 2)
                .Select(row => (Time: EffectIdentity.Integer(row.Items[0]), Rate: EffectIdentity.Float(row.Items[1]))).ToArray();
            if (points.Length > 0)
            {
                for (var index = 0; index < points.Length; index++)
                {
                    var start = BigInteger.Max(startMs, points[index].Time);
                    var end = index + 1 < points.Length ? points[index + 1].Time : endMs;
                    if (end <= start) continue;
                    result.Add(new(Segment(start, BigInteger.Min(end, endMs), effect, new EvidenceReal(points[index].Rate), "dynamic_observed")));
                }
                continue;
            }
            if (add > 0 && delay > 0 && startMs + delay < endMs)
            {
                result.Add(new(Segment(startMs, startMs + delay, effect, new EvidenceReal(baseRate), "dynamic_before_delay")));
                result.Add(new(Segment(startMs + delay, endMs, effect, new EvidenceReal(baseRate + add), "dynamic_after_delay")));
                continue;
            }
            var fallback = Segment(startMs, endMs, effect, new EvidenceReal(baseRate), "dynamic");
            fallback["tick_rate_per_sec"] = new EvidenceReal(tick);
            fallback["max_rate"] = new EvidenceReal(maximum);
            result.Add(new(fallback));
        }
        return result;
    }
}
