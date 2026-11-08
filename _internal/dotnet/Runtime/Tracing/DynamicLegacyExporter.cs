using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class DynamicLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timezoneOffsetMinutes)
    {
        var data = ExportValues.Data(item);
        var observation = BuffPacketWire.Observation(data, pairs: false);
        var proof = Json(observation, finite: true);
        var body = item.Type switch
        {
            "blackboard_dynamic" => "BB_MODIFY_DYNAMIC " + string.Join(' ', DynamicWire.Fields(data).Select(pair => pair.Key + "=" + pair.Value)) + " identity=" + proof,
            "buff_attribute_refresh" or "blackboard_skill_setting" => (item.Type == "buff_attribute_refresh" ? "BUFF_ATTR_REFRESH" : "BB_READ_SKILL_SETTING")
                + (Truth(observation.Get("validationErrors")) ? "_UNRESOLVED " : " ") + proof,
            _ => throw new InvalidDataException("Expected dynamic blackboard event"),
        };
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timezoneOffsetMinutes));
        return ["[" + stamp.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture) + "] " + body + "\n"];
    }
}
