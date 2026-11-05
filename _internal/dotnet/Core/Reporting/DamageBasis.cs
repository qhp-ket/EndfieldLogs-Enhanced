using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Packet-grounded totals and per-hit conservation, without modifying allocation.</summary>
public static class DamageBasis
{
    private static double Float(EvidenceValue value) => EffectIdentity.Float(CatalogValues.Or(value, new EvidenceReal(0)));
    private static EvidenceValue Round(double value) => new EvidenceReal(PythonDecimalRounding.Round(value, 4));
    private static EvidenceObject Contributions(EvidenceObject hit) => !CatalogValues.Truth(hit.Get("rdps_contributions")) ? BuffEvidence.Object()
        : hit.Get("rdps_contributions") as EvidenceObject ?? throw new InvalidDataException("Hit contributions must be an object");

    internal struct Accumulator
    {
        private int count, packetCount, finalCount, rawCount, cappedCount, mismatched;
        private double maxDelta;
        private PythonFloatSum.Accumulator finals, raw;

        internal void Add(EvidenceObject hit)
        {
            var delta = PythonFloatSum.Sum(Contributions(hit).Fields.Values.Select(Float)) - Float(hit.Get("hit_value"));
            var absolute = Math.Abs(delta);
            if (count == 0 || absolute > maxDelta) maxDelta = absolute;
            if (absolute > .01) mismatched++;
            if (hit.Get("packet_hit_value") is not EvidenceNull) packetCount++;
            if (hit.Get("packet_final_value") is not EvidenceNull)
            {
                finals.Add(EffectIdentity.Float(hit.Get("packet_final_value"))); finalCount++;
            }
            if (hit.Get("packet_raw_value") is not EvidenceNull)
            {
                raw.Add(EffectIdentity.Float(hit.Get("packet_raw_value"))); rawCount++;
            }
            if (EffectIdentity.Integer(CatalogValues.Or(hit.Get("overkill_damage"), new EvidenceInteger(0))) > 0) cappedCount++;
            count++;
        }

        internal readonly EvidenceObject Build(IReadOnlyDictionary<string, EvidenceValue> totals, BigInteger totalDamage)
        {
            var contributionTotal = PythonFloatSum.Sum(totals.Values.Select(Float));
            var delta = contributionTotal - EffectIdentity.Float(new EvidenceInteger(totalDamage));
            return BuffEvidence.Object(
            ("mode", new EvidenceText("packet_hp_loss")), ("rdps_mode", new EvidenceText("packet_hp_loss")),
            ("allocation_policy", new EvidenceText("log_marginal_v1")), ("allocation_policy_basis", new EvidenceText("accounting_convention")),
            ("source", new EvidenceText("HP_V2.hit with packet eHP overkill cap")), ("hit_count", new EvidenceInteger(count)),
            ("packet_grounded_hit_count", new EvidenceInteger(packetCount)), ("packet_hit_count", new EvidenceInteger(packetCount)),
            ("packet_final_value_count", new EvidenceInteger(finalCount)), ("packet_raw_value_count", new EvidenceInteger(rawCount)),
            ("formula_grounded_hit_count", new EvidenceInteger(0)), ("missing_packet_hit_count", new EvidenceInteger(count - packetCount)),
            ("overkill_capped_hit_count", new EvidenceInteger(cappedCount)),
            ("total_damage", new EvidenceInteger(totalDamage)), ("total_packet_final_value", finalCount > 0 ? Round(finals.Value) : EvidenceNull.Value),
            ("total_packet_raw_value", rawCount > 0 ? Round(raw.Value) : EvidenceNull.Value),
            ("total_rdps_contribution", Round(contributionTotal)), ("rdps_conservation_delta", Round(delta)),
            ("rdps_conservation_ok", new EvidenceBoolean(Math.Abs(delta) <= .01 && mismatched == 0)),
            ("hit_conservation_mismatch_count", new EvidenceInteger(mismatched)), ("max_hit_conservation_delta", Round(maxDelta)));
        }
    }

    public static EvidenceObject Build(IReadOnlyList<EvidenceObject> hits, IReadOnlyDictionary<string, EvidenceValue> totals, BigInteger totalDamage)
    {
        Accumulator aggregate = new();
        foreach (var hit in hits) aggregate.Add(hit);
        return aggregate.Build(totals, totalDamage);
    }
}
