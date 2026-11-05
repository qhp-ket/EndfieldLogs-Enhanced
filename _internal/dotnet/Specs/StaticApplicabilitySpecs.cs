using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Reporting;

internal static class StaticApplicabilitySpecs
{
    private static EvidenceObject Obj(string json)=>(EvidenceObject)EvidenceJson.Parse(json);
    public static void Run(Action<bool,string> check)
    {
        var source=Obj("""{"zone":"dmg_inc","rate":0.2,"attr_type":32,"evidence_kind":"official_EquipTable_attribute"}""");
        var runtime=Obj("""{"damage_decorate_mask":256}""");
        check(StaticEntryApplicability.Evaluate(source,runtime) is { Applies:true,UnresolvedCondition:false },
            "A positive equipment skill rate applies to an explicitly observed matching runtime category");
        check(StaticEntryApplicability.Evaluate(source,Obj("""{"damage_decorate_mask":0}""")) is { Applies:false,UnresolvedCondition:false },
            "An observed zero mask proves the category absent without marking it unknown");
        check(StaticEntryApplicability.Evaluate(source,Obj("{}")) is { Applies:false,UnresolvedCondition:true }
            && StaticEntryApplicability.Evaluate(source,Obj("""{"damage_decorate_mask":256.0}""")) is { Applies:false,UnresolvedCondition:true },
            "A missing or noninteger mask cannot prove skill applicability");
        var template=Obj("""{"static_damage_decorate_mask":256,"static_damage_decorate_mask_source":"current_typed_skill_or_buff_exact_unit_generation_only"}""");
        check(StaticEntryApplicability.Evaluate(source,template) is { Applies:true,UnresolvedCondition:false }
            && StaticEntryApplicability.Evaluate(source,Obj("""{"static_damage_decorate_mask":0,"static_damage_decorate_mask_source":"current_typed_skill_or_buff_exact_unit_generation_only"}""")) is { Applies:false,UnresolvedCondition:true },
            "An exact current template proves positive category bits while missing template bits remain unknown");
        check(!StaticEntryApplicability.Evaluate(source,Obj("""{"damage_decorate_mask":256,"baseline":{"32":0}}""")).Applies,
            "An observed final zero attribute already includes equipment and prevents counting its rate again");
        var numeric=new Dictionary<BigInteger,EvidenceValue> { [32]=EvidenceNull.Value };
        check(StaticEntryApplicability.Evaluate(source,Obj("""{"damage_decorate_mask":256,"baseline":{"32":0}}"""),numeric)
            is { Applies:true,UnresolvedCondition:true },
            "An invalid numeric observation takes precedence over a valid text alias and retains uncertainty");
        numeric[32]=new EvidenceInteger(0);
        check(StaticEntryApplicability.Evaluate(source,Obj("""{"damage_decorate_mask":256,"baseline":{"32":"invalid"}}"""),numeric)
            is { Applies:false,UnresolvedCondition:false },
            "A valid numeric observation takes precedence over an invalid text alias without double counting");
        var attack=Obj("""{"zone":"atk","rate":0.3,"attr_type":2,"evidence_kind":"official_EquipTable_attribute"}""");
        check(StaticEntryApplicability.Evaluate(attack,Obj("""{"baseline":{"2":120}}""")) is { Applies:true,UnresolvedCondition:false },
            "Percent attack retains the reference exception to final attribute suppression");
        var grouped=Obj("""{"zone":"dmg_inc","rate":0.2,"skill_groups":["normal","skill","skill"]}""");
        check(StaticEntryApplicability.Evaluate(grouped,runtime) is { Applies:true,UnresolvedCondition:false }
            && StaticEntryApplicability.Evaluate(grouped,Obj("""{"damage_decorate_mask":8192}""")) is { Applies:false,UnresolvedCondition:false }
            && StaticEntryApplicability.Evaluate(Obj("""{"zone":"dmg_inc","rate":0.2,"skill_groups":["unknown"]}"""),runtime).UnresolvedCondition,
            "Group selection is a unique mask union and unsupported groups remain unresolved");
        check(!StaticEntryApplicability.Evaluate(Obj("""{"zone":"crit","rate":0.5}"""),runtime).Applies
            && !StaticEntryApplicability.Evaluate(Obj("""{"zone":"dmg_inc","rate":0}"""),runtime).Applies,
            "Critical zones and nonpositive rates do not become allocatable static contributions");
        check(StaticEntryApplicability.Evaluate(Obj("""{"zone":"dmg_inc","rate":0.2,"element":"spell"}"""),Obj("""{"damage_element":"fire"}""")).Applies
            && !StaticEntryApplicability.Evaluate(Obj("""{"zone":"dmg_inc","rate":0.2,"element":"physical"}"""),Obj("""{"damage_element":"physical","damage_school":false}""")).Applies,
            "Element fallback is used only when school evidence is absent, including malformed explicit school evidence");
        var before=EvidenceJsonSignature.Sorted(template);
        _=StaticEntryApplicability.Evaluate(source,template);
        check(before==EvidenceJsonSignature.Sorted(template) && template.Get("rdps_unresolved_effect_conditions") is EvidenceNull
            && DamageAttributeApplicability.Evaluate(new EvidenceInteger(50),EvidenceNull.Value,EvidenceNull.Value,EvidenceNull.Value) is true,
            "Pure evaluation leaves input evidence unchanged and ordinary elemental attributes need no category mask");
    }
}
