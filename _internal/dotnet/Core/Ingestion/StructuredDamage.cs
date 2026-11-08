using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>One structured detail enters the existing hit/evidence rules without a trace-text roundtrip.</summary>
public static class StructuredDamage
{
    private static EvidenceObject Object(EvidenceValue value) => value as EvidenceObject
        ?? throw new InvalidDataException("Expected damage object");
    private static EvidenceObject OptionalObject(EvidenceValue value) => value is EvidenceNull
        ? new(new Dictionary<string, EvidenceValue>()) : Object(value);
    private static BigInteger? Integer(EvidenceValue value) => value switch
    {
        EvidenceNull => null, EvidenceInteger integer => integer.Value,
        _ => throw new InvalidDataException("Expected damage integer"),
    };
    private static double? Number(EvidenceValue value) => value switch
    {
        EvidenceNull => null, EvidenceInteger integer when double.IsFinite((double)integer.Value) => (double)integer.Value,
        EvidenceReal real when double.IsFinite(real.Value) => real.Value,
        _ => throw new InvalidDataException("Expected finite damage number"),
    };
    private static string Label(EvidenceValue value) => value is EvidenceText text ? text.Value
        : throw new InvalidDataException("Expected damage label");
    private static string? Identity(EvidenceValue value)
    {
        if (value is EvidenceNull) return null;
        if (value is not EvidenceText text || text.Value.Length == 0 || text.Value.Any(unit => unit is < '0' or > '9'))
            throw new InvalidDataException("Damage instance IDs must be decimal strings");
        return BigInteger.Parse(text.Value, CultureInfo.InvariantCulture) > 0 ? text.Value : null;
    }
    private static BigInteger? Index(EvidenceValue value) => Integer(value) is { Sign: >= 0 } number ? number : null;
    private static BigInteger? Positive(EvidenceValue value) => Integer(value) is { Sign: > 0 } number ? number : null;
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array
        ? array.Items.OfType<EvidenceObject>() : [];
    private static IEnumerable<EvidenceObject> BlackboardRows(EvidenceValue value) => value is EvidenceArray array
        && array.Items.All(item => item is EvidenceObject) ? array.Items.Cast<EvidenceObject>()
        : throw new InvalidDataException("Expected damage blackboard rows");
    private static string General(double value) => value.ToString("g6", CultureInfo.InvariantCulture);
    private static double Project(double value, string format) => double.Parse(value.ToString(format, CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);

    public static DamageObservation Observation(TraceEvent item)
    {
        if (item.Type != "damage") throw new InvalidDataException("Expected damage event");
        var data = item.Data; var actors = Object(data.Get("actors")); var action = Object(data.Get("action"));
        var amounts = Object(data.Get("amounts")); var blackboards = Object(data.Get("blackboards"));
        _ = Object(data.Get("evidence"));
        var sequence = Positive(data.Get("hit_seq")) ?? throw new InvalidDataException("Damage hit_seq must be positive");
        var raw = Math.Abs(Number(amounts.Get("value")) ?? throw new InvalidDataException("Missing damage amount"));
        if (new BigInteger(raw + 0.5) <= 0) throw new InvalidDataException("Damage detail must contain a positive hit");
        var hp = Number(amounts.Get("current_hp")) ?? 0; if (hp == 0) hp = 0;
        var critical = amounts.Get("is_crit") switch
        { EvidenceNull => false, EvidenceBoolean flag => flag.Value, _ => throw new InvalidDataException("Expected damage critical flag") };
        Dictionary<BigInteger, double> dynamic = [];
        Dictionary<BigInteger, Dictionary<string, EvidenceValue>> calculation = [];
        List<string> dynamicTokens = [], calculationTokens = [];
        foreach (var row in BlackboardRows(blackboards.Get("dynamic")))
        {
            var id = Integer(row.Get("action_id")) ?? throw new InvalidDataException("Missing blackboard action");
            var value = Number(row.Get("value")) ?? throw new InvalidDataException("Missing blackboard value");
            var token = General(value); dynamicTokens.Add(id + ":" + token);
            dynamic[id] = double.Parse(token, CultureInfo.InvariantCulture);
        }
        foreach (var row in BlackboardRows(blackboards.Get("calculation")))
        {
            var id = Integer(row.Get("action_id")) ?? throw new InvalidDataException("Missing calculation blackboard action");
            var key = Label(row.Get("key")); if (key.Length == 0) throw new InvalidDataException("Missing calculation blackboard key");
            var value = Number(row.Get("value")) ?? throw new InvalidDataException("Missing calculation blackboard value");
            var token = General(value); calculationTokens.Add(id + ":" + key + "=" + token);
            if (!calculation.TryGetValue(id, out var entries)) calculation[id] = entries = new(StringComparer.Ordinal);
            entries[key] = new EvidenceReal(double.Parse(token, CultureInfo.InvariantCulture));
        }
        var owner = Identity(item.Source.Get("owner_id"));
        if (owner is not null && (owner[0] == '0' || BigInteger.Parse(owner, CultureInfo.InvariantCulture) >= BigInteger.One << 64)) owner = null;
        var attacker = Label(actors.Get("attacker"));
        return new()
        {
            Sequence = sequence, Source = attacker, Attacker = attacker, Target = Label(actors.Get("target")),
            SourceActor = Identity(actors.Get("attacker_id")), TargetActor = Identity(actors.Get("target_id")),
            Skill = Label(action.Get("skill")), TemplateType = action.Get("template_type") is EvidenceText { Value.Length: > 0 } template ? template.Value : "unknown",
            Hit = new BigInteger(raw + 0.5), HitObserved = true, Raw = Project(raw, "F2"), Final = raw,
            EnemyHp = new BigInteger(Project(hp, "F0")), EnemyHpObserved = true, Critical = critical ? 1 : 0, CriticalObserved = true,
            SkillLevel = Positive(action.Get("skill_level")), TemplateInteger = Positive(action.Get("template_int_id")),
            OriginalTemplate = Positive(action.Get("original_template_int_id")),
            EventInstance = Identity(action.Get("event_inst_id")), EventOwner = Identity(action.Get("event_owner_id")),
            Action = Index(action.Get("action_id")), UnitIndex = Index(action.Get("damage_unit_index")),
            PartInstance = Identity(action.Get("part_inst_id")) is { } part ? BigInteger.Parse(part, CultureInfo.InvariantCulture) : null,
            ClientTick = item.ClientTickMs >= 0 ? new BigInteger(item.ClientTickMs.Value) : null,
            PacketSequence = Index(item.Source.Get("operation_seq")), PacketOwner = owner, PacketGeneration = Index(item.Source.Get("generation")),
            PacketSession = item.Source.Get("session_id") is EvidenceText { Value.Length: > 0 } session ? session.Value : null,
            Blackboards = new(dynamicTokens.Count > 0 ? string.Join(',', dynamicTokens) : "unknown", dynamic,
                calculationTokens.Count > 0 ? string.Join(',', calculationTokens) : "unknown", calculation),
        };
    }

    private static string[] ModifierIds(EvidenceObject mods, string side) => Rows(mods.Get(side + "_modifiers"))
        .Select(row => row.Get("buff_inst_id")).Where(value => value is not EvidenceNull && value is not EvidenceText { Value.Length: 0 }
            && value is not EvidenceInteger { Value.IsZero: true } && value is not EvidenceBoolean { Value: false }
            && value is not EvidenceReal { Value: 0 }).Select(PythonDisplay.String).ToArray();
    private static BigInteger? AttributeKind(EvidenceValue value) => value switch
    {
        EvidenceBoolean flag => flag.Value ? 1 : 0, EvidenceReal real when double.IsFinite(real.Value) => new BigInteger(real.Value),
        _ => TraceFields.OptionalInteger(PythonDisplay.String(value)),
    };
    private static string AttributeText(EvidenceValue value) => value switch
    {
        EvidenceBoolean flag => PythonDisplay.Float(flag.Value ? 1 : 0), EvidenceReal real => PythonDisplay.Float(real.Value),
        EvidenceInteger integer => PythonDisplay.Float((double)integer.Value),
        EvidenceText text when double.TryParse(text.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number) => PythonDisplay.Float(number),
        _ => PythonDisplay.String(value),
    };
    private static string[] Attributes(EvidenceObject report, string side) => Rows(report.Get(side + "_attr_modify_info"))
        .Where(row => AttributeKind(row.Get("attr_type")) is not null).Select(row => AttributeKind(row.Get("attr_type")) + ":" + string.Join(',',
            row.Get("attrs") is EvidenceArray array ? array.Items.Select(AttributeText) : [])).ToArray();

    public static void Accept(TraceEvent item, int evidenceIndex, HitBuffLifecycleObservations lifecycle, PacketObservationState packets)
    {
        var observation = Observation(item);
        var evidence = Object(TraceModel.Data(item).Get("evidence"));
        var mods = OptionalObject(evidence.Get("modifier_args")); var report = OptionalObject(evidence.Get("battle_report_info"));
        var presence = OptionalObject(evidence.Get("presence"));
        var attackerMods = ModifierIds(mods, "attacker"); var defenderMods = ModifierIds(mods, "defender");
        var attackerAttrs = Attributes(report, "attacker"); var defenderAttrs = Attributes(report, "defender");
        var context = evidence.Fields.TryGetValue("packet_context", out var packetContext) ? Object(packetContext).Fields.ToDictionary()
            : new Dictionary<string, EvidenceValue>
            { ["packetSeq"] = item.Source.Get("operation_seq"), ["packetSessionId"] = item.Source.Get("session_id") };
        // Observation() created these dictionaries for this one acceptance;
        // transfer them rather than clone newly allocated private evidence.
        lifecycle.ObserveOwned(observation, evidenceIndex, item.CapturedAtMs);
        var sequence = observation.Sequence!.Value;
        if (attackerMods.Length > 0 || defenderMods.Length > 0)
        {
            packets.ObserveModifiers(new(sequence, attackerMods, defenderMods), item.CapturedAtMs);
            var handles = new Dictionary<string, EvidenceValue>(context)
            {
                ["attacker"] = mods.Get("attacker_modifiers") is EvidenceNull ? new EvidenceArray([]) : mods.Get("attacker_modifiers"),
                ["defender"] = mods.Get("defender_modifiers") is EvidenceNull ? new EvidenceArray([]) : mods.Get("defender_modifiers"),
            };
            packets.ObserveModifierHandles(sequence, new EvidenceObject(handles));
        }
        var present = presence.Get("has_battle_report_info") is EvidenceBoolean flag ? flag.Value
            : evidence.Get("battle_report_info") is EvidenceObject ? true : (bool?)null;
        if (present is not null)
        {
            context["reportPresent"] = new EvidenceBoolean(present.Value);
            packets.ObserveAttributeReport(sequence, new EvidenceObject(context));
        }
        if (attackerAttrs.Length > 0 || defenderAttrs.Length > 0)
            packets.ObserveAttributes(new(sequence, attackerAttrs, defenderAttrs));
    }
}
