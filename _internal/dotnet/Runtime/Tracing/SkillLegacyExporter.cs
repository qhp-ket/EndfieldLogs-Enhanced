using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class SkillLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timeZoneOffsetMinutes)
    {
        var data = ExportValues.Data(item);
        string L(string key, string fallback = "unknown") => SkillWire.Label(data, key, fallback);
        string Iden(string key) => SkillWire.IdentityToken(data.Get(key));
        string G(string key) => General(SkillWire.Number(data.Get(key)));
        var seq = SkillWire.Integer(data.Get("operation_seq")) ?? 0; var tick = SkillWire.Integer(data.Get("client_tick_ms")) ?? 0;
        string body;
        if (item.Type == "skill_cast")
        {
            var start = L("phase") == "start";
            var owner = start ? Iden("owner_id") : Present(data.Get("owner_id"));
            body = $"SKILL_CAST_{(start ? "START" : "END")} seq={seq} {(start ? "startMs" : "endMs")}={tick} inst={Iden("skill_inst_id")} owner={L("owner","?")} ownerId={owner} skill={L("skill","unknown_skill")} skillSource={L("skill_source")}" + (start ? $" captureMs={item.CapturedAtMs}" : "");
        }
        else if (item.Type == "atb")
            body = $"ATB_UPDATE seq={seq} tick={tick} owner={L("owner","?")} ownerId={Iden("owner_id")} reason={L("reason")} atb={G("value")} recoverySpeed={G("recovery_speed")} delta={G("delta")} source={L("source")} origSource={L("original_source")}";
        else if (item.Type == "poise")
            body = $"POISE_V1 seq={seq} tick={tick} type={L("modify_type")} value={G("value")} cur={G("current_value")} attacker={L("attacker","?")} attackerId={Iden("attacker_id")} ownerType={L("owner_type")} sourceType={L("source_type")} source={L("source")} sourceInt={Iden("source_int")} origSourceType={L("original_source_type")} origSource={L("original_source")} origSourceInt={Iden("original_source_int")} actionId={Iden("action_id")}";
        else throw new InvalidDataException("Expected skill/resource event");
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timeZoneOffsetMinutes)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return ["[" + stamp + "] " + body + "\n"];
    }
}
