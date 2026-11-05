using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Partial equipment updates and authoritative weapon-instance replacement.</summary>
public static class LoadoutMerging
{
    private static readonly string[] WeaponFields = ["weapon_refine_evidence", "weapon_inst_id", "weapon_template",
        "weapon_name", "weapon_level", "weapon_refine", "weapon_refine_source", "weapon_break", "weapon_base_atk",
        "weapon_base_atk_lv1", "weapon_base_atk_max", "weapon_catalog_skilllist", "weapon_source_skills",
        "weapon_refine_stats", "gem_template", "gem_terms"];
    private static readonly HashSet<string> CompleteFields = ["equips", "suit_effects", "equip_suit_raw", "unresolved_equip_inst_ids"];
    private static readonly EvidenceArray Empty = new([]);

    internal static bool SameWeapon(EvidenceObject first,EvidenceObject second)=>
        WeaponFields.All(field=>EvidenceJson.PythonEquals(first.Get(field),second.Get(field)));

    internal static BigInteger Integer(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsNaN(real.Value) => throw new FormatException("Cannot convert NaN to integer"),
        EvidenceReal real when !double.IsFinite(real.Value) => throw new OverflowException("Cannot convert infinity to integer"),
        EvidenceReal real => new BigInteger(real.Value),
        EvidenceText text when Regex.IsMatch(text.Value.Trim(), @"\A[+-]?\d+(?:_\d+)*\z")
            && TraceFields.OptionalInteger(text.Value) is BigInteger integer => integer,
        EvidenceText => throw new FormatException("Invalid integer"),
        _ => throw new InvalidCastException("Cannot convert value to integer"),
    };
    private static object? FieldInput(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value, EvidenceReal real => real.Value,
        EvidenceText text => text.Value, EvidenceBoolean flag => flag.Value, _ => null,
    };

    public static EvidenceObject Merge(EvidenceObject previous, EvidenceObject update)
    {
        var fields = new Dictionary<string, EvidenceValue>(previous.Fields, StringComparer.Ordinal);
        var strong = previous.Get("weapon_refine_source") is EvidenceText { Value: "source_skill" };
        foreach (var (key, value) in update.Fields)
        {
            if (update.Get("equipment_snapshot_complete") is EvidenceBoolean { Value: true } && CompleteFields.Contains(key))
            { fields[key] = BuffEvidence.Clone(value); continue; }
            if (value is EvidenceNull or EvidenceText { Value.Length: 0 } or EvidenceArray { Items.Count: 0 } or EvidenceObject { Fields.Count: 0 }) continue;
            if (key == "equips" && value is EvidenceArray equips)
            {
                if (fields.GetValueOrDefault(key) is EvidenceArray { Items.Count: > 0 } current)
                {
                    foreach (var suit in CatalogValues.Iterable(CatalogValues.Or(update.Get("suit_effects"), Empty)).OfType<EvidenceObject>())
                        if (CatalogValues.Text(CatalogValues.Or(suit.Get("suit_id"), new EvidenceText(""))).Length > 0)
                            _ = Integer(CatalogValues.Or(suit.Get("piece_count"), new EvidenceInteger(0)));
                    fields[key] = MergeEquipment(current, equips);
                }
                else fields[key] = value;
                continue;
            }
            if (strong && (key == "weapon_refine" && update.Get("weapon_refine_source") is not EvidenceText { Value: "source_skill" }
                || key == "weapon_refine_source" && value is not EvidenceText { Value: "source_skill" })) continue;
            fields[key] = value;
        }
        return new(fields);
    }

    public static EvidenceArray MergeEquipment(EvidenceArray previous, EvidenceArray update)
    {
        var rows = previous.Items.OfType<EvidenceObject>().Select(row => new EvidenceObject(new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal))).ToList();
        Dictionary<BigInteger, int> slots = [];
        BigInteger? Slot(EvidenceObject row)
        {
            try { return Integer(row.Get("slot")); }
            catch (Exception error) when (error is FormatException or InvalidCastException) { return null; }
        }
        for (var index = 0; index < rows.Count; index++) if (Slot(rows[index]) is BigInteger slot) slots[slot] = index;
        foreach (var row in update.Items.OfType<EvidenceObject>())
        {
            var slot = Slot(row);
            if (slot is BigInteger valid && slots.TryGetValue(valid, out var index))
            {
                var fields = EvidenceJson.PythonEquals(rows[index].Get("item_id"), row.Get("item_id"))
                    ? new Dictionary<string, EvidenceValue>(rows[index].Fields, StringComparer.Ordinal) : new(StringComparer.Ordinal);
                foreach (var pair in row.Fields) fields[pair.Key] = pair.Value;
                rows[index] = new(fields);
            }
            else
            {
                rows.Add(new(new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal)));
                if (slot is BigInteger next) slots[next] = rows.Count-1;
            }
        }
        BigInteger SortKey(EvidenceObject row)
        {
            var text = row.Fields.TryGetValue("slot", out var value) ? CatalogValues.Text(value) : "";
            return SkillIdentityCatalog.IsDigitText(text.TrimStart('-')) ? Integer(row.Get("slot")) : new BigInteger(99);
        }
        return new(rows.OrderBy(SortKey).Cast<EvidenceValue>().ToArray());
    }

    public static IReadOnlyList<BigInteger> WeaponSourceSkillIds(EvidenceObject row)
    {
        var values = CatalogValues.Or(row.Get("weapon_source_skills"), row.Get("weapon_refine_stats"), Empty);
        var ids = CatalogValues.Iterable(values).OfType<EvidenceObject>()
            .Select(item => TraceFields.OptionalInteger(FieldInput(item.Get("skill_id"))) ?? BigInteger.Zero).Where(value => !value.IsZero);
        return PythonIntegerSetOrder.Distinct(ids);
    }

    public static EvidenceObject WithWeapon(EvidenceObject destination, EvidenceObject source)
    {
        var previousIds = WeaponSourceSkillIds(destination).ToHashSet();
        var fields = new Dictionary<string, EvidenceValue>(((EvidenceObject)BuffEvidence.Clone(destination)).Fields, StringComparer.Ordinal);
        foreach (var key in WeaponFields)
        {
            if (source.Fields.TryGetValue(key, out var value)) fields[key] = BuffEvidence.Clone(value);
            else fields.Remove(key);
        }
        var potential = Integer(CatalogValues.Or(destination.Get("potential"), new EvidenceInteger(0)));
        foreach (var key in new[] { "weapon_source_skills", "weapon_refine_stats" })
            if (fields.TryGetValue(key, out var value))
            {
                var items = CatalogValues.Iterable(CatalogValues.Or(value, Empty)).ToArray();
                if (value is EvidenceArray) fields[key] = new EvidenceArray(items.Select(item => item is EvidenceObject row
                    ? (EvidenceValue)new EvidenceObject(new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal) { ["potential_level"] = new EvidenceInteger(potential) }) : item).ToArray());
            }
        var ids = CatalogValues.Iterable(CatalogValues.Or(destination.Get("skill_int_ids"), Empty)).Select(Integer)
            .Where(value => !value.IsZero && !previousIds.Contains(value)).ToList();
        foreach (var id in WeaponSourceSkillIds(new(fields))) if (!ids.Contains(id)) ids.Add(id);
        fields["skill_int_ids"] = new EvidenceArray(ids.Select(id => (EvidenceValue)new EvidenceInteger(id)).ToArray());
        return new(fields);
    }

    public static EvidenceObject MergeTracked(EvidenceObject? previous, EvidenceObject row)
    {
        previous ??= new(new Dictionary<string, EvidenceValue>());
        var merged = Merge(previous, row);
        var before = CatalogValues.Text(CatalogValues.Or(previous.Get("weapon_inst_id"), new EvidenceText("")));
        var after = CatalogValues.Text(CatalogValues.Or(row.Get("weapon_inst_id"), new EvidenceText("")));
        return before.Length > 0 && after.Length > 0 && before != after ? WithWeapon(merged, row) : merged;
    }
}
