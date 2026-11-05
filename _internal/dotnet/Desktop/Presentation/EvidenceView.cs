using System.Globalization;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Desktop.Presentation;

internal static class EvidenceView
{
    public static IEnumerable<EvidenceObject> Rows(EvidenceValue? value) => value is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : [];
    public static string Text(EvidenceValue? value, string fallback = "") => value is EvidenceText text ? text.Value : fallback;
    public static double? Number(EvidenceValue? value) => value switch { EvidenceReal real => real.Value, EvidenceInteger integer => (double)integer.Value, _ => null };
    public static string Exact(EvidenceValue? value) => value is null or EvidenceNull ? "未知" : PythonDisplay.String(value);
    public static string Format(EvidenceValue? value, string format = "N0") => Number(value) is { } number && double.IsFinite(number)
        ? number.ToString(format, CultureInfo.CurrentCulture) : "未知";
    public static EvidenceObject Empty() => new(new Dictionary<string, EvidenceValue>());
}
