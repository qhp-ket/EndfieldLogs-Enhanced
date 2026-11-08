using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

/// <summary>Independent entity text export, sharing only formatting with the legacy producer.</summary>
public static class EntityLegacyExporter
{
    internal static string AttributeTokens(EvidenceValue value) => string.Join(' ', Rows(value).Where(row => Int(row.Get("attr_type")) is not null).Select(row =>
    {
        var number = Float(row.Get("value")) ?? 0;
        return I(Int(row.Get("attr_type"))) + ":" + General(number) + "/" + General(Float(row.Get("basic_value")) ?? number);
    }));

    public static IReadOnlyList<string> Lines(TraceEvent item, int timeZoneOffsetMinutes)
    {
        if (item.Type is not ("entity_stats" or "entity_attributes" or "entity_value" or "entity_die" or "ability_spawn")) throw new InvalidDataException("Expected entity event");
        var data = ExportValues.Data(item);
        var attrs = AttributeTokens(data.Get("attributes"));
        static string Number(EvidenceValue value) => Float(value) is { } number ? PythonDisplay.Float(number) : "unknown";
        static string Vector(EvidenceValue value) => string.Join(',', new[] { "x", "y", "z" }.Select(axis => Number(Obj(value).Get(axis))));
        var detail = Obj(data.Get("detail"));
        var source = Id(detail.Get("source_actor_id")) ?? Int(data.Get("owner_id"));
        var body = item.Type switch
        {
            "entity_stats" => $"ENTITY_STATS id={S(data.Get("entity_id"))} template={S(data.Get("template"))} kind={S(data.Get("kind"))} level={Present(data.Get("level"))} hp={Present(data.Get("hp"))} attrs=[{attrs}]",
            "entity_attributes" => $"ENTITY_ATTR_UPDATE id={S(data.Get("entity_id"))} obj={Present(data.Get("object_id"))} template={S(data.Get("template"))} attrs=[{attrs}]",
            "entity_die" => "ENTITY_DIE id=" + S(data.Get("entity_id")),
            "entity_value" => $"ENTITY_VALUE seq={S(data.Get("operation_seq"))} id={I(Int(data.Get("entity_id")))} scene={Present(data.Get("scene_num_id"))} hp={Number(data.Get("hp"))} ult={Number(data.Get("ultimate_sp"))} delta={Number(data.Get("delta"))} srcType={Text(data.Get("source_type"), "unknown")} srcInt={I(Int(data.Get("source_int")))} origSrcType={Text(data.Get("original_source_type"), "unknown")} origSrcInt={I(Int(data.Get("original_source_int")))}",
            _ => $"ABILITY_ENTITY_SPAWN seq={I(Int(data.Get("operation_seq")) ?? 0)} tick={I(Int(data.Get("client_tick_ms")) ?? 0)} actionId={I(Int(data.Get("action_id")) ?? 0)} inst={I(Int(data.Get("event_inst_id")))} skill={Text(data.Get("skill"), "unknown_skill")} templateIntId={I(Int(data.Get("template_int_id")))} ownerId={I(Int(data.Get("owner_id")))} owner={Text(data.Get("owner"), "?")} sourceId={I(source)} source={Text(data.Get("source"), "?")} entityId={I(Int(detail.Get("entity_id")))} pos={Vector(detail.Get("position"))} rot={Vector(detail.Get("rotation"))}",
        };
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timeZoneOffsetMinutes)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return ["[" + stamp + "] " + body + "\n"];
    }
}
