using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Runtime.Tracing;

/// <summary>Independent old-log rendering; never used as structured ingestion.</summary>
public static class BuffLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timezoneOffsetMinutes)
    {
        var data = ExportValues.Data(item);
        var uid = SkillWire.IdentityToken(data.Get("buff_inst_id"));
        var body = item.Type switch
        {
            "buff_start" => $"BUFF_START #{PythonDisplay.String(data.Get("buff_seq"))} id=\"{SkillWire.Label(data, "template", "unknown_buff")}\" uid={uid} "
                + $"owner={SkillWire.Label(data, "owner", "?")} src={SkillWire.Label(data, "source", "?")} "
                + $"ownerId={SkillWire.IdentityToken(data.Get("target_id"))} srcId={SkillWire.IdentityToken(data.Get("source_actor_id"))} "
                + "dur=unknown lifeT=unknown passed=unknown enh=unknown",
            "buff_end" => $"BUFF_END #{PythonDisplay.String(data.Get("buff_seq"))} id=\"{SkillWire.Label(data, "template", data.Get("template_status") is EvidenceText { Value: "unresolved" } ? "unknown_buff" : "")}\" uid={uid}",
            "buff_blackboard" => $"BB[{uid}]: " + string.Join(' ', ((EvidenceArray)data.Get("values")).Items.Cast<EvidenceObject>()
                .Select(row => ((EvidenceText)row.Get("key")).Value + "=" + TraceData.General(SkillWire.Number(row.Get("value"))))),
            _ => throw new InvalidDataException("Expected BUFF lifecycle or blackboard event"),
        };
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timezoneOffsetMinutes));
        return ["[" + stamp.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture) + "] " + body + "\n"];
    }
}
