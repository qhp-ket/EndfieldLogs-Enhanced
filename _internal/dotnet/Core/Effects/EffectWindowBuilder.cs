using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Effects;

public sealed record EffectWindowBuildResult(IReadOnlyList<EvidenceObject> Records,IReadOnlyList<EvidenceObject> Hits,IReadOnlyList<EvidenceObject> Windows)
{
    internal IReadOnlyDictionary<EvidenceObject,EffectRecordAnalysis>? Analyses { get; init; }
}

/// <summary>Report-local assembly of ordinary and exact-hit windows, with owned evidence and quality state.</summary>
public sealed class EffectWindowBuilder(IReadOnlyDictionary<string,EvidenceObject> roots,
    BuffLabelCatalog labels,EffectSpecificationCatalog specifications,DynamicEffectSpecificationCatalog dynamics,
    PacketEffectDisplayCatalog packetDisplay,BuffLoadoutFilter loadouts,EffectStackPolicy stacking,
    EffectApproval approval,SpecialComboWindowBuilder combos)
{
    public static EffectWindowBuilder Load(ResourceFiles files)
    {
        var typed=new BuffRootCatalog(files).Roots;
        SkillResourceCatalog skills=new(files);
        var packets=PacketBuffCatalog.Load(files,skills);
        EffectApproval approval=new(EffectApprovalCatalog.Load(files),typed,skills.Buffs,skills.Skills);
        SemanticEffectCatalog semantics=new(typed,DamageZoneCatalog.Load(files),approval);
        EffectSpecificationCatalog specifications=new(approval,semantics,new(typed));
        PacketEffectDisplayCatalog display=new(packets,EnhancedChildEffectCatalog.Load(files));
        return new(typed,new(semantics,BuffDisplayClassification.Load(files,packets),display),specifications,
            new(approval,specifications,typed,packets),display,BuffLoadoutFilter.Load(files,packets),
            EffectStackPolicy.Load(files,typed),approval,new(typed,skills.Buffs,approval));
    }

    private static readonly EvidenceObject Empty=new(new Dictionary<string,EvidenceValue>());
    private static string Text(EvidenceValue value)=>CatalogValues.Text(CatalogValues.Or(value,new EvidenceText("")));
    private static EvidenceValue Required(EvidenceObject record,string field)=>record.Fields.TryGetValue(field,out var value)
        ? value : throw new KeyNotFoundException(field);
    private static EvidenceValue RequiredAlternative(EvidenceObject record,string first,string second)
    {
        var value=Required(record,first);
        return CatalogValues.Truth(value) ? value : Required(record,second);
    }
    private static EvidenceArray Array(IEnumerable<EvidenceValue> values)=>new(values.ToArray());
    private static BigInteger Integer(EvidenceValue value)=>value switch
    {
        EvidenceInteger number=>number.Value,EvidenceBoolean flag=>flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal number when double.IsFinite(number.Value)=>new BigInteger(number.Value),
        EvidenceReal number when double.IsNaN(number.Value)=>throw new FormatException("cannot convert float NaN to integer"),
        EvidenceReal=>throw new OverflowException("cannot convert float infinity to integer"),
        EvidenceText text=>TraceFields.OptionalInteger(text.Value) ?? throw new FormatException("Invalid lifetime coordinate"),
        _=>throw new InvalidCastException("Invalid lifetime coordinate"),
    };
    private static BigInteger? OptionalInteger(EvidenceValue value)=>value is EvidenceNull ? null : Integer(value);
    private static int Length(EvidenceValue value)=>value switch
    {
        EvidenceArray array=>array.Items.Count,EvidenceObject obj=>obj.Fields.Count,EvidenceText text=>text.Value.EnumerateRunes().Count(),
        _=>throw new InvalidCastException("Invalid attribute modifier collection"),
    };

    public EffectWindowBuildResult Build(ReportEffectInput input)=>Build(input.Records,input.Hits,input.LastHitMs,
        input.StaticArtsStrength,input.ActiveSuits,input.ActiveWeapons);

    public EffectWindowBuildResult Build(IReadOnlyList<EvidenceObject> sourceRecords,IReadOnlyList<EvidenceObject> sourceHits,
        BigInteger lastHitMs,IReadOnlyDictionary<string,double>? staticArtsStrength=null,
        IReadOnlyDictionary<string,HashSet<string>>? activeSuits=null,IReadOnlyDictionary<string,string>? activeWeapons=null,
        EffectRecordCache? recordCache=null)
        => BuildCore(sourceRecords,sourceHits,lastHitMs,staticArtsStrength,activeSuits,activeWeapons,recordCache,ownsHits:false);

    internal EffectWindowBuildResult BuildOwned(IReadOnlyList<EvidenceObject> sourceRecords,IReadOnlyList<EvidenceObject> sourceHits,
        BigInteger lastHitMs,IReadOnlyDictionary<string,double> staticArtsStrength,
        IReadOnlyDictionary<string,HashSet<string>> activeSuits,IReadOnlyDictionary<string,string> activeWeapons,
        EffectRecordCache? recordCache,bool readOnlyRecords=false,bool retainAnalyses=false)
        => BuildCore(sourceRecords,sourceHits,lastHitMs,staticArtsStrength,activeSuits,activeWeapons,recordCache,ownsHits:true,readOnlyRecords,retainAnalyses);

    private EffectWindowBuildResult BuildCore(IReadOnlyList<EvidenceObject> sourceRecords,IReadOnlyList<EvidenceObject> sourceHits,
        BigInteger lastHitMs,IReadOnlyDictionary<string,double>? staticArtsStrength,
        IReadOnlyDictionary<string,HashSet<string>>? activeSuits,IReadOnlyDictionary<string,string>? activeWeapons,
        EffectRecordCache? recordCache,bool ownsHits,bool readOnlyRecords=false,bool retainAnalyses=false)
    {
        var frozenRecords=ownsHits && readOnlyRecords && recordCache is not null;
        List<EvidenceObject> records=[];
        List<EvidenceObject> windows=[];
        Dictionary<EvidenceObject,EffectRecordAnalysis>? analyses=retainAnalyses ? new(ReferenceEqualityComparer.Instance) : null;
        foreach(var source in sourceRecords)
        {
            if(CatalogValues.Truth(source.Get("uid_observation_only")))
            {
                records.Add((EvidenceObject)(frozenRecords ? FrozenEvidence.Capture(source) : BuffEvidence.Clone(source)));
                continue;
            }
            EffectRecordAnalysis Analyze(EvidenceObject input)
            {
                var description=labels.Collect(input);
                var current=ownsHits ? specifications.CollectStaticOwned(description.Record) : specifications.CollectStatic(description.Record);
                var dynamic=ownsHits ? dynamics.CollectOwned(current.Record) : dynamics.Collect(current.Record);
                return new(dynamic.Record,description.Labels,current.Effects,dynamic.Effects);
            }
            var analyzed=recordCache is null ? Analyze(source)
                : frozenRecords ? recordCache.AnalyzeFrozen(this,source,Analyze)
                : ownsHits ? recordCache.AnalyzeOwned(this,source,Analyze) : recordCache.Analyze(this,source,Analyze);
            var record=analyzed.Record;
            records.Add(record);
            if(analyses is not null) analyses[record]=analyzed;
            if(analyzed.StaticEffects.Count==0 && analyzed.DynamicEffects.Count==0) continue;
            var key=Text(record.Get("event_key"));
            var provider=Text(record.Get("source_character_key"));
            if(!loadouts.MatchesSuit(key,provider,activeSuits) || !loadouts.MatchesWeapon(key,provider,activeWeapons)) continue;
            var start=Integer(Required(record,"ts_ms"));
            var root=roots.GetValueOrDefault(key);
            var end=BuffLifetime.EndAt(start,OptionalInteger(record.Get("end_ts_ms")),OptionalInteger(record.Get("raw_duration_ms")),lastHitMs,
                root?.Get("lifeType") is EvidenceText { Value:"Infinity" },OptionalInteger(record.Get("snapshot_end_ts_ms")));
            var endValue=new EvidenceInteger(end);
            var endLine=EvidenceJson.PythonEquals(record.Get("snapshot_end_ts_ms"),endValue) ? record.Get("snapshot_end_line_no")
                : EvidenceJson.PythonEquals(record.Get("end_ts_ms"),endValue) ? record.Get("end_line_no") : EvidenceNull.Value;
            var strength=staticArtsStrength?.GetValueOrDefault(provider) ?? 0;
            EvidenceObject Assemble()
            {
                var settings=root?.Get("stackingSettings") as EvidenceObject;
                var limit=packetDisplay.StackLimit(record)
                    ?? (approval.Match(record) is { } entry ? EffectStackPolicy.Positive(entry.Get("stack_limit")) : null)
                    ?? stacking.Limit(key,record.Get("bb_values") as EvidenceObject);
                Dictionary<string,EvidenceValue> fields=new(StringComparer.Ordinal)
                {
                    ["start_ts_ms"]=Required(record,"ts_ms"),["start_line_no"]=record.Get("line_no"),["end_ts_ms"]=endValue,["end_line_no"]=endLine,
                    ["duration_ms"]=new EvidenceInteger(BigInteger.Max(BigInteger.Zero,end-start)),
                    ["snapshot_end_ts_ms"]=record.Get("snapshot_end_ts_ms"),["snapshot_end_line_no"]=record.Get("snapshot_end_line_no"),
                    ["snapshot_update"]=new EvidenceBoolean(CatalogValues.Truth(record.Get("snapshot_update"))),
                    ["lifetime_mode"]=record.Get("lifetime_mode"),["lifetime_source"]=record.Get("lifetime_source"),
                    ["end_is_observation_boundary"]=new EvidenceBoolean(record.Get("end_ts_ms") is EvidenceNull
                        && record.Get("snapshot_end_ts_ms") is EvidenceNull && record.Get("lifetime_mode") is EvidenceText { Value:"Infinity" }),
                    ["uid"]=record.Get("uid"),["uid_aliases"]=new EvidenceArray([]),
                    ["source_character_key"]=Required(record,"source_character_key"),["source_character_name"]=Required(record,"source_character_name"),
                    ["source_static_arts_strength"]=new EvidenceReal(strength),
                    ["source_skill_key"]=record.Get("source_skill_key"),["source_skill_family_key"]=record.Get("source_skill_family_key"),
                    ["raw_source_character_key"]=record.Get("raw_source_character_key"),["raw_source_character_name"]=record.Get("raw_source_character_name"),
                    ["raw_source"]=record.Get("raw_source"),
                    ["target_character_key"]=RequiredAlternative(record,"target_character_key","target_enemy_key"),
                    ["target_character_name"]=RequiredAlternative(record,"target_character_name","target_enemy_name"),
                    ["target_player_key"]=Required(record,"target_character_key"),["target_enemy_key"]=Required(record,"target_enemy_key"),
                    ["owner_raw"]=record.Get("owner_raw"),["target_actor_id"]=record.Get("target_actor_id"),["source_actor_id"]=record.Get("source_actor_id"),
                    ["source_weapon_template"]=record.Get("source_weapon_template"),["event_key"]=Required(record,"event_key"),
                    ["event_name"]=analyzed.Labels.Count>0 ? new EvidenceText(string.Join(" / ",analyzed.Labels)) : Required(record,"event_key"),
                    ["bb_values"]=ownsHits && recordCache is not null ? CatalogValues.Or(record.Get("bb_values"),Empty)
                        : BuffEvidence.Clone(CatalogValues.Or(record.Get("bb_values"),Empty)),
                    ["zone_effects"]=Array(analyzed.StaticEffects),["dynamic_effects"]=Array(analyzed.DynamicEffects),
                    ["requires_enable_observation"]=new EvidenceBoolean(settings?.Get("stackingType") is EvidenceText { Value:"HighPriority" or "HighPriorityWithMaxStack" }),
                    ["modifier_count"]=new EvidenceInteger(Length(CatalogValues.Or(record.Get("attr_mods"),new EvidenceArray([])))),
                    ["enable_observations"]=ownsHits && recordCache is not null ? CatalogValues.Or(record.Get("enable_observations"),new EvidenceArray([]))
                        : BuffEvidence.Clone(CatalogValues.Or(record.Get("enable_observations"),new EvidenceArray([]))),
                    ["rdps_conflicting_enable_state"]=new EvidenceBoolean(CatalogValues.Truth(record.Get("rdps_conflicting_enable_state"))),
                    ["skill_family_key"]=EvidenceNull.Value,["stack_limit"]=limit is BigInteger count ? new EvidenceInteger(count) : EvidenceNull.Value,
                };
                return new(fields);
            }
            var window=ownsHits && recordCache is not null
                ? recordCache.AssembleWindow(analyzed,end,endLine,strength,Assemble,frozenRecords ? stacking : null) : Assemble();
            if(window is not null) windows.Add(window);
        }
        var ordinary=EffectWindowSet.Deduplicate(EffectWindowSet.Ordered(windows));
        var combo=ownsHits ? combos.BuildOwned(sourceHits,records) : combos.Build(sourceHits,records);
        // Summary ordinary windows already have immutable limits. Exact-hit combo windows
        // remain report-local; limit those without cloning every completed ordinary window.
        var comboWindows=frozenRecords ? EffectWindowSet.ApplyLimits(combo.Windows,stacking) : combo.Windows;
        var combined=comboWindows.Count==0 ? ordinary
            : EffectWindowSet.Deduplicate(EffectWindowSet.Ordered(ordinary.Concat(comboWindows)));
        return new(records,combo.Hits,frozenRecords ? EffectWindowSet.OrderLimited(combined) : EffectWindowSet.ApplyLimits(combined,stacking))
        { Analyses=analyses };
    }
}
