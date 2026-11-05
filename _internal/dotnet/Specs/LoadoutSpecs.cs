using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class LoadoutSpecs
{
    public static void Run(Action<bool, string> check)
    {
        static EvidenceObject Row(string json) => (EvidenceObject)EvidenceJson.Parse(json);
        static LoadoutObservations Stream(PartyObservationState? party = null,
            IReadOnlyDictionary<string, EvidenceObject>? overrides = null)
        {
            SkillIdentityCatalog skills = new(new Dictionary<string, string>(),
                new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
            LoadoutSnapshotParser parser = new(new Dictionary<string, EvidenceObject>(),
                new Dictionary<string, EvidenceObject>(), new Dictionary<string, EvidenceObject>(),
                new(new Dictionary<string, EvidenceObject>()), skills, key => key);
            return new(parser, skills, party, overrides);
        }
        const string owner = "chr_0001_alpha";
        const string slot = " LOADOUT slot=0 char=chr_0001_alpha weaponTemplate=wpn_test weaponInstId=11 equipSuit={suit_a:3}";
        PartyObservationState party = new();
        var first = Stream(party);
        var other = Stream();
        first.Observe(slot, 1, 100);
        var previous = first.Groups.Single().Rows[owner];
        var signature = EvidenceJsonSignature.Sorted(previous);
        first.Observe(slot.Replace("weaponInstId=11", "weaponInstId=12", StringComparison.Ordinal), 2, 200);
        check(ReferenceEquals(first.Party.Loadouts, party.Loadouts)
            && party.Loadouts[owner].Get("weapon_inst_id") is EvidenceText { Value: "12" },
            "Equipment observations write the party state consumed by hits and BUFFs");
        check(first.Groups.Count == 2 && EvidenceJsonSignature.Sorted(previous) == signature,
            "Later equipment observations preserve previous group snapshots");
        check(other.Party.Loadouts.Count == 0 && other.Groups.Count == 0 && other.CurrentGroup is null,
            "Equipment streams isolate current state and observation groups");

        var source = Row("""{"weapon_template":"wpn_override","weapon_source_skills":[{"skill_id":"17","bb":{"rate":0.2}}]}""");
        var overridden = Stream(overrides: new Dictionary<string, EvidenceObject> { [owner] = source });
        var sourceSkill = (EvidenceObject)((EvidenceArray)source.Get("weapon_source_skills")).Items[0];
        var overrideSkill = (EvidenceObject)((EvidenceArray)overridden.WeaponOverrides[owner].Get("weapon_source_skills")).Items[0];
        var partySkill = (EvidenceObject)((EvidenceArray)overridden.Party.Loadouts[owner].Get("weapon_source_skills")).Items[0];
        check(!ReferenceEquals(sourceSkill.Get("bb"), overrideSkill.Get("bb"))
            && !ReferenceEquals(overrideSkill.Get("bb"), partySkill.Get("bb")),
            "Initial overrides, party equipment and caller evidence own separate nested containers");
        overridden.Observe(slot, 3, 300);
        check(overridden.Party.ActiveWeapons[owner] == "wpn_override"
            && overridden.Groups[0].Rows[owner].Get("weapon_template") is EvidenceText { Value: "wpn_override" },
            "Authoritative weapon overrides apply to active bindings and historical groups");

        var oldWeapon = Row("""{"potential":2,"weapon_inst_id":"11","weapon_template":"old","gem_template":"old_gem","weapon_source_skills":[{"skill_id":"17"}],"skill_int_ids":[5,17]}""");
        var newWeapon = Row("""{"weapon_inst_id":"12","weapon_template":"new","weapon_source_skills":[{"skill_id":"18","bb":{"rate":0.3}}]}""");
        var original = EvidenceJsonSignature.Sorted(oldWeapon)+EvidenceJsonSignature.Sorted(newWeapon);
        var merged = LoadoutMerging.MergeTracked(oldWeapon, newWeapon);
        var mergedSource = (EvidenceObject)((EvidenceArray)merged.Get("weapon_source_skills")).Items[0];
        check(merged.Get("gem_template") is EvidenceNull && mergedSource.Get("potential_level") is EvidenceInteger { Value: var level } && level == 2,
            "Weapon instance replacement removes stale gem evidence and applies destination potential");
        var replaced = LoadoutMerging.WithWeapon(oldWeapon, newWeapon);
        check(((EvidenceArray)replaced.Get("skill_int_ids")).Items.Select(value => ((EvidenceInteger)value).Value).SequenceEqual(new System.Numerics.BigInteger[] { 5, 18 }),
            "Weapon replacement removes old source skills without removing character skills");
        check(!ReferenceEquals(mergedSource.Get("bb"), ((EvidenceObject)((EvidenceArray)newWeapon.Get("weapon_source_skills")).Items[0]).Get("bb"))
            && original == EvidenceJsonSignature.Sorted(oldWeapon)+EvidenceJsonSignature.Sorted(newWeapon),
            "Weapon replacement clones nested evidence and preserves both inputs");

        var complete = Row("""{"equipment_snapshot_complete":true,"equips":[{"slot":0,"item_id":"new","stats":[1]}],"suit_effects":[]}""");
        var completeMerged = LoadoutMerging.Merge(Row("""{"equips":[{"slot":0,"item_id":"old"}],"suit_effects":[{"suit_id":"old"}]}"""), complete);
        check(((EvidenceArray)completeMerged.Get("suit_effects")).Items.Count == 0
            && !ReferenceEquals(completeMerged.Get("equips"), complete.Get("equips")),
            "Complete equipment snapshots clear old suits and own their row containers");
    }
}
