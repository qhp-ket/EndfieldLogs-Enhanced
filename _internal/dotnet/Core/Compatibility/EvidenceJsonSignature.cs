using System.Globalization;
using System.Text.Json;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Stable internal signatures, preserving JSON number types and duplicate pairs.</summary>
public static class EvidenceJsonSignature
{
    public static string Sorted(EvidenceValue value) => value switch
    {
        EvidenceNull => "null",
        EvidenceBoolean flag => flag.Value ? "true" : "false",
        EvidenceInteger integer => "i:"+integer.Value.ToString(CultureInfo.InvariantCulture),
        EvidenceReal real => "f:"+PythonDisplay.String(real),
        EvidenceText text => JsonSerializer.Serialize(text.Value),
        EvidenceArray array => "["+string.Join(',', array.Items.Select(Sorted))+"]",
        EvidenceObject obj => "{"+string.Join(',', obj.Fields.OrderBy(pair => pair.Key, StringComparer.Ordinal)
            .Select(pair => JsonSerializer.Serialize(pair.Key)+":"+Sorted(pair.Value)))+"}",
        _ => throw new InvalidDataException("Unsupported JSON evidence"),
    };
}
