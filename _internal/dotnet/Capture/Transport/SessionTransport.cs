using System.Numerics;
using EndfieldLogs.Capture.Cryptography;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Core.Models;

namespace EndfieldLogs.Capture.Transport;

/// <summary>Ordered TCP-to-message transport. Business state and trace formatting are downstream owners.</summary>
public sealed class SessionTransport
{
    private readonly FlowKey flow;
    private readonly string sessionId;
    private readonly MessageRegistry registry;
    private readonly Func<byte[], byte[]> decryptLogin, decryptKey;
    private readonly Action<DecodedMessage, long> onMessage;
    private readonly Action<BattleLogEvent> onWarning;
    private readonly Action<Dictionary<string, object?>>? onDebug;
    private readonly RuntimeMetrics metrics;
    private readonly TcpStreamReassembler clientReassembler = new(), serverReassembler = new();
    private readonly SessionFrameBuffer clientBuffer = new(), serverBuffer = new();
    private readonly Queue<(SessionFrame Frame, long TimestampMs)> pendingClient = [];
    private readonly Dictionary<string, (long Expected, long Lowest, long Missing)> gaps = new(StringComparer.Ordinal);
    private readonly MultiPackAssembler multiPack;
    private readonly Dictionary<string, long> classCounts = new(StringComparer.Ordinal);
    private Xxe1? clientCipher, serverCipher;
    private bool clientLoginDone, serverLoginDone, startupWarning;
    private long? firstPacketMs;
    public HashSet<string> ReliabilityFlags { get; } = new(StringComparer.Ordinal);
    public int StartupGapCount { get; private set; }
    public long MaximumStartupGapBytes { get; private set; }
    public bool IsLive => clientLoginDone && serverLoginDone && clientCipher is not null && serverCipher is not null;

    public SessionTransport(FlowKey flow, string sessionId, MessageRegistry registry,
        Func<byte[], byte[]> decryptLogin, Func<byte[], byte[]> decryptKey,
        Action<DecodedMessage, long> onMessage, Action<BattleLogEvent> onWarning,
        RuntimeMetrics metrics, Action<Dictionary<string, object?>>? onDebug=null)
    {
        this.flow=flow; this.sessionId=sessionId; this.registry=registry; this.decryptLogin=decryptLogin;
        this.decryptKey=decryptKey; this.onMessage=onMessage; this.onWarning=onWarning; this.metrics=metrics; this.onDebug=onDebug;
        multiPack = new(progress => Debug("debug_multipack_pending", progress.TimestampMs, progress.Key.Direction,
            new() { ["msg_id"]=progress.Key.MessageId, ["seqid"]=progress.SequenceId, ["base_seqid"]=progress.Key.BaseSequenceId,
                ["total_pack_count"]=progress.TotalPackCount, ["current_pack_index"]=progress.CurrentPackIndex,
                ["received_indexes"]=progress.ReceivedIndexes }));
    }

    public Dictionary<string, object?> Status() => new()
    {
        ["client_login_done"]=clientLoginDone, ["server_login_done"]=serverLoginDone,
        ["client_cipher_ready"]=clientCipher is not null, ["server_cipher_ready"]=serverCipher is not null,
        ["client_buffer_len"]=clientBuffer.Count, ["server_buffer_len"]=serverBuffer.Count,
        ["pending_client_session_frames"]=pendingClient.Count,
        ["decoded_class_counts"]=classCounts.OrderByDescending(row => row.Value).Take(30).ToDictionary(row => row.Key, row => row.Value),
        ["reliability_flags"]=ReliabilityFlags.Order(StringComparer.Ordinal).ToArray(),
        ["startup_tcp_gap_count"]=StartupGapCount, ["startup_tcp_gap_max_missing_bytes"]=MaximumStartupGapBytes,
        ["tcp_gap"]=gaps.ToDictionary(row => row.Key, row => new Dictionary<string, object?>
            { ["missing_from_seq"]=row.Value.Expected, ["next_seen_seq"]=row.Value.Lowest, ["missing_bytes"]=row.Value.Missing }),
    };

    private void Debug(string type, long timestampMs, string direction, Dictionary<string, object?> fields)
    {
        if (onDebug is null) return;
        Dictionary<string, object?> record = new() { ["type"]=type, ["session_id"]=sessionId,
            ["timestamp_ms"]=timestampMs, ["direction"]=direction };
        foreach (var field in fields) record[field.Key]=field.Value;
        onDebug(record);
    }

    private void NoteGap(long timestampMs, string direction, long missing)
    {
        if (firstPacketMs is null || timestampMs-firstPacketMs > 5000) return;
        StartupGapCount++;
        MaximumStartupGapBytes=Math.Max(MaximumStartupGapBytes,missing);
        ReliabilityFlags.Add("startup_tcp_gap");
        if (MaximumStartupGapBytes >= 4096) ReliabilityFlags.Add("startup_tcp_gap_large");
        if (startupWarning) return;
        startupWarning=true;
        metrics.OutboundEventsEmitted++;
        onWarning(new(sessionId,timestampMs,"SESSION_WARNING",new Dictionary<string, object?>
        { ["kind"]="startup_tcp_gap", ["direction"]=direction, ["missing_bytes"]=missing, ["startup_tcp_gap_count"]=StartupGapCount }));
    }

    public void Process(CapturedPacket packet)
    {
        firstPacketMs ??= packet.TimestampMs;
        var direction = packet.Src == flow.Client ? "cs" : "sc";
        var reassembler = direction == "cs" ? clientReassembler : serverReassembler;
        var buffer = direction == "cs" ? clientBuffer : serverBuffer;
        var chunks = reassembler.Accept(packet.Seq,packet.Payload);
        if (chunks.Count > 0) gaps.Remove(direction);
        else if (reassembler.GapState() is { } gap && (!gaps.TryGetValue(direction,out var prior) || prior != gap))
        {
            gaps[direction]=gap;
            NoteGap(packet.TimestampMs,direction,gap.Missing);
            Debug("debug_tcp_gap",packet.TimestampMs,direction,new()
            { ["missing_from_seq"]=gap.Expected, ["next_seen_seq"]=gap.Lowest, ["missing_bytes"]=gap.Missing,
                ["packet_seq"]=packet.Seq, ["packet_len"]=packet.Payload.Length });
        }
        foreach (var chunk in chunks) { buffer.Append(chunk); Drain(direction,packet.TimestampMs); }
    }

    private void Drain(string direction, long timestampMs)
    {
        var buffer = direction == "cs" ? clientBuffer : serverBuffer;
        while (buffer.Pop() is { } frame)
        {
            if (direction == "cs" && !clientLoginDone) { clientLoginDone=true; continue; }
            if (direction == "sc" && !serverLoginDone)
            {
                var login = WireFields.ParseLogin(decryptLogin(frame.Body));
                var key = decryptKey(login.EncryptedSessionKey ?? throw new KeyNotFoundException("session_key_encrypted"));
                var nonce = login.SessionNonce ?? throw new KeyNotFoundException("session_nonce");
                clientCipher=new(key,nonce,1); serverCipher=new(key,nonce,1); serverLoginDone=true;
                while (pendingClient.TryDequeue(out var pending)) Decode("cs",pending.Frame,pending.TimestampMs);
                continue;
            }
            var cipher = direction == "cs" ? clientCipher : serverCipher;
            if (cipher is null)
            {
                if (direction == "cs") pendingClient.Enqueue((frame,timestampMs));
                continue;
            }
            Decode(direction,frame,timestampMs);
        }
    }

    private static string HexPrefix(byte[] bytes, int length) => Convert.ToHexStringLower(bytes.AsSpan(0,Math.Min(bytes.Length,length)));

    private void Failure(string direction, long timestampMs, SessionHead head, byte[] body, Exception error, bool protobuf=false)
    {
        if (protobuf) { metrics.ProtobufDecodeErrors++; ReliabilityFlags.Add("protobuf_decode_failed"); }
        else { metrics.DecompressionErrors++; ReliabilityFlags.Add("session_body_decompression_failed"); }
        Debug(protobuf ? "debug_protobuf_error" : "debug_decompression_error",timestampMs,direction,new()
        {
            ["msg_id"]=head.MessageId ?? BigInteger.Zero, ["class_name"]=registry.ResolveClassName(direction,head.MessageId ?? BigInteger.Zero),
            ["error"]=error.Message, ["head"]=head.ToPayload(), ["body_len"]=body.Length, ["body_prefix_hex"]=HexPrefix(body,128),
        });
    }

    private void Decode(string direction, SessionFrame frame, long timestampMs)
    {
        var cipher = direction == "cs" ? clientCipher : serverCipher;
        if (cipher is null) return;
        var plaintext = cipher.Process([..frame.Head, ..frame.Body]);
        var plainHead = plaintext[..frame.HeadLength];
        var body = plaintext[frame.HeadLength..];
        var head = WireFields.ParseHead(plainHead);
        if (head.ParseError is not null)
        {
            Debug("debug_frame_error",timestampMs,direction,new() { ["error"]=head.ParseError, ["head_len"]=frame.HeadLength,
                ["plain_head_hex"]=Convert.ToHexStringLower(plainHead), ["plain_body_prefix_hex"]=HexPrefix(body,64) });
            return;
        }
        var id = head.MessageId ?? BigInteger.Zero;
        if (onDebug is not null)
            Debug("debug_session_head",timestampMs,direction,new() { ["msg_id"]=id, ["class_name"]=registry.ResolveClassName(direction,id),
                ["head"]=head.ToPayload(), ["head_len"]=frame.HeadLength, ["plain_head_hex"]=Convert.ToHexStringLower(plainHead),
                ["plain_body_len"]=body.Length, ["plain_body_prefix_hex"]=HexPrefix(body,64),
                ["plain_body_hex"]=body.Length <= 4096 ? Convert.ToHexStringLower(body) : null });
        AssembledMessage? assembled;
        try { assembled=multiPack.Assemble(direction,head,body,timestampMs); }
        catch (SessionBodyDecompressionException error) { Failure(direction,timestampMs,head,body,error); return; }
        if (assembled is null) return;
        head=assembled.Head; body=assembled.Body; id=head.MessageId ?? BigInteger.Zero;
        if (!registry.ShouldDecode(direction,id))
        {
            if (onDebug is null) return;
            var debugBody=body;
            try { if (!assembled.AlreadyDecompressed) debugBody=SessionBodyCodec.Decode(head,body); }
            catch (SessionBodyDecompressionException error) { Failure(direction,timestampMs,head,body,error); }
            Debug("debug_ignored_frame",timestampMs,direction,new() { ["msg_id"]=id, ["class_name"]=registry.ResolveClassName(direction,id),
                ["head"]=head.ToPayload(), ["body_len"]=debugBody.Length, ["body_prefix_hex"]=HexPrefix(debugBody,128),
                ["body_hex"]=debugBody.Length <= 8192 ? Convert.ToHexStringLower(debugBody) : null });
            return;
        }
        IReadOnlyList<DecodedMessage> messages;
        try
        {
            if (!assembled.AlreadyDecompressed) body=SessionBodyCodec.Decode(head,body);
            messages=registry.Decode(direction,head,body);
        }
        catch (MessageDecodeFailure error) { Failure(direction,timestampMs,head,body,error,true); return; }
        catch (SessionBodyDecompressionException error) { Failure(direction,timestampMs,head,body,error); return; }
        metrics.FramesDecoded++;
        if (messages.Count == 0)
            Debug("debug_undecoded_frame",timestampMs,direction,new() { ["head"]=head.ToPayload(), ["head_len"]=frame.HeadLength,
                ["plain_head_hex"]=Convert.ToHexStringLower(plainHead), ["plain_body_prefix_hex"]=HexPrefix(body,128) });
        foreach (var message in messages)
        {
            metrics.MessagesDecoded++;
            classCounts[message.ClassName]=classCounts.GetValueOrDefault(message.ClassName)+1;
            onMessage(message,timestampMs);
        }
    }

    public void FlushDebugState()
    {
        if (onDebug is not null)
            foreach (var pair in multiPack.Pending)
                Debug("debug_multipack_incomplete",pair.Value.LastTimestampMs,pair.Key.Direction,new()
                {
                    ["msg_id"]=pair.Key.MessageId, ["base_seqid"]=pair.Key.BaseSequenceId, ["total_pack_count"]=pair.Value.TotalPackCount,
                    ["received_indexes"]=pair.Value.Parts.Keys.Order().ToArray(), ["first_timestamp_ms"]=pair.Value.FirstTimestampMs,
                    ["last_timestamp_ms"]=pair.Value.LastTimestampMs, ["head"]=pair.Value.Head.ToPayload(),
                });
        multiPack.Reset();
    }
}
