using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class IdentityLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timeZoneOffsetMinutes)
    {
        if (item.Type is not ("squad" or "actor_mapping" or "character_skills" or "identity_inference")) throw new InvalidDataException("Expected identity event");
        if (item.Data.Get("legacy_layout") is not EvidenceObject layout) throw new InvalidDataException("Identity event lacks legacy export layout");
        var data = Obj(TraceValueProjection.Restore(item.Data, layout));
        string body;
        if (item.Type == "squad")
        {
            var members = ((EvidenceArray)data.Get("members")).Items.Cast<EvidenceObject>().ToArray();
            body = $"SQUAD size={members.Length} members=[{string.Join(' ', members.Select(row => S(row.Get("template")) + "_" + S(row.Get("entity_id"))))}]";
        }
        else if (item.Type == "character_skills")
        {
            var skills = ((EvidenceArray)data.Get("skills")).Items.Cast<EvidenceObject>().ToArray();
            var owner = Truth(data.Get("entity_id")) ? S(data.Get("entity_id")) : "unknown";
            body = $"CHAR_SKILLS owner={S(data.Get("template"))} ownerId={owner} count={skills.Length} skills=[{string.Join(' ', skills.Select(row => S(row.Get("skill")) + ":" + S(row.Get("level"))))}]";
        }
        else if (item.Type == "identity_inference") body = $"IDENTITY_INFERENCE actorId={S(data.Get("entity_id"))} template={S(data.Get("template"))} source={S(data.Get("inference_source"))}";
        else body = $"ACTOR_MAP id={S(data.Get("entity_id"))} template={S(data.Get("template"))} source={S(data.Get("mapping_source"))} skill={S(data.Get("skill"))}";
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timeZoneOffsetMinutes)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return ["[" + stamp + "] " + body + "\n"];
    }
}
