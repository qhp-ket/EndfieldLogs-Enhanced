using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

/// <summary>On-demand legacy damage export, independent of TraceBridge state and realtime ingestion.</summary>
public static partial class DamageLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timeZoneOffsetMinutes)
    {
        if (item.Type != "damage") throw new InvalidDataException("Expected damage event");
        if (item.Data.Get("legacy_layout") is not EvidenceObject layout) throw new InvalidDataException("Damage event lacks legacy export layout");
        var data = Obj(TraceValueProjection.Restore(item.Data, layout));
        var actors = Obj(data.Get("actors")); var action = Obj(data.Get("action")); var amounts = Obj(data.Get("amounts"));
        var evidence = Obj(data.Get("evidence")); var context = Obj(evidence.Get("packet_context"));
        var detailFields = evidence.Fields.Where(pair => pair.Key is not ("presence" or "packet_context")).ToDictionary();
        detailFields["damage_unit_index"] = action.Get("damage_unit_index"); detailFields["part_inst_id"] = action.Get("part_inst_id");
        var detail = new EvidenceObject(detailFields);
        var packet = Make(("session_id", context.Get("packetSessionId")), ("seq_id", context.Get("packetSeq")));
        var raw = Math.Abs(Float(amounts.Get("value")) ?? 0); var hit = new BigInteger(raw + 0.5);
        var hp = Float(amounts.Get("current_hp")) ?? 0; if (hp == 0) hp = 0;
        var critical = Truth(amounts.Get("is_crit")); var hitSeq = Int(data.Get("hit_seq")) ?? throw new InvalidDataException("Missing hit sequence");
        static string Positive(EvidenceValue value) => Int(value) is { Sign: > 0 } number ? I(number) : "unknown";
        static string Nonzero(EvidenceValue value) => I(Id(value));
        var boards = Obj(data.Get("blackboards"));
        var dynamic = string.Join(',', Rows(boards.Get("dynamic")).Select(row => I(Int(row.Get("action_id"))) + ":" + General(Float(row.Get("value")))));
        var calculation = string.Join(',', Rows(boards.Get("calculation")).Select(row => I(Int(row.Get("action_id"))) + ":" + S(row.Get("key")) + "=" + General(Float(row.Get("value")))));
        List<string> tokens = [];
        if (item.Source.Get("session_id") is EvidenceText { Value.Length: > 0 } session) tokens.Add("packetSessionId=" + Quote(session.Value));
        if (item.Source.Get("owner_id") is EvidenceText owner) tokens.Add("packetOwnerId=" + owner.Value);
        if (item.Source.Get("generation") is EvidenceInteger generation) tokens.Add("packetGeneration=" + S(generation));
        var calc = CalculationFields.Where(pair => Float(Obj(detail.Get("calculate_damage_check_args")).Get(pair.Input)) is not null)
            .Select(pair => pair.Token + "=" + General(Float(Obj(detail.Get("calculate_damage_check_args")).Get(pair.Input)))).ToArray();
        List<string> bodies = [
            $"HP_V2 #{hitSeq} hit={hit} cum={hit} raw={Fixed(raw, 2)} packetFinalValue={General(raw, 17)} pHP=0 eHP={Fixed(hp, 0)} skill=\"{S(action.Get("skill"))}\" hits=1 " +
            $"skillLv={Positive(action.Get("skill_level"))} templateIntId={Positive(action.Get("template_int_id"))} templateType={Text(action.Get("template_type"), "unknown")} actionId={I(Int(action.Get("action_id")))} " +
            $"origTemplateIntId={Positive(action.Get("original_template_int_id"))} damageUnitIndex={I(Int(action.Get("damage_unit_index")))} partInstId={Positive(action.Get("part_inst_id"))} " +
            $"dynBB={(dynamic.Length > 0 ? dynamic : "unknown")} calcBB={(calculation.Length > 0 ? calculation : "unknown")} src={S(actors.Get("attacker"))} tgt={S(actors.Get("target"))} atk={S(actors.Get("attacker"))} " +
            $"atkId={Nonzero(actors.Get("attacker_id"))} tgtId={Nonzero(actors.Get("target_id"))} seg=0 shared={(critical ? 3 : 2)} critFlag={(critical ? 1 : 0)} critDmg=-1.0000 " +
            $"eventInstId={Positive(action.Get("event_inst_id"))} eventOwnerId={Nonzero(action.Get("event_owner_id"))} packetSeq={I(Int(item.Source.Get("operation_seq")))} clientTick={(item.ClientTickMs is long tick ? tick.ToString(CultureInfo.InvariantCulture) : "unknown")} " +
            (tokens.Count > 0 ? string.Join(' ', tokens) + " " : "") + (calc.Length > 0 ? " " + string.Join(' ', calc) : "")];
        WriteEvidence(packet, detail, Obj(evidence.Get("presence")), item.CapturedAtMs, hitSeq, (_, body) => bodies.Add(body));
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timeZoneOffsetMinutes)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return bodies.Select(body => "[" + stamp + "] " + body + "\n").ToArray();
    }
}
