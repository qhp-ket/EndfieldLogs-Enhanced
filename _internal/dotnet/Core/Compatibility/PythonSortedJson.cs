using System.Globalization;
using System.Text;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Sorted JSON text used inside Python effect identities (default separators, ensure_ascii=False).</summary>
public static class PythonSortedJson
{
    public static string Serialize(EvidenceValue value, bool compact = false) => value switch
    {
        EvidenceNull => "null",
        EvidenceBoolean flag => flag.Value ? "true" : "false",
        EvidenceInteger number => number.Value.ToString(CultureInfo.InvariantCulture),
        EvidenceReal number => double.IsNaN(number.Value) ? "NaN" : double.IsPositiveInfinity(number.Value) ? "Infinity"
            : double.IsNegativeInfinity(number.Value) ? "-Infinity" : PythonDisplay.Float(number.Value),
        EvidenceText text => Quote(text.Value),
        EvidenceArray array => "[" + string.Join(compact ? "," : ", ", array.Items.Select(item => Serialize(item, compact))) + "]",
        EvidenceObject obj => "{" + string.Join(compact ? "," : ", ", obj.Fields.OrderBy(pair => pair.Key, PythonDisplay.CodePointComparer)
            .Select(pair => Quote(pair.Key) + (compact ? ":" : ": ") + Serialize(pair.Value, compact))) + "}",
        _ => throw new InvalidDataException("Unsupported effect JSON value"),
    };

    private static string Quote(string text)
    {
        StringBuilder output = new("\"");
        foreach (var unit in text)
            output.Append(unit switch
            {
                '"' => "\\\"", '\\' => "\\\\", '\b' => "\\b", '\f' => "\\f", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t",
                < ' ' => "\\u" + ((int)unit).ToString("x4", CultureInfo.InvariantCulture), _ => unit.ToString(),
            });
        return output.Append('"').ToString();
    }
}
