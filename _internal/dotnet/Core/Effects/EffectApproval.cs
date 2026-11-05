using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Reviewed identities authorize effects only when their observed source and recipient agree.</summary>
public sealed class EffectApproval(EvidenceObject registry, IReadOnlyDictionary<string, EvidenceObject> roots,
    IReadOnlyDictionary<string, string> buffNumbers, IReadOnlyDictionary<string, string> skillNumbers,
    BuffActionIndices? actions = null)
{
    private readonly BuffActionIndices actions = actions ?? new();
    private readonly EvidenceObject verified = Obj(registry.Get("verified_effects"));
    private readonly Lazy<(Dictionary<string, HashSet<string>> Exact, Dictionary<string, HashSet<string>> Runtime, Dictionary<string, int> Order)> index = new(() => Index(Obj(registry.Get("verified_effects"))));
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static EvidenceObject Obj(EvidenceValue value) => value as EvidenceObject ?? Empty;
    private static IReadOnlyList<EvidenceValue> Items(EvidenceValue value) => value is EvidenceArray array ? array.Items : [];
    private static bool Truth(EvidenceValue value) => CatalogValues.Truth(value);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static string Normalize(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("unknown_buff")));
    private static bool Is(EvidenceValue value, string text) => value is EvidenceText found && found.Value == text;
    private static bool Same(EvidenceValue left, EvidenceValue right) => EvidenceJson.PythonEquals(left, right);
    private static bool Contains(EvidenceValue values, EvidenceValue value) => Items(values).Any(item => Same(item, value));
    private static EvidenceArray Strings(IEnumerable<string> values) => new(values.Select(value => (EvidenceValue)new EvidenceText(value)).ToArray());
    private static EvidenceObject With(EvidenceObject value, params (string Key, EvidenceValue Value)[] fields)
    {
        var result = new Dictionary<string, EvidenceValue>(value.Fields, StringComparer.Ordinal);
        foreach (var (key, item) in fields) result[key] = item;
        return new(result);
    }
    private static (Dictionary<string, HashSet<string>> Exact, Dictionary<string, HashSet<string>> Runtime, Dictionary<string, int> Order) Index(EvidenceObject verified)
    {
        Dictionary<string, HashSet<string>> exact = new(StringComparer.Ordinal), runtime = new(StringComparer.Ordinal);
        static void Add(Dictionary<string, HashSet<string>> table, string identity, string key)
        {
            if (!table.TryGetValue(identity, out var keys)) table[identity] = keys = new(StringComparer.Ordinal);
            keys.Add(key);
        }
        foreach (var (key, value) in verified.Fields)
        {
            if (value is not EvidenceObject entry) continue;
            foreach (var identity in new[] { key }.Concat(Items(entry.Get("aliases")).Select(CatalogValues.Text))
                .Concat(Items(entry.Get("numeric_ids")).Select(CatalogValues.Text)).Where(value => value.Length > 0)) Add(exact, identity, key);
            foreach (var binding in Items(entry.Get("runtime_bindings")).OfType<EvidenceObject>())
                if (binding.Get("template") is EvidenceText template) Add(runtime, template.Value, key);
        }
        return (exact, runtime, verified.Fields.Keys.Select((key, order) => (key, order)).ToDictionary(row => row.key, row => row.order, StringComparer.Ordinal));
    }
    private IEnumerable<KeyValuePair<string, EvidenceValue>> Candidates(IEnumerable<string> identities, bool runtime)
    {
        HashSet<string> keys = new(StringComparer.Ordinal);
        var table = runtime ? index.Value.Runtime : index.Value.Exact;
        foreach (var identity in identities)
            if (table.TryGetValue(identity, out var found)) keys.UnionWith(found);
        // Resource declaration order decides between independently valid runtime bindings.
        return keys.OrderBy(key => index.Value.Order[key]).Select(key => new KeyValuePair<string, EvidenceValue>(key, verified.Get(key)));
    }
    private static bool PacketId(EvidenceValue value, bool requireText)
    {
        if (requireText && value is not EvidenceText) return false;
        var text = Text(value);
        return Regex.IsMatch(text, @"\A[1-9]\d*\z") && TraceFields.OptionalInteger(text) is BigInteger number && number < BigInteger.One << 64;
    }

    public static HashSet<string> BlackboardKeys(EvidenceObject record)
    {
        var keys = Items(record.Get("bb_keys")).Select(CatalogValues.Text).Where(value => value.Length > 0).ToHashSet(StringComparer.Ordinal);
        keys.UnionWith(Obj(record.Get("bb_values")).Fields.Keys.Where(value => value.Length > 0));
        return keys;
    }

    public static HashSet<string> EffectBlackboardKeys(EvidenceObject entry)
    {
        HashSet<string> result = new(StringComparer.Ordinal);
        foreach (var effect in Items(entry.Get("effects")).OfType<EvidenceObject>())
        {
            foreach (var key in new[] { "bb_key", "add_bb_key", "delay_bb_key", "max_bb_key" })
                if (Text(effect.Get(key)) is { Length: > 0 } value) result.Add(value);
            foreach (var key in new[] { "bb_keys", "required_bb_keys" })
                result.UnionWith(Items(effect.Get(key)).Select(CatalogValues.Text).Where(value => value.Length > 0));
        }
        return result;
    }

    public static bool BlackboardAllowed(EvidenceObject entry, EvidenceObject record)
    {
        if (entry.Get("allowed_bb_keys") is not EvidenceArray allowed) return true;
        var keys = allowed.Items.Select(CatalogValues.Text).Select(value => value.ToLowerInvariant()).ToHashSet(StringComparer.Ordinal);
        return keys.Contains("*") || BlackboardKeys(record).Select(value => value.ToLowerInvariant()).All(keys.Contains);
    }

    public static bool MatchesGuard(EvidenceObject entry, EvidenceObject record)
    {
        if (entry.Get("guard") is not EvidenceObject guard) return true;
        var source = Text(record.Get("source_character_key"));
        var target = Text(record.Get("target_character_key"));
        var mapping = Obj(record.Get("packet_mapping"));
        if (guard.Get("requires_actor_identity") is EvidenceBoolean { Value: true }
            && (source.Length == 0 || new[] { "uid", "source_actor_id", "target_actor_id" }.Any(key => !PacketId(record.Get(key), true))
                || Is(record.Get("uid"), "4294967295"))) return false;
        if (Is(guard.Get("target_kind"), "enemy")
            && (!Truth(record.Get("target_enemy_key")) || target.Length > 0 && !Same(new EvidenceText(target), record.Get("target_enemy_key"))
                || Truth(record.Get("target_player_key")))) return false;
        if (Is(guard.Get("target_kind"), "character") && (target.Length == 0 || Truth(record.Get("target_enemy_key")))) return false;
        var sourceActor = record.Get("source_actor_id");
        var targetActor = record.Get("target_actor_id");
        if (Is(guard.Get("recipient"), "self")
            && (source.Length == 0 || source != target || (Truth(sourceActor) || Truth(targetActor))
                && (!Truth(sourceActor) || !Truth(targetActor) || CatalogValues.Text(sourceActor) != CatalogValues.Text(targetActor)))) return false;
        if (Is(guard.Get("recipient"), "other_character")
            && (source.Length == 0 || target.Length == 0 || source == target || (Truth(sourceActor) || Truth(targetActor))
                && (!Truth(sourceActor) || !Truth(targetActor) || CatalogValues.Text(sourceActor) == CatalogValues.Text(targetActor)))) return false;
        var sourceGuard = Text(CatalogValues.Or(guard.Get("source_character_key"), guard.Get("source_character_id")));
        if (sourceGuard.Length > 0 && source != sourceGuard) return false;
        var character = Text(guard.Get("character_id"));
        if (character.Length > 0 && character != source && character != target) return false;
        var skill = Text(record.Get("source_skill_key"));
        var family = Text(CatalogValues.Or(record.Get("source_skill_family_key"), new EvidenceText(skill)));
        if (Text(guard.Get("source_skill_key")) is { Length: > 0 } skillGuard && skillGuard != skill) return false;
        if (Text(guard.Get("source_skill_family_key")) is { Length: > 0 } familyGuard && familyGuard != family) return false;
        if (Text(guard.Get("weapon_id")) is { Length: > 0 } weapon)
        {
            if (guard.Get("requires_source_loadout") is EvidenceBoolean { Value: true } && !Is(record.Get("source_weapon_template"), weapon)) return false;
            var mapped = Text(mapping.Get("weapon_id"));
            if (mapped.Length > 0 && mapped != weapon) return false;
            if (mapped.Length == 0 && !Normalize(record.Get("event_key")).StartsWith("buff_" + weapon, StringComparison.Ordinal)
                && !Normalize(record.Get("raw_event_key")).StartsWith("buff_" + weapon, StringComparison.Ordinal)) return false;
        }
        var suit = Text(guard.Get("suit_id"));
        return suit.Length == 0 || Text(mapping.Get("suit_id")) is not { Length: > 0 } mappedSuit || suit == mappedSuit;
    }

    public EvidenceObject? Match(BuffRecord record, bool requireGuard = true) => Match(Record(record), requireGuard);

    public EvidenceObject? Match(EvidenceObject record, bool requireGuard = true)
    {
        var candidates = new[] { Normalize(record.Get("event_key")), Normalize(record.Get("raw_event_key")) }.ToHashSet(StringComparer.Ordinal);
        candidates.Remove("");
        string Resolve(string value) => SkillIdentityCatalog.IsDigitText(value) ? buffNumbers.GetValueOrDefault(value, value) : value;
        var actual = candidates.Select(Resolve).ToHashSet(StringComparer.Ordinal);
        foreach (var (approvalKey, value) in Candidates(actual, true))
        {
            if (value is not EvidenceObject entry) continue;
            foreach (var binding in Items(entry.Get("runtime_bindings")).OfType<EvidenceObject>())
            {
                if (binding.Get("template") is not EvidenceText template || !actual.Contains(template.Value)
                    || !Same(binding.Get("decoder"), NativeDamageSemanticsBinding.Evidence)
                    || !Regex.IsMatch(Text(binding.Get("sourceRootSha256")), @"\A[0-9a-f]{64}\z")
                    || requireGuard && !MatchesGuard(entry, record)) continue;
                var origins = Items(record.Get("origin_observations"));
                var valid = origins.Count > 0;
                foreach (var originValue in origins)
                {
                    var origin = Obj(originValue);
                    var parent = Parent(origin, Is(binding.Get("parent_kind"), "Skill") ? skillNumbers : buffNumbers, false);
                    if (origin.Get("_boundCreateRecord") is not EvidenceBoolean { Value: true }
                        || Text(origin.Get("environmentType")).ToLowerInvariant() != Text(binding.Get("parent_kind")).ToLowerInvariant()
                        || !Same(parent, binding.Get("parent_template"))
                        || origin.Get("actionId") is not EvidenceInteger action || !Contains(binding.Get("create_actions"), action)
                        || !Same(origin.Get("triggerType"), new EvidenceInteger(0)) || !Same(origin.Get("buffUid"), record.Get("uid"))
                        || origin.Get("buffTemplate") is not EvidenceText buff || !candidates.Contains(buff.Value) && !actual.Contains(buff.Value)
                        || !Same(origin.Get("sourceActorId"), record.Get("source_actor_id")) || !Same(origin.Get("targetActorId"), record.Get("target_actor_id"))
                        || new[] { "buffUid", "sourceActorId", "targetActorId" }.Any(key => !PacketId(origin.Get(key), false))
                        || Is(binding.Get("recipient"), "other_character") && Same(origin.Get("sourceActorId"), origin.Get("targetActorId")))
                    { valid = false; break; }
                }
                if (!valid) continue;
                var remap = Obj(binding.Get("bb_key_remap"));
                var effects = Items(entry.Get("effects")).OfType<EvidenceObject>().Select(effect => (EvidenceValue)With(effect,
                    ("bb_key", effect.Get("bb_key") is EvidenceText key && remap.Fields.TryGetValue(key.Value, out var replacement) ? replacement : effect.Get("bb_key")))).ToArray();
                return With(entry, ("effects", new EvidenceArray(effects)), ("_rdps_whitelist_keys", Strings([approvalKey])),
                    ("_runtime_binding", BuffEvidence.Clone(binding)));
            }
        }

        List<(string Key, EvidenceObject Entry)> exact = [];
        var rawNumeric = Normalize(record.Get("raw_event_key"));
        foreach (var (key, value) in Candidates(candidates, false))
            if (value is EvidenceObject entry && (candidates.Contains(key)
                    || Items(entry.Get("aliases")).Select(CatalogValues.Text).Any(candidates.Contains)
                    || Items(entry.Get("numeric_ids")).Select(CatalogValues.Text).Contains(rawNumeric, StringComparer.Ordinal))
                && (!requireGuard || MatchesGuard(entry, record))) exact.Add((key, entry));
        if (exact.Count > 0)
        {
            var actualKey = Resolve(Normalize(record.Get("event_key")));
            var lifecycle = actualKey switch
            {
                "buff_chr_0023_antal_tageffect" => "buff_chr_0023_antal_normal_fragile",
                "buff_common_natural_natural_corrupt_triggered" => "buff_chr_0025_ardelia_dynamic_def_decrease",
                _ => exact.Count == 1 && exact[0].Entry.Get("lifecycle_only") is EvidenceBoolean { Value: true } ? exact[0].Key : null,
            };
            var lifecycleEntry = exact.FirstOrDefault(row => row.Key == lifecycle).Entry;
            if (lifecycleEntry is not null && roots.TryGetValue(actualKey, out var root) && EmptyModifiers(root))
            {
                var ignored = Items(lifecycleEntry.Get("ignored_bb_keys")).OfType<EvidenceText>().Select(key => key.Value).ToHashSet(StringComparer.Ordinal);
                ignored.UnionWith(EffectBlackboardKeys(lifecycleEntry));
                return With(lifecycleEntry, ("dynamic", new EvidenceBoolean(false)), ("effects", new EvidenceArray([])),
                    ("dynamic_effects", new EvidenceArray([])), ("ignored_bb_keys", Strings(ignored.Order(StringComparer.Ordinal))),
                    ("_rdps_whitelist_keys", Strings([lifecycle!])), ("_rdps_lifecycle_only", new EvidenceBoolean(true)));
            }
            const string corrosion = "buff_common_natural_natural_corrupt_do", ardelia = "buff_chr_0025_ardelia_dynamic_def_decrease";
            if (actualKey == corrosion && exact.Select(row => row.Key).ToHashSet().SetEquals([corrosion, ardelia])
                && verified.Get(corrosion) is EvidenceObject generic && verified.Get(ardelia) is EvidenceObject character
                && Same(generic.Get("effects"), character.Get("effects")) && Contains(character.Get("aliases"), new EvidenceText(corrosion)))
                return With(generic, ("_rdps_whitelist_keys", Strings(exact.Select(row => row.Key).Order(StringComparer.Ordinal))));
            return exact.Count == 1 || exact.Select(row => EvidenceJsonSignature.Sorted(row.Entry)).Distinct(StringComparer.Ordinal).Count() == 1
                ? With(exact[0].Entry, ("_rdps_whitelist_keys", Strings(exact.Select(row => row.Key).Order(StringComparer.Ordinal)))) : null;
        }
        List<EvidenceObject> prefixes = [];
        foreach (var key in candidates)
            foreach (var entry in Items(registry.Get("verified_prefixes")).OfType<EvidenceObject>())
                if (Text(entry.Get("prefix")) is { Length: > 0 } prefix && key.StartsWith(prefix, StringComparison.Ordinal)
                    && (!requireGuard || MatchesGuard(entry, record)) && BlackboardAllowed(entry, record)) prefixes.Add(entry);
        if (prefixes.Count > 0)
            return prefixes.Count == 1 || prefixes.Select(EvidenceJsonSignature.Sorted).Distinct(StringComparer.Ordinal).Count() == 1
                ? With(prefixes[0], ("_rdps_whitelist_keys", Strings(prefixes.Select(row => Text(row.Get("prefix"))).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal)))) : null;
        return MatchKeyword(record, verified, requireGuard);
    }

    private static EvidenceValue Parent(EvidenceObject origin, IReadOnlyDictionary<string, string> numbers, bool normalize)
    {
        var parent = origin.Get("templateStrId");
        var numeric = origin.Get("templateIntId");
        if (parent is EvidenceNull or EvidenceText { Value: "" } && numeric is EvidenceInteger integer && (!normalize || integer.Value.Sign >= 0))
            return numbers.TryGetValue(CatalogValues.Text(integer), out var mapped) ? new EvidenceText(mapped) : EvidenceNull.Value;
        return parent is EvidenceText { Value.Length: > 0 } && numeric is EvidenceNull ? parent : EvidenceNull.Value;
    }

    private static bool EmptyModifiers(EvidenceObject root) => Obj(root.Get("attributeModifier")).Get("attributeModifiers") is EvidenceArray { Items.Count: 0 }
        && root.Get("damageModifier") is EvidenceArray { Items.Count: 0 } && root.Get("globalModifier") is EvidenceArray { Items.Count: 0 };

    private EvidenceObject? MatchKeyword(EvidenceObject record, EvidenceObject verified, bool requireGuard)
    {
        if (record.Get("origin_observations") is not EvidenceArray { Items.Count: > 0 } origins
            || registry.Get("_keyword_buff_map") is not EvidenceObject keywordMap) return null;
        List<(string Key, EvidenceObject Entry)> projected = [];
        foreach (var value in origins.Items)
        {
            if (value is not EvidenceObject origin || origin.Get("_boundCreateRecord") is not EvidenceBoolean { Value: true }
                || !Same(origin.Get("buffTemplate"), record.Get("event_key")) && !Same(origin.Get("buffTemplate"), record.Get("raw_event_key"))
                || new[] { "buffUid", "sourceActorId", "targetActorId", "environmentInstId" }.Any(key => !PacketId(origin.Get(key), true))
                || !Same(origin.Get("buffUid"), record.Get("uid")) || !Same(origin.Get("sourceActorId"), record.Get("source_actor_id"))
                || !Same(origin.Get("targetActorId"), record.Get("target_actor_id")) || Text(origin.Get("environmentType")).ToLowerInvariant() != "buff"
                || Text(origin.Get("ownerType")) != "1" || Text(origin.Get("environmentInstId")) == "4294967295"
                || origin.Get("actionId") is not EvidenceInteger { Value.Sign: >= 0 } action) return null;
            foreach (var identity in new[] { record.Get("raw_event_key"), origin.Get("buffTemplate") })
            {
                if (identity is EvidenceNull or EvidenceText { Value: "" }) continue;
                var template = Normalize(identity);
                if (SkillIdentityCatalog.IsDigitText(template)) template = buffNumbers.GetValueOrDefault(template);
                if (template is null || template != Normalize(record.Get("event_key"))) return null;
            }
            if (Parent(origin, buffNumbers, true) is not EvidenceText parent) return null;
            var parents = verified.Fields.Where(pair => pair.Value is EvidenceObject entry
                && (pair.Key == parent.Value || Contains(entry.Get("aliases"), parent)) && (!requireGuard || MatchesGuard(entry, record)))
                .Select(pair => (pair.Key, Entry: (EvidenceObject)pair.Value)).ToArray();
            if (parents.Select(row => EvidenceJsonSignature.Sorted(row.Entry)).Distinct(StringComparer.Ordinal).Count() > 1
                || !roots.TryGetValue(parent.Value, out var root)) return null;
            var selected = actions.For(root).Actions.GetValueOrDefault(action.Value)?.Where(row => Text(row.Definition.Get("$type"))
                is "Beyond.Gameplay.Core.VulnerableAction.Data" or "Beyond.Gameplay.Core.EnhancedAction.Data").ToArray() ?? [];
            if (selected.Length != 1 || !selected[0].Enabled) return null;
            var definition = selected[0].Definition;
            var kind = Is(definition.Get("$type"), "Beyond.Gameplay.Core.VulnerableAction.Data") ? "Vulnerable" : "Enhanced";
            if (definition.Get("subType") is not EvidenceText subtype
                || Obj(keywordMap.Get(kind)).Get(subtype.Value) is not EvidenceText child || child.Value.Length == 0
                || child.Value != Normalize(record.Get("event_key"))) return null;
            var rate = Obj(definition.Get("rate"));
            if (rate.Get("useBlackboardKey") is not EvidenceBoolean { Value: true }
                || rate.Get("blackboardKey") is not EvidenceText { Value.Length: > 0 } rateKey) return null;
            var entry = parents.FirstOrDefault().Entry;
            var parentKeys = parents.Select(row => row.Key).Order(StringComparer.Ordinal).ToArray();
            var fromParent = entry is not null;
            var approvalKey = parentKeys.FirstOrDefault() ?? parent.Value;
            if (entry is null)
            {
                if (!roots.TryGetValue(child.Value, out var mainRoot)) return null;
                EvidenceValue visualChild;
                var config = Obj(definition.Get("childBuffId"));
                if (definition.Get("overrideChildBuffId") is EvidenceBoolean { Value: true } && config.Get("useBlackboardKey") is EvidenceBoolean { Value: false }) visualChild = config.Get("value");
                else if (definition.Get("overrideChildBuffId") is EvidenceBoolean { Value: false })
                {
                    var defaults = Items(mainRoot.Get("blackboard")).OfType<EvidenceObject>().Where(row => Is(row.Get("key"), "child_buff_id")).ToArray();
                    if (defaults.Length != 1 || defaults[0].Get("isDynamic") is not EvidenceBoolean { Value: false }) return null;
                    visualChild = defaults[0].Get("valueStr");
                }
                else return null;
                if (visualChild is not EvidenceText { Value.Length: > 0 } visual || verified.Get(visual.Value) is not EvidenceObject visualEntry
                    || !roots.TryGetValue(visual.Value, out var visualRoot) || !EmptyModifiers(visualRoot)) return null;
                List<(EvidenceObject Definition, bool Enabled)> forwards = [];
                foreach (var creation in actions.For(mainRoot).Creations)
                    foreach (var created in Items(creation.Definition.Get("buffs")).OfType<EvidenceObject>())
                        if (created.Get("readIdFromBlackboard") is EvidenceBoolean { Value: true } && Is(created.Get("buffIdKey"), "child_buff_id"))
                            forwards.Add((created, creation.Enabled));
                if (forwards.Count != 1 || !forwards[0].Enabled || forwards[0].Definition.Get("assignBlackboard") is not EvidenceBoolean { Value: true }) return null;
                foreach (var key in new[] { "rate", "duration" })
                {
                    var assigned = Items(forwards[0].Definition.Get("assignItems")).OfType<EvidenceObject>().Where(row => Is(row.Get("targetKey"), key)).ToArray();
                    if (assigned.Length != 1 || assigned[0].Get("useDirectValue") is not EvidenceBoolean { Value: false } || !Is(assigned[0].Get("inputValueKey"), key)) return null;
                }
                var element = subtype.Value switch { "All" => "all", "Spell" => "spell", "Physical" => "physical", "Natural" => "natural", "Fire" => "fire", "Crystal" => "cryst", "Pulse" => "pulse", _ => null };
                if (Items(visualEntry.Get("effects")).OfType<EvidenceObject>().Any(effect => !Is(effect.Get("zone"), kind == "Vulnerable" ? "fragile" : "amp")
                    || !Same(CatalogValues.Or(effect.Get("element"), new EvidenceText("all")), element is null ? EvidenceNull.Value : new EvidenceText(element)))) return null;
                entry = visualEntry;
                approvalKey = visual.Value;
            }
            if (requireGuard && !MatchesGuard(entry, record)) return null;
            if (parent.Value == "buff_chr_0023_antal_tageffect" && parentKeys.SequenceEqual(["buff_chr_0023_antal_normal_fragile"]))
                entry = With(entry, ("dynamic", new EvidenceBoolean(Truth(record.Get("keyword_rate_snapshots")))),
                    ("effects", new EvidenceArray(new[] { "pulse", "fire" }.Select(element => (EvidenceValue)new EvidenceObject(new Dictionary<string, EvidenceValue>
                    { ["zone"] = new EvidenceText("fragile"), ["element"] = new EvidenceText(element), ["bb_key"] = new EvidenceText("rate") })).ToArray())));
            var specs = Items(entry.Get("effects"));
            if (specs.Count == 0 || specs.OfType<EvidenceObject>().Any(spec => fromParent && !EffectInputKeys(spec, true).Contains(rateKey.Value)
                || !EffectInputKeys(spec, false).Contains("rate"))) return null;
            foreach (var key in fromParent ? parentKeys : [approvalKey]) projected.Add((key, entry));
        }
        return projected.Count > 0 && (projected.Count == 1
            || projected.Select(row => EvidenceJsonSignature.Sorted(row.Entry)).Distinct(StringComparer.Ordinal).Count() == 1)
            ? With(projected[0].Entry, ("_rdps_whitelist_keys", Strings(projected.Select(row => row.Key).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal))),
                ("_keyword_origin", BuffEvidence.Clone(origins))) : null;
    }

    private static HashSet<string> EffectInputKeys(EvidenceObject effect, bool origin)
    {
        var keys = Items(effect.Get("bb_keys")).OfType<EvidenceText>().Select(value => value.Value).ToHashSet(StringComparer.Ordinal);
        if (effect.Get("bb_key") is EvidenceText key) keys.Add(key.Value);
        if (origin) keys.UnionWith(Items(effect.Get("origin_bb_keys")).OfType<EvidenceText>().Select(value => value.Value));
        return keys;
    }

    private static EvidenceObject Record(BuffRecord record)
    {
        EvidenceValue TextOrNull(string? value) => value is null ? EvidenceNull.Value : new EvidenceText(value);
        return new(new Dictionary<string, EvidenceValue>
        {
            ["uid"] = new EvidenceText(record.Uid), ["event_key"] = new EvidenceText(record.EventKey), ["raw_event_key"] = new EvidenceText(record.RawEventKey),
            ["source_character_key"] = TextOrNull(record.SourceCharacterKey), ["target_character_key"] = TextOrNull(record.TargetCharacterKey),
            ["target_enemy_key"] = TextOrNull(record.TargetEnemyKey), ["source_actor_id"] = TextOrNull(record.SourceActorId), ["target_actor_id"] = TextOrNull(record.TargetActorId),
            ["source_weapon_template"] = TextOrNull(record.SourceWeaponTemplate), ["source_skill_key"] = TextOrNull(record.SourceSkillKey),
            ["source_skill_family_key"] = TextOrNull(record.SourceSkillFamilyKey), ["packet_mapping"] = record.PacketMapping is { } mapping ? mapping : EvidenceNull.Value,
            ["bb_keys"] = Strings(record.BlackboardKeys), ["bb_values"] = new EvidenceObject(record.BlackboardValues.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceReal(pair.Value))),
            ["origin_observations"] = record.OriginObservations is { } origins ? new EvidenceArray(origins.Select(row => (EvidenceValue)row.Evidence).ToArray()) : EvidenceNull.Value,
            ["keyword_rate_snapshots"] = record.KeywordRateSnapshots is { } snapshots ? new EvidenceArray(snapshots.Select(row => (EvidenceValue)row.Evidence).ToArray()) : EvidenceNull.Value,
        });
    }
}
