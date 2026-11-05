using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public sealed partial class TraceBridge
{
    private long structuredEventSequence;
    private TraceEvent StructuredDamage(EvidenceObject e, EvidenceObject detail, int detailIndex, EvidenceObject presence,
        long ts, string attacker, BigInteger? attackerId, string target, BigInteger? targetId, string skill, BigInteger originalTemplate, BigInteger inst)
    {
        Dictionary<string, EvidenceValue> action = new() { ["skill"] = new EvidenceText(skill), ["original_template_int_id"] = new EvidenceInteger(originalTemplate) };
        foreach (var (output, value) in new[] {
            ("skill_level", e.Get("level")), ("template_int_id", e.Get("template_int_id")),
            ("template_type", e.Get("template_type")), ("action_id", Obj(e.Get("action")).Get("action_id")),
            ("damage_unit_index", detail.Get("damage_unit_index")), })
            if (value is not EvidenceNull) action[output] = output == "template_type" ? value : Int(value) is { } number ? new EvidenceInteger(number) : EvidenceNull.Value;
        foreach (var (output, value) in new[] { ("event_inst_id", e.Get("inst_id")), ("event_owner_id", e.Get("owner_id")), ("part_inst_id", detail.Get("part_inst_id")) })
            if (value is not EvidenceNull) action[output] = value;
        Dictionary<string, EvidenceValue> source = new() { ["detail_index"] = new EvidenceInteger(detailIndex) };
        if (e.Get("session_id") is EvidenceText { Value.Length: > 0 } session) source["session_id"] = session;
        if (e.Get("seq_id") is EvidenceInteger operation) source["operation_seq"] = operation;
        if (e.Get("generation") is EvidenceInteger generation && generation.Value >= 0 && generation.Value < BigInteger.One << 32)
            source["generation"] = generation;
        if (DecimalRange(e.Get("operation_owner_id"), 0, BigInteger.One << 64)) source["owner_id"] = new EvidenceText(S(e.Get("operation_owner_id")));
        if (action.TryGetValue("action_id", out var actionId)) source["action_id"] = actionId;
        Dictionary<string, EvidenceValue> amounts = [];
        foreach (var (input, output) in new[] { ("value", "value"), ("cur_hp", "current_hp"), ("is_crit", "is_crit") })
            if (detail.Fields.TryGetValue(input, out var value)) amounts[output] = value;
        var excluded = new HashSet<string>(["value", "cur_hp", "is_crit", "target_id", "damage_unit_index", "part_inst_id"], StringComparer.Ordinal);
        var evidence = detail.Fields.Where(pair => !excluded.Contains(pair.Key)).ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
        evidence["presence"] = presence;
        evidence["packet_context"] = Make(("packetSeq", e.Get("seq_id")), ("packetSessionId", e.Get("session_id")));
        Dictionary<string, EvidenceValue> actors = new() { ["attacker"] = new EvidenceText(attacker), ["target"] = new EvidenceText(target) };
        if (attackerId is not null) actors["attacker_id"] = new EvidenceInteger(attackerId.Value);
        if (targetId is not null) actors["target_id"] = new EvidenceInteger(targetId.Value);
        var blackboards = Make(
            ("dynamic", (dynamicBb.GetValueOrDefault(inst) ?? []).Select(row => Make(("action_id", row.Action), ("value", row.Value))).ToArray()),
            ("calculation", (calcBb.GetValueOrDefault(inst) ?? []).Select(row => Make(("action_id", row.Action), ("key", row.Key), ("value", row.Value))).ToArray()));
        // Capture takes ownership of all containers below. Do not first deep-copy
        // the decoded evidence through Make only to copy it again during projection.
        var data = new EvidenceObject(new Dictionary<string, EvidenceValue>
        {
            ["hit_seq"] = new EvidenceInteger(hitSeq), ["actors"] = new EvidenceObject(actors),
            ["action"] = new EvidenceObject(action), ["amounts"] = new EvidenceObject(amounts),
            ["blackboards"] = blackboards, ["evidence"] = new EvidenceObject(evidence),
        });
        var projected = TraceValueProjection.Capture(data);
        var payload = ((EvidenceObject)projected.Value).Fields.ToDictionary();
        payload["legacy_layout"] = projected.Layout;
        return new(++structuredEventSequence, ts, "damage", new EvidenceObject(payload), (EvidenceObject)EvidenceJson.Clone(new EvidenceObject(source)),
            e.Get("client_tick_tms") is EvidenceInteger tick && tick.Value >= long.MinValue && tick.Value <= long.MaxValue ? (long)tick.Value : null);
    }
}
