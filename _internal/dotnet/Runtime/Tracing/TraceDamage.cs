using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public sealed partial class TraceBridge
{
    private string SourceSkill(EvidenceObject e, string prefix = "") => ResolveSkill(e.Get(prefix + "template_str_id"), e.Get(prefix + "template_int_id")) ?? Text(e.Get(prefix + "template_str_id"), "unknown");
    private string? StructuredSource(EvidenceObject e, string prefix = "") => ResolveSkill(e.Get(prefix + "template_str_id"), e.Get(prefix + "template_int_id"))
        ?? (Truth(e.Get(prefix + "template_str_id")) ? S(e.Get(prefix + "template_str_id")) : null);
    private void Atb(EvidenceObject e, long ts)
    {
        if (eventOutput is not null)
        {
            var fields = SkillWire.Data("atb", e).Fields.ToDictionary(); var owner = Name(Int(e.Get("owner_id")));
            fields["owner"] = Value(owner == "?" ? null : owner); fields["source"] = Value(StructuredSource(e)); fields["original_source"] = Value(StructuredSource(e, "orig_"));
            EmitStructured(ts, "atb", new(fields), e); return;
        }
        Line(ts, $"ATB_UPDATE seq={I(Int(e.Get("seq_id")) ?? 0)} tick={I(Int(e.Get("client_tick_tms")) ?? 0)} owner={Name(Int(e.Get("owner_id")))} ownerId={I(Int(e.Get("owner_id")))} reason={Text(e.Get("reason"), "unknown")} atb={General(Float(e.Get("atb_value")))} recoverySpeed={General(Float(e.Get("atb_recovery_speed")))} delta={General(Float(e.Get("delta_value")))} source={SourceSkill(e)} origSource={SourceSkill(e, "orig_")}");
    }
    private void Poise(EvidenceObject e, long ts)
    {
        if (eventOutput is not null)
        {
            var fields = SkillWire.Data("poise", e).Fields.ToDictionary(); var attacker = Name(Int(e.Get("attacker_inst_id")));
            fields["attacker"] = Value(attacker == "?" ? null : attacker); fields["source"] = Value(StructuredSource(e)); fields["original_source"] = Value(StructuredSource(e, "orig_"));
            EmitStructured(ts, "poise", new(fields), e); return;
        }
        Line(ts, $"POISE_V1 seq={I(Int(e.Get("seq_id")) ?? 0)} tick={I(Int(e.Get("client_tick_tms")) ?? 0)} type={Text(e.Get("modify_type"), "unknown")} value={General(Float(e.Get("value")))} cur={General(Float(e.Get("cur_poise_value")))} attacker={Name(Int(e.Get("attacker_inst_id")))} attackerId={I(Int(e.Get("attacker_inst_id")))} ownerType={Text(e.Get("owner_type"), "unknown")} sourceType={Text(e.Get("template_type"), "unknown")} source={SourceSkill(e)} sourceInt={I(Int(e.Get("template_int_id")))} origSourceType={Text(e.Get("orig_template_type"), "unknown")} origSource={SourceSkill(e, "orig_")} origSourceInt={I(Int(e.Get("orig_template_int_id")))} actionId={I(Int(e.Get("action_id")))}");
    }
    private void EntityValue(EvidenceObject e, long ts)
    {
        if (eventOutput is not null) { EmitStructured(ts, "entity_value", StructuredEntity.ValueData(e), e); return; }
        static string Number(EvidenceValue value) => Float(value) is { } number ? PythonDisplay.Float(number) : "unknown";
        Line(ts, $"ENTITY_VALUE seq={S(e.Get("seq_id"))} id={I(Int(e.Get("entity_inst_id")))} scene={Present(e.Get("scene_num_id"))} hp={Number(e.Get("hp"))} ult={Number(e.Get("ultimatesp"))} delta={Number(e.Get("delta_value"))} srcType={Text(e.Get("template_type"), "unknown")} srcInt={I(Int(e.Get("template_int_id")))} origSrcType={Text(e.Get("orig_template_type"), "unknown")} origSrcInt={I(Int(e.Get("orig_template_int_id")))}");
    }
    private static bool DecimalRange(EvidenceValue value, BigInteger min, BigInteger limit, bool signed = false)
    {
        if (value is not (EvidenceInteger or EvidenceText)) return false;
        var text = S(value); var digits = signed && text.StartsWith('-') ? text[1..] : text;
        return digits.Length > 0 && digits.All(unit => unit is >= '0' and <= '9') && BigInteger.TryParse(text, out var number) && number >= min && number < limit;
    }
    private void Damage(EvidenceObject e, EvidenceValue payload, long ts)
    {
        if (payload is not EvidenceObject damage) return;
        var attackerId = Id(damage.Get("attacker_id")) ?? Int(e.Get("owner_id"));
        var skill = TriggerSkill(e); var original = Obj(damage.Get("original_source_template_id"));
        var origNum = Int(original.Get("int_id")) ?? 0;
        var originalSkill = ResolveSkill(original.Get("str_id"), new EvidenceInteger(origNum));
        if (attackerId is { IsZero: false } aid && Character(originalSkill) is { } character && names.TryAdd(aid, character))
            WriteActorMapping(ts, aid, character, "damage_original_skill", originalSkill ?? skill, e);
        var attacker = Name(attackerId); var inst = Int(e.Get("inst_id")) ?? 0;
        var dyn = damageOutput is null ? string.Join(',', dynamicBb.GetValueOrDefault(inst)?.Select(row => I(row.Action) + ":" + General(row.Value)) ?? []) : "";
        var calc = damageOutput is null ? string.Join(',', calcBb.GetValueOrDefault(inst)?.Select(row => I(row.Action) + ":" + row.Key + "=" + General(row.Value)) ?? []) : "";
        if (damage.Get("details") is not EvidenceArray details) return;
        var presence = Items(e.Get("damage_detail_presence")).ToArray();
        for (var index = 0; index < details.Items.Count; index++)
        {
            if (details.Items[index] is not EvidenceObject detail) continue;
            var raw = Math.Abs(Float(detail.Get("value")) ?? 0);
            var hit = new BigInteger(raw + 0.5);
            if (hit <= 0) continue;
            var targetId = Int(detail.Get("target_id")); var crit = Truth(detail.Get("is_crit"));
            hitSeq++;
            if (damageOutput is not null)
            {
                FlushStarts();
                damageOutput(StructuredDamage(e, detail, index, Obj(index < presence.Length ? presence[index] : null),
                    ts, attacker, attackerId, Name(targetId, target: true), targetId, skill, origNum, inst));
                continue;
            }
            var hp = Float(detail.Get("cur_hp")) ?? 0;
            if (hp == 0) hp = 0; // Python's `value or 0.0` clears the sign bit of negative zero.
            var calcArgs = Obj(detail.Get("calculate_damage_check_args"));
            var calcTokens = DamageLegacyExporter.CalculationFields.Where(pair => Float(calcArgs.Get(pair.Input)) is not null).Select(pair => pair.Token + "=" + General(Float(calcArgs.Get(pair.Input)))).ToArray();
            List<string> packet = [];
            if (e.Get("session_id") is EvidenceText { Value.Length: > 0 } session) packet.Add("packetSessionId=" + Quote(session.Value));
            if (DecimalRange(e.Get("operation_owner_id"), 0, BigInteger.One << 64)) packet.Add("packetOwnerId=" + S(e.Get("operation_owner_id")));
            if (e.Get("generation") is EvidenceInteger gen && gen.Value >= 0 && gen.Value < BigInteger.One << 32) packet.Add("packetGeneration=" + S(gen));
            string Positive(BigInteger? value) => value > 0 ? I(value) : "unknown";
            string ExactInt(string key) => e.Get(key) is EvidenceInteger integer ? S(integer) : "unknown";
            Line(ts, $"HP_V2 #{hitSeq} hit={hit} cum={hit} raw={Fixed(raw, 2)} packetFinalValue={General(raw, 17)} pHP=0 eHP={Fixed(hp, 0)} skill=\"{skill}\" hits=1 skillLv={Positive(Int(e.Get("level")))} templateIntId={Positive(Int(e.Get("template_int_id")))} templateType={Text(e.Get("template_type"), "unknown")} actionId={I(Int(Obj(e.Get("action")).Get("action_id")))} origTemplateIntId={Positive(origNum)} damageUnitIndex={I(Int(detail.Get("damage_unit_index")))} partInstId={Positive(Int(detail.Get("part_inst_id")))} dynBB={(dyn.Length > 0 ? dyn : "unknown")} calcBB={(calc.Length > 0 ? calc : "unknown")} src={attacker} tgt={Name(targetId, target: true)} atk={attacker} atkId={I(attackerId is { IsZero: false } ? attackerId : null)} tgtId={I(targetId is { IsZero: false } ? targetId : null)} seg=0 shared={(crit ? 3 : 2)} critFlag={(crit ? 1 : 0)} critDmg=-1.0000 eventInstId={Positive(inst)} eventOwnerId={I(Id(e.Get("owner_id")))} packetSeq={ExactInt("seq_id")} clientTick={ExactInt("client_tick_tms")} " + (packet.Count > 0 ? string.Join(' ', packet) + " " : "") + (calcTokens.Length > 0 ? " " + string.Join(' ', calcTokens) : ""));
            DamageLegacyExporter.WriteEvidence(e, detail, Obj(index < presence.Length ? presence[index] : null), ts, hitSeq, Line);
        }
        if (!inst.IsZero) { dynamicBb.Remove(inst); calcBb.Remove(inst); }
    }
}
