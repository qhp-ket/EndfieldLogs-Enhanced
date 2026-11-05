using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Allocation;

public sealed record HitAllocationResult(EvidenceObject Hit, IReadOnlyList<EvidenceObject> Windows, EvidenceObject Allocation)
{
    internal IReadOnlyList<int>? EvaluatedWindowIndices { get; init; }
}

/// <summary>Ordered per-hit allocation pipeline. The report owns its inputs; returned evidence owns all hit changes.</summary>
public sealed class HitAllocator(AllocationContextBuilder context, EffectStackPolicy stacks, AllocationResistance resistance,
    EffectContributorCollection contributors, AllocationBaselines baselines, AllocationExplanation explanation)
{
    public HitAllocationResult Allocate(AllocationEvidenceInput input)
    {
        if (input.Hit.Evidence.Get("_ink_allocation") is not EvidenceNull)
            return ProjectRecordedInk(input);
        var state = context.Prepare(input);
        state.SelectStackEffects(stacks);
        resistance.Resolve(state);
        contributors.Collect(state);
        baselines.AttachObserved(state);
        baselines.ResolveAttack(state);
        baselines.CheckRemaining(state);
        AllocationMultipliers.Compute(state);
        var shares = LogMarginalAllocation.Allocate(state);
        return new(state.Hit, state.Windows, explanation.Project(state, shares))
        {
            EvaluatedWindowIndices = state.RequiresFullWindowReset
                ? Enumerable.Range(0, state.Windows.Count).ToArray() : state.WindowIndices,
        };
    }

    private HitAllocationResult ProjectRecordedInk(AllocationEvidenceInput input)
    {
        var hit = input.ConsumesHit ? input.Hit.Evidence : (EvidenceObject)BuffEvidence.Clone(input.Hit.Evidence);
        var shares = hit.Get("_ink_allocation") as EvidenceObject ?? throw new InvalidDataException("Recorded ink shares must be an object");
        var fields = new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
        {
            ["allocation_policy"] = new EvidenceText("whole_ink_damage_log_zones_v1"), ["allocation_policy_basis"] = new EvidenceText("accounting_convention"),
            ["contributions_map"] = BuffEvidence.Clone(shares),
        };
        fields["contributions_list"] = new EvidenceArray(explanation.RecordedContributionRows(shares).Cast<EvidenceValue>().ToArray());
        if (input.IncludeDebug)
        {
            var attacker = CatalogValues.Text(hit.Fields["character_key"]);
            fields["zones"] = new EvidenceArray([]);
            fields["ignored_effects"] = new EvidenceArray([]);
            fields["attacker_share"] = shares.Fields.GetValueOrDefault(attacker) ?? new EvidenceInteger(0);
            fields["external_pool"] = PythonNumericSum.Sum(shares.Fields.Where(pair => pair.Key != attacker).Select(pair => pair.Value));
            fields["product_external_multiplier"] = EvidenceNull.Value;
            fields["external_sources"] = new EvidenceArray([]);
            fields["zone_summary"] = BuffEvidence.Object();
            fields["buff_source_summary"] = new EvidenceArray([]);
            fields["ink_provenance"] = BuffEvidence.Clone(hit.Fields["ink_provenance"]);
        }
        return new(hit, input.OwnsWindowBuffer ? input.Windows : input.Windows.ToArray(), new(fields));
    }

    public static HitAllocator Load(ResourceFiles files)
    {
        var roots = new BuffRootCatalog(files);
        SkillResourceCatalog skills = new(files);
        DisplayNameCatalog names = new(files, new(files), skills.CreateIdentityCatalog());
        var packets = PacketBuffCatalog.Load(files, skills);
        EffectApproval approval = new(EffectApprovalCatalog.Load(files), roots.Roots, skills.Buffs, skills.Skills);
        SemanticEffectCatalog semantics = new(roots.Roots, DamageZoneCatalog.Load(files), approval);
        BuffLabelCatalog labels = new(semantics, BuffDisplayClassification.Load(files, packets), new(packets, EnhancedChildEffectCatalog.Load(files)));
        AllocationDebug debug = new(names.Character);
        return new(new(new AttackDependenceClassifier(new SkillDamageUnits(skills, roots))), EffectStackPolicy.Load(files, roots.Roots),
            new(roots), new(debug), new(debug), new(debug, labels.Collect));
    }
}
