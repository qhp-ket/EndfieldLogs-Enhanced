namespace EndfieldLogs.Core.Models;

public sealed class RuntimeMetrics
{
    public long PacketsSeen { get; set; }
    public long PacketsDroppedQueue { get; set; }
    public long FramesDecoded { get; set; }
    public long MessagesDecoded { get; set; }
    public long DecompressionErrors { get; set; }
    public long ProtobufDecodeErrors { get; set; }
    public long OutboundEventsEmitted { get; set; }
    public long WsBatchesSent { get; set; }
}
