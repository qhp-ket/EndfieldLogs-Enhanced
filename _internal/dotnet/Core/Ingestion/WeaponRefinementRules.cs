using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Only exact observed skill levels and a bound gem snapshot can identify one refinement.</summary>
public sealed class WeaponRefinementRules(IReadOnlyDictionary<string, EvidenceObject> entries)
{
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static EvidenceObject Obj(EvidenceValue value) => value as EvidenceObject ?? Empty;
    private static IReadOnlyList<EvidenceValue> Items(EvidenceValue value) => value is EvidenceArray array ? array.Items : [];
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static bool IsEmptyId(EvidenceValue value) => value is EvidenceNull or EvidenceText { Value: "" } || EvidenceJson.PythonEquals(value, new EvidenceInteger(0));
    public string MainSkill(string weapon) => entries.TryGetValue(weapon, out var entry) ? Text(entry.Get("mainSkillId")) : "";

    public static WeaponRefinementRules Load(ResourceFiles resources)
    {
        var document = resources.ReadRelative("data/local_tables/weapon/refine_catalog.json") as EvidenceObject;
        return new(document?.Get("entries") is EvidenceObject values
            ? values.Fields.Where(pair => pair.Value is EvidenceObject).ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value, StringComparer.Ordinal) : []);
    }

    public BigInteger? Infer(string weapon, EvidenceValue? sourceSkills, EvidenceValue? gemTerms = null)
    {
        var entry = entries.GetValueOrDefault(weapon) ?? Empty;
        var accepted = new[] { Text(entry.Get("mainSkillId")), Text(entry.Get("mainSkillNumId")) }.Where(value => value.Length > 0).ToHashSet(StringComparer.Ordinal);
        BigInteger? gemCost = null;
        if (gemTerms is not null and not EvidenceNull)
        {
            if (gemTerms is not EvidenceArray { Items.Count: > 0 } terms) return null;
            Dictionary<BigInteger, BigInteger> costs = [];
            foreach (var value in terms.Items)
            {
                if (value is not EvidenceObject term || term.Get("term_num_id") is not EvidenceInteger { Value.Sign: > 0 } id
                    || term.Get("cost") is not EvidenceInteger cost || cost.Value < 0 || cost.Value > 6 || !costs.TryAdd(id.Value, cost.Value)) return null;
            }
            if (entry.Get("mainSkillGemTermNumId") is not EvidenceInteger termId
                || !CatalogValues.Truth(entry.Get("mainSkillBounds")) || !CatalogValues.Truth(entry.Get("refineBonusBounds"))) return null;
            gemCost = costs.GetValueOrDefault(termId.Value);
        }
        HashSet<BigInteger> values = [];
        if (CatalogValues.Truth(sourceSkills) && sourceSkills is not EvidenceArray and not EvidenceObject and not EvidenceText)
            throw new InvalidCastException("Source skills are not iterable");
        foreach (var skill in Items(sourceSkills ?? EvidenceNull.Value).OfType<EvidenceObject>())
        {
            var ids = new[] { "skill_id", "skillKey", "skill_str_id", "skill_int_id" }.Select(skill.Get)
                .Where(value => !IsEmptyId(value)).Select(CatalogValues.Text).ToHashSet(StringComparer.Ordinal);
            if (!ids.Overlaps(accepted)) continue;
            if (!ids.IsSubsetOf(accepted)) return null;
            var levelValue = skill.Get("level");
            var text = CatalogValues.Text(levelValue);
            if (levelValue is EvidenceBoolean || !SkillIdentityCatalog.IsDigitText(text)) return null;
            var level = Integer(levelValue);
            var key = level.ToString(System.Globalization.CultureInfo.InvariantCulture);
            var refine = Obj(entry.Get("skillLevelToRefine")).Get(key);
            if (gemCost is BigInteger cost)
            {
                if (!Items(entry.Get("supportedSkillLevels")).Any(value => EvidenceJson.PythonEquals(value, new EvidenceInteger(level)))) return null;
                HashSet<BigInteger> candidates = [];
                foreach (var (refineKey, bonusValue) in Obj(entry.Get("refineBonusBounds")).Fields)
                    foreach (var boundValue in Items(entry.Get("mainSkillBounds")))
                    {
                        var bonus = Obj(bonusValue);
                        var bound = Obj(boundValue);
                        var lower = Add(Add(bound.Get("lowerBound"), bonus.Get("lowerBound")), new EvidenceInteger(cost));
                        var upper = Add(bound.Get("upperBound"), bonus.Get("upperBound"));
                        if (EvidenceJson.PythonEquals(Minimum(lower, upper), new EvidenceInteger(level))) candidates.Add(Integer(new EvidenceText(refineKey)));
                    }
                refine = candidates.Count == 1 ? new EvidenceInteger(candidates.Single()) : EvidenceNull.Value;
            }
            if (refine is EvidenceNull) return null;
            values.Add(Integer(refine));
        }
        return values.Count == 1 ? values.Single() : null;
    }

    private static BigInteger Integer(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsFinite(real.Value) => new BigInteger(real.Value),
        EvidenceText text when Regex.IsMatch(text.Value.Trim(), @"\A[+-]?\d+(?:_\d+)*\z") && TraceFields.OptionalInteger(text.Value) is BigInteger integer => integer,
        EvidenceReal real when double.IsInfinity(real.Value) => throw new OverflowException("Cannot convert infinity"),
        EvidenceReal or EvidenceText => throw new FormatException("Invalid refinement integer"),
        _ => throw new InvalidCastException("Invalid refinement integer type"),
    };

    private static double Real(EvidenceValue value)
    {
        var number = value switch
        {
            EvidenceInteger integer => (double)integer.Value,
            EvidenceBoolean flag => flag.Value ? 1 : 0,
            EvidenceReal real => real.Value,
            _ => throw new InvalidCastException("Invalid refinement bound"),
        };
        if (!double.IsFinite(number) && value is EvidenceInteger) throw new OverflowException("int too large to convert to float");
        return number;
    }
    private static EvidenceValue Add(EvidenceValue left, EvidenceValue right)
    {
        if (left is not (EvidenceInteger or EvidenceReal or EvidenceBoolean) || right is not (EvidenceInteger or EvidenceReal or EvidenceBoolean))
            throw new InvalidCastException("Invalid refinement bound");
        return left is EvidenceReal || right is EvidenceReal ? new EvidenceReal(Real(left) + Real(right)) : new EvidenceInteger(Integer(left) + Integer(right));
    }
    private static EvidenceValue Minimum(EvidenceValue left, EvidenceValue right)
    {
        bool LessOrEqual(EvidenceValue a, EvidenceValue b)
        {
            if (a is EvidenceReal && b is EvidenceReal) return Real(a) <= Real(b);
            if (a is not EvidenceReal && b is not EvidenceReal) return Integer(a) <= Integer(b);
            if (a is EvidenceReal real && !double.IsFinite(real.Value) || b is EvidenceReal other && !double.IsFinite(other.Value)) return Real(a) <= Real(b);
            var integer = a is EvidenceReal ? Integer(b) : Integer(a);
            var number = a is EvidenceReal ? Real(a) : Real(b);
            var truncated = new BigInteger(number);
            var comparison = integer.CompareTo(truncated);
            if (comparison == 0) comparison = ((double)truncated).CompareTo(number);
            return a is EvidenceReal ? comparison >= 0 : comparison <= 0;
        }
        // Python min retains its first value when neither is strictly smaller.
        return LessOrEqual(right, left) && !EvidenceJson.PythonEquals(left, right) ? right : left;
    }
}
