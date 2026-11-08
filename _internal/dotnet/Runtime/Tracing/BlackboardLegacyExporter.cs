using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class BlackboardLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timezoneOffsetMinutes)
    {
        var data = ExportValues.Data(item);
        string body;
        if (item.Type == "ink_release") body = "INK_RELEASE " + Json(BlackboardWire.ReleaseObservation(data), finite: true);
        else
        {
            var fields = BlackboardWire.Fields(data);
            string marker;
            if (item.Type == "blackboard_calculation")
            {
                marker = "BB_SIMPLE_CALC"; fields["key"] = S(data.Get("key")); fields["final"] = PythonDisplay.Float(Float(data.Get("final_value"))!.Value);
                foreach (var (input, output) in new[] { ("value_a", "valueA"), ("value_b", "valueB") })
                    if (data.Fields.ContainsKey(input)) fields[output] = PythonDisplay.Float(Float(data.Get(input))!.Value);
            }
            else if (item.Type == "blackboard_modify")
            {
                marker = "BB_MULTI_MODIFY";
                if (data.Fields.ContainsKey("key")) fields["key"] = S(data.Get("key"));
                if (data.Fields.ContainsKey("value")) fields["value"] = General(Float(data.Get("value")));
            }
            else { marker = "BB_SET_PRESET"; fields["modifiedValue"] = Quote(S(data.Get("modified_value"))); }
            body = marker + " " + string.Join(' ', fields.Select(pair => pair.Key + "=" + pair.Value));
        }
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timezoneOffsetMinutes));
        return ["[" + stamp.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture) + "] " + body + "\n"];
    }
}
