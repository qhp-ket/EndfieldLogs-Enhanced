using System.Numerics;
using EndfieldLogs.Capture.Cryptography;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Protocol;
using EndfieldLogs.Runtime.Sessions;
using Google.Protobuf;

internal static class SessionBusinessSpecs
{
    private static IMessage Parse(string name, string json) => JsonParser.Default.Parse(json, ProtocolCatalog.Messages[name]);
    private static DecodedMessage Decoded(string name, IMessage message) => new(name.StartsWith("CS_", StringComparison.Ordinal) ? "cs" : "sc",
        name, 1, new(), message, message.ToByteArray());

    public static void Run(Action<bool, string> check)
    {
        List<BattleLogEvent> events = [];
        GameSessionBusiness session = new("synthetic", events.Add);
        const string packet = """
            {"client_data":{"op_list":[
              {"op_type":"BattleOpTriggerKeyword","owner_id":"18446744073709551615","seq_id":1,"client_tick_tms":"100",
               "trigger_keyword_op_data":{"buff_inst_id":"18446744073709551614","modify":[{"config_index":0,"modify_value":0}]}},
              {"op_type":"BattleOpSetBuffEnableState","seq_id":2,"client_tick_tms":"100",
               "set_buff_enable_state_op_data":{"buff_inst_id_to_enable_state":{"18446744073709551614":false}}}
            ]}}
            """;
        var message = Parse("CS_BATTLE_OP", packet);
        check(session.Process(Decoded("CS_BATTLE_OP", message), 123), "The typed business entry handles a decoded battle packet");
        check(events.Select(row => row.EventType).SequenceEqual(["GAME_CLOCK_TICK", "BattleOpTriggerKeyword", "BattleOpSetBuffEnableState"]),
            "One client tick precedes ordered operations without duplicating the same tick in its packet");
        check(events[1].Payload["owner_id"] is "18446744073709551615"
            && events[1].Payload["buff_inst_id"] is "18446744073709551614",
            "Keyword owner and instance identities retain their complete uint64 decimal representation");
        check(events[2].Payload["states"] is Dictionary<string, object?> map && map["18446744073709551614"] is false,
            "An explicit disabled state survives the map and zero-default boundary");
        events.Clear();
        var atb = Parse("CS_BATTLE_OP", """
            {"client_data":{"op_list":[{"op_type":"BattleOpUpdateAtbInfo",
              "update_atb_info_op_data":{"atb_data":{"reason":"ChangeRecoverySpeed"}}}]}}
            """);
        session.Process(Decoded("CS_BATTLE_OP", atb), 124);
        check(events.Single().Payload["atb_recovery_speed"] is double speed && speed == 0,
            "A change-recovery-speed operation explicitly proves a zero speed");
        events.Clear();
        var trigger = Parse("CS_BATTLE_OP", """
            {"client_data":{"op_list":[{"owner_id":"11","op_type":"BattleOpTriggerAction",
              "trigger_action_op_data":{"template_id":{"type":"Skill","int_id":42},"action":{"action_id":0}}}]}}
            """);
        session.ObserveOwner(new(11, 111, "chr_test"), Parse("BATTLE_MGR_INFO", """
            {"skill_list":[{"inst_id":"7","skill_id":{"type":"Skill","int_id":42},"level":3}]}
            """));
        session.Process(Decoded("CS_BATTLE_OP", trigger), 125);
        var action = (Dictionary<string, object?>)events.Single().Payload["action"]!;
        check(action["action_id"] is BigInteger { IsZero: true } && events[0].Payload["action_runtime_case"] is null,
            "Proto3 scalar action index zero is present while an absent action oneof remains absent");
        check(events[0].Payload["level"] is BigInteger level && level == 3,
            "A trigger takes the level from its observed owner and exact template identity");
        var rows = session.ServerSkills(11);
        ((Dictionary<string, object?>)rows.Single())["level"] = -1;
        check(session.ServerSkills(11).Single()["level"] is BigInteger kept && kept == 3,
            "Returned server skill rows cannot mutate observed session state");

        // Exercise the real framing/decryption/registry path with synthetic login and session crypto only.
        static byte[] Frame(byte[] head, byte[] body) => [(byte)head.Length, (byte)body.Length, (byte)(body.Length >> 8), ..head, ..body];
        var key = Enumerable.Range(0, 32).Select(index => (byte)index).ToArray();
        byte[] nonce = new byte[12];
        var flow = new FlowKey(new("192.0.2.1", 30001), new("203.0.113.1", 30000));
        MessageRegistry registry = new("[{\"msg_id\":1,\"class_name\":\"CS_BATTLE_OP\"}]", "[]");
        RuntimeMetrics metrics = new();
        List<BattleLogEvent> emitted = [];
        GameSessionPipeline pipeline = new(flow, "wire-session", registry, bytes => bytes, _ => key, emitted.Add, metrics);
        pipeline.ProcessPacket(new(1000, flow.Client, flow.Server, 0, Frame([], []), "synthetic"));
        pipeline.ProcessPacket(new(1001, flow.Server, flow.Client, 0, Frame([], [0x1a, 1, 0, 0x22, 12, ..nonce]), "synthetic"));
        byte[] head = [8, 1];
        var encrypted = new Xxe1(key, nonce, 1).Process([..head, ..message.ToByteArray()]);
        var wire = Frame(encrypted[..head.Length], encrypted[head.Length..]);
        pipeline.ProcessPacket(new(1002, flow.Client, flow.Server, 3, wire[..4], "synthetic"));
        check(pipeline.IsLive && emitted.Count == 0, "A completed handshake with a partial message produces no premature business event");
        pipeline.ProcessPacket(new(1003, flow.Client, flow.Server, 7, wire[4..], "synthetic"));
        check(emitted.Count == 3 && emitted.All(row => row.TimestampMs == 1003 && row.SessionId == "wire-session")
            && metrics.MessagesDecoded == 1 && metrics.OutboundEventsEmitted == 3,
            "Encrypted split TCP input reaches ordered business events and updates both transport and event accounting");
        pipeline.ProcessPacket(new(1004, flow.Client, flow.Server, 3, wire, "synthetic"));
        check(emitted.Count == 3, "A retransmitted packet does not emit duplicate events");
        check(pipeline.UnhandledClasses.Count == 0, "The maintained operation path has no unhandled decoded class");
    }
}
