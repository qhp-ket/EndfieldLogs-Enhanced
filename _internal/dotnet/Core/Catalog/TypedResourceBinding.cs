using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Catalog;

internal static class TypedResourceBinding
{
    public static EvidenceObject Evidence { get; } = new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
    {
        ["gameAssemblySha256"] = new EvidenceText("ab00f1c41e13edf9816f142b166e3c2536d5bc7707992c39e5ed52d1cc888e2c"),
        ["metadataSha256"] = new EvidenceText("461321d9dca6a832bce3bd2390402efc7c83c145554e97a8058bb68fbec1c8ca"),
        ["schemaSha256"] = new EvidenceText("42bd4483f3f6f5937fd4a1f8bd43f3152ee62d33e259c67260a4be25a8a4bcf2"),
    });

    public static bool Matches(EvidenceObject decoder) =>
        Evidence.Fields.All(pair => EvidenceJson.PythonEquals(decoder.Get(pair.Key), pair.Value));
}
