using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Runtime.Tracing;

internal static class ExportValues
{
    private static EvidenceValue Numbers(EvidenceValue value) => value switch
    {
        EvidenceObject obj when obj.Fields.Count == 1 && obj.Get("number_status") is EvidenceText status => new EvidenceReal(status.Value switch
        { "nan" => double.NaN, "positive_infinity" => double.PositiveInfinity, "negative_infinity" => double.NegativeInfinity, _ => throw new InvalidDataException("Unknown number status") }),
        EvidenceObject obj => new EvidenceObject(obj.Fields.ToDictionary(pair => pair.Key, pair => Numbers(pair.Value))),
        EvidenceArray array => new EvidenceArray(array.Items.Select(Numbers).ToArray()),
        _ => value,
    };
    public static EvidenceObject Data(TraceEvent item) => item.Data.Get("legacy_layout") is EvidenceObject
        ? TraceV1.ExportData(item.Data) : item.Type is "loadout_slot" or "loadout_stats"
            ? TraceLoadout.Legacy((EvidenceObject)Numbers(TraceModel.Data(item))) : (EvidenceObject)Numbers(TraceModel.Data(item));
}
