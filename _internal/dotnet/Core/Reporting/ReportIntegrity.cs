using System.Security.Cryptography;
using System.Text;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Reporting;

public static class ReportIntegrity
{
    public static string CanonicalJson(EvidenceValue value) => PythonSortedJson.Serialize(value, compact: true);
    public static string Sha256(EvidenceValue value) => Convert.ToHexStringLower(SHA256.HashData(new UTF8Encoding(false, true).GetBytes(CanonicalJson(value))));
}
