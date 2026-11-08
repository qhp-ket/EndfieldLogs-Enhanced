using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public sealed record StructuredEntityObservation(EntityStatsEvidence? Evidence, string? PartyActorId, bool Partial);

public static class StructuredEntity
{
    public static EvidenceObject ValueData(EvidenceObject source)
    {
        Dictionary<string, EvidenceValue> result = [];
        foreach (var (input, output) in new (string, string)[] {
            ("entity_inst_id", "entity_id"), ("seq_id", "operation_seq"), ("scene_num_id", "scene_num_id"),
            ("hp", "hp"), ("ultimatesp", "ultimate_sp"), ("delta_value", "delta"),
            ("template_type", "source_type"), ("template_int_id", "source_int"),
            ("orig_template_type", "original_source_type"), ("orig_template_int_id", "original_source_int") })
            if (source.Fields.TryGetValue(input, out var value)) result[output] = value;
        return new(result);
    }

    public static EvidenceObject SpawnData(EvidenceObject source, EvidenceObject detail, EvidenceValue actionId,
        string owner, string actor, string skill)
    {
        Dictionary<string, EvidenceValue> result = [], row = [];
        foreach (var (input, output) in new (string, string)[] { ("seq_id", "operation_seq"), ("client_tick_tms", "client_tick_ms"),
            ("inst_id", "event_inst_id"), ("owner_id", "owner_id"), ("template_int_id", "template_int_id") })
            if (source.Fields.TryGetValue(input, out var value)) result[output] = value;
        result["action_id"] = actionId;
        result["owner"] = owner == "?" ? EvidenceNull.Value : new EvidenceText(owner);
        result["source"] = actor == "?" ? EvidenceNull.Value : new EvidenceText(actor);
        result["skill"] = skill == "unknown_skill" ? EvidenceNull.Value : new EvidenceText(skill);
        foreach (var (input, output) in new (string, string)[] { ("client_ability_entity_id", "entity_id"),
            ("source_id", "source_actor_id"), ("init_pos", "position"), ("rotation", "rotation") })
            if (detail.Fields.TryGetValue(input, out var value)) row[output] = value;
        result["detail"] = new EvidenceObject(row);
        return new(result);
    }

    private static EvidenceObject Object(EvidenceValue value) => value as EvidenceObject ?? throw new InvalidDataException("Expected entity object");
    private static BigInteger? Integer(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsFinite(real.Value) => new BigInteger(real.Value),
        EvidenceText text when BigInteger.TryParse(text.Value.Trim(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var integer) => integer,
        _ => null,
    };
    private static double? Number(EvidenceValue value) => value switch
    {
        EvidenceObject marker when marker.Get("number_status") is EvidenceText { Value: "nan" or "positive_infinity" or "negative_infinity" } => double.NaN,
        EvidenceReal real => real.Value, EvidenceInteger integer => (double)integer.Value,
        EvidenceBoolean flag => flag.Value ? 1 : 0,
        EvidenceText text when double.TryParse(text.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number) => number,
        _ => null,
    };
    private static double? Project(double value) => double.IsFinite(value)
        ? double.Parse(value.ToString("g6", CultureInfo.InvariantCulture), CultureInfo.InvariantCulture) : null;

    public static StructuredEntityObservation Observation(TraceEvent item)
    {
        if (item.Type is not ("entity_stats" or "entity_attributes" or "entity_value" or "entity_die" or "ability_spawn")) throw new InvalidDataException("Expected entity event");
        if (item.Type is "entity_value" or "entity_die" or "ability_spawn")
        {
            var detail = item.Data.Fields.TryGetValue("detail", out var value) ? Object(value) : new EvidenceObject(new Dictionary<string, EvidenceValue>());
            foreach (var fields in new[] { item.Data, detail })
                foreach (var key in new[] { "entity_id", "event_inst_id", "owner_id", "source_actor_id" })
                    if (fields.Fields.TryGetValue(key, out var identity) && identity is not EvidenceNull
                        && (identity is not EvidenceText digits || digits.Value.Length == 0 || digits.Value.Any(unit => unit is < '0' or > '9')))
                        throw new InvalidDataException("Entity instance IDs must be decimal strings");
            // These are diagnostic observations, never inferred attributes or party bindings.
            return new(null, null, false);
        }
        if (!item.Data.Fields.TryGetValue("entity_id", out var rawIdentity)) throw new InvalidDataException("Missing entity identity");
        if (rawIdentity is not EvidenceNull && (rawIdentity is not EvidenceText text || text.Value.Length == 0 || text.Value.Any(unit => unit is < '0' or > '9')))
            throw new InvalidDataException("Entity instance IDs must be decimal strings");
        var data = TraceModel.Data(item);
        if (data.Get("template") is not EvidenceText template || data.Get("kind") is not (EvidenceText or EvidenceNull))
            throw new InvalidDataException("Expected entity labels");
        var kind = (data.Get("kind") as EvidenceText)?.Value;
        var id = data.Get("entity_id") is EvidenceNull ? "" : PythonDisplay.String(data.Get("entity_id"));
        var partial = item.Type == "entity_attributes";
        var party = !partial && kind == "character" && ActorIdentity.CharacterKey(template.Value) is not null && id.Length > 0 ? id : null;
        if (id.Length == 0 || id[0] == '0' || id.Any(unit => unit is < '0' or > '9')) return new(null, party, partial);
        List<EntityAttributeObservation> values = [];
        if (data.Get("attributes") is EvidenceArray array)
            foreach (var row in array.Items.OfType<EvidenceObject>())
            {
                if (Integer(row.Get("attr_type")) is not BigInteger attribute) continue;
                var number = Number(row.Get("value")) ?? 0; var basic = Number(row.Get("basic_value")) ?? number;
                values.Add(new(attribute, Project(number), Project(basic)));
            }
        var level = data.Get("level") is EvidenceNull ? null : TraceFields.OptionalInteger(PythonDisplay.String(data.Get("level")));
        return new(new(id, EntityStatsDecoder.Snapshot(template.Value, kind, level, values, item.CapturedAtMs, true)), party, partial);
    }

    public static void Accept(StructuredEntityObservation observation, int evidenceIndex, long timestampMs,
        EntityObservationState entities, ISet<string> partyActorIds)
    {
        if (observation.PartyActorId is { } party) partyActorIds.Add(party);
        if (observation.Evidence is { } evidence) entities.Observe(evidence, evidenceIndex, timestampMs, observation.Partial);
    }
}
