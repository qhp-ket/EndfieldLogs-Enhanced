using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Allocation;

/// <summary>Prepare the real per-hit allocation context from the report boundary and exact packet evidence.</summary>
public sealed class AllocationContextBuilder(AttackDependenceClassifier attacks)
{
    private static readonly EvidenceArray Empty = new([]);
    private static bool Truth(EvidenceValue value) => CatalogValues.Truth(value);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, Empty));
    private static EvidenceArray Strings(IEnumerable<string> values) => new(values.Order(PythonDisplay.CodePointComparer).Select(value => (EvidenceValue)new EvidenceText(value)).ToArray());

    public HitAllocation Prepare(AllocationEvidenceInput input)
    {
        HitAllocation state = new(input);
        var hit = state.Hit;
        var fields = (Dictionary<string, EvidenceValue>)hit.Fields;
        state.Attacker = CatalogValues.Text(hit.Fields["character_key"]);
        state.Target = CatalogValues.Text(hit.Fields["target_enemy_key"]);
        state.HitValue = EffectIdentity.Float(hit.Fields["hit_value"]);
        state.TimestampMs = checked((long)EffectIdentity.Integer(hit.Fields["ts_ms"]));
        state.Element = hit.Get("damage_element") is EvidenceNull ? null : CatalogValues.Text(hit.Get("damage_element"));
        state.School = hit.Get("damage_school") is EvidenceNull ? null : CatalogValues.Text(hit.Get("damage_school"));
        state.ArtsStrength = HitDamageClassification.ArtsStrength(hit.Get("damage_decorate_mask"),
            (hit.Get("static_damage_decorate_mask") as EvidenceInteger)?.Value,
            (hit.Get("static_damage_decorate_mask_source") as EvidenceText)?.Value,
            hit.Get("arts_strength_damage_observed") is EvidenceBoolean { Value: true },
            hit.Get("arts_strength_damage_source") is EvidenceNull ? null : CatalogValues.Text(hit.Get("arts_strength_damage_source")));
        fields["arts_strength_damage_observed"] = new EvidenceBoolean(state.ArtsStrength.Observed);
        fields["arts_strength_damage_kind"] = BuffEvidence.Text(state.ArtsStrength.Kind);
        fields["arts_strength_damage_source"] = BuffEvidence.Text(state.ArtsStrength.Source);
        fields["arts_strength_damage_factor_count"] = new EvidenceInteger(state.ArtsStrength.FactorCount);
        state.Attack = attacks.Classify(hit);
        fields["attack_damage_dependency"] = new EvidenceText(state.Attack.EvidenceKind);
        state.PacketModifiers = hit.Get("packet_modifier_uids") as EvidenceObject ?? BuffEvidence.Object();
        state.PacketAttributes = hit.Get("packet_attr_details") as EvidenceObject ?? BuffEvidence.Object();
        state.AttackerModifierUids = Items(state.PacketModifiers.Get("attacker")).Select(CatalogValues.Text).Where(uid => uid.Length != 0).ToHashSet(StringComparer.Ordinal);
        state.DefenderModifierUids = Items(state.PacketModifiers.Get("defender")).Select(CatalogValues.Text).Where(uid => uid.Length != 0).ToHashSet(StringComparer.Ordinal);
        state.DefenderAllowedEffects = PacketAllocationEvidence.AllowedAttributes(Items(state.PacketAttributes.Get("defender")));
        state.LineNumber = checked((int)EffectIdentity.Integer(CatalogValues.Or(hit.Get("line_no"), new EvidenceInteger(0))));
        state.ResistanceAttribute = state.Element switch { "physical" => 94, "natural" => 95, "cryst" => 96, "pulse" => 97, "fire" => 98, "ether" => 99, _ => null };
        var resistanceRows = new List<string>();
        foreach (var token in Items(state.PacketAttributes.Get("defender")))
        {
            var text = CatalogValues.Text(token);
            var colon = text.IndexOf(':');
            if (state.ResistanceAttribute is not null && (colon < 0 ? text : text[..colon]) == state.ResistanceAttribute.Value.ToString(System.Globalization.CultureInfo.InvariantCulture))
                resistanceRows.Add(colon < 0 ? "" : text[(colon + 1)..]);
        }
        state.ResistanceRows = resistanceRows;
        var values = resistanceRows.SelectMany(row => row.Split(',')).Select(value => BuffEvidence.OptionalFloat(new EvidenceText(value))).ToArray();
        if (values.Length > 0 && !Truth(hit.Get("packet_attr_conflict")) && values.All(value => value is not null) && values.Distinct().Count() == 1)
            state.EffectiveResistance = values[0];
        state.ResistanceNumerator = state.EffectiveResistance is double resistance ? 100.0 - resistance : null;
        state.ResistanceSource = "PKT_ATTR.defender.attr" + (state.ResistanceAttribute?.ToString(System.Globalization.CultureInfo.InvariantCulture) ?? "None");
        state.WindowIndices = input.WindowIndices?.ToArray() ?? Enumerable.Range(0, input.Windows.Count).ToArray();
        if (Truth(hit.Get("packet_modifier_seen")))
        {
            var selected = state.WindowIndices.Select(index => state.Windows[index]).ToArray();
            var matched = PacketAllocationEvidence.MatchDefender(hit, selected, state.DefenderModifierUids);
            var windows = input.OwnsWindowBuffer && state.Windows is EvidenceObject[] owned ? owned : state.Windows.ToArray();
            for (var index = 0; index < state.WindowIndices.Count; index++) windows[state.WindowIndices[index]] = matched.Windows[index];
            state.Windows = windows;
            state.MatchedDefenderSignatures = matched.Signatures;
        }
        IReadOnlyList<EvidenceObject>? Records(string key) => input.ConditionsByTarget is null ? input.ConditionRecords
            : input.ConditionsByTarget.GetValueOrDefault(key) ?? [];
        state.ActiveTargetBuffIds = PacketAllocationEvidence.ActiveTargetBuffs(hit, Records(Text(hit.Get("target_enemy_key"))));
        fields["_active_target_buff_ids"] = Strings(state.ActiveTargetBuffIds);
        if (Truth(hit.Get("source_actor_id")))
            fields["_active_attacker_buff_ids"] = Strings(PacketAllocationEvidence.ActiveTargetBuffs(hit, Records(Text(hit.Get("character_key"))), "attacker"));
        return state;
    }
}
