using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class BuffPacketLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timezoneOffsetMinutes)
    {
        var data = (EvidenceObject)TraceValueProjection.Restore(item.Data, (EvidenceObject)item.Data.Get("legacy_layout"));
        string body;
        if (item.Type == "buff_unresolved")
        {
            var fields = StructuredBuffPacket.UnresolvedFields(data);
            body = $"BUFF_ACTION_UNRESOLVED uid={fields["uid"]} seq={fields["seq"]} triggerType={fields["triggerType"]} actionId={fields["actionId"]} ownerId={fields["ownerId"]} srcId={fields["srcId"]}";
        }
        else
        {
            var observation = BuffPacketWire.Observation(data);
            var marker = item.Type switch
            {
                "buff_creation" => "BUFF_CREATE_OBSERVED", "buff_origin" => "BUFF_ORIGIN", "buff_enable" => "BUFF_ENABLE",
                "buff_keyword" => Truth(observation.Get("validationErrors")) ? "BUFF_KEYWORD_UPDATE_UNRESOLVED" : "BUFF_KEYWORD_UPDATE",
                _ => throw new InvalidDataException("Expected BUFF packet event"),
            };
            body = marker + " " + Json(observation, ascii: item.Type == "buff_enable", finite: item.Type is "buff_creation" or "buff_keyword");
        }
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timezoneOffsetMinutes));
        return ["[" + stamp.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture) + "] " + body + "\n"];
    }
}
