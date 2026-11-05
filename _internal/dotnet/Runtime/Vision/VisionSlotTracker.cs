using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Vision;

/// <summary>Observed cooldown state and bounded velocity evidence. An unreadable frame retains the last estimate.</summary>
public sealed class VisionSlotTracker
{
    private string state = "unknown";
    private double? progress, remaining, lastValid, lastMovement, estimateAt, estimateProgress;
    private long? lastFrame;
    private readonly List<(double Time, double Progress)> samples = [];
    private bool held;
    public void Invalid(double now) { samples.Clear(); held = lastValid is not null; }
    public EvidenceObject Feed(VisionObservation observation, double now, long frameId)
    {
        if (frameId == lastFrame)
        { if (lastValid is null || now - lastValid > 1) Invalid(now); return Payload(now); }
        lastFrame = frameId;
        if (!observation.Readable || observation.Progress is null && !observation.Empty && !observation.Dead)
        { Invalid(now); return Payload(now); }
        lastValid = now; held = false;
        var desired = observation.Empty ? "empty" : observation.Dead ? "dead" : observation.Ready ? "ready" : "cooldown";
        if (desired != state) samples.Clear(); state = desired; var value = observation.Progress; var old = progress;
        if (value is not null && (old is null || Math.Abs(value.Value - old.Value) > .001)) lastMovement = now;
        progress = value; remaining = estimateAt = estimateProgress = null;
        if (state != "cooldown" || value is null) samples.Clear();
        else
        {
            if (old is not null && (value < old - .015 || value - old > .2)) samples.Clear();
            samples.Add((now, value.Value)); if (samples.Count > 128) samples.RemoveAt(0);
            while (samples.Count > 0 && now - samples[0].Time > 3) samples.RemoveAt(0);
            if (lastMovement is not null && now - lastMovement > .2) samples.Clear();
            if (samples.Count > 0 && now - samples[0].Time >= .75)
            {
                var recent = samples.Where(p => now - p.Time <= .75).ToArray();
                if (recent.Length > 1 && value - recent[0].Progress > .003)
                {
                    var slopes = samples.Zip(samples.Skip(1)).Where(p => p.Second.Time > p.First.Time && p.Second.Progress > p.First.Progress)
                        .Select(p => (p.Second.Progress - p.First.Progress) / (p.Second.Time - p.First.Time)).ToArray();
                    if (slopes.Length > 0)
                    {
                        var speed = Median(slopes); var spread = Median(slopes.Select(s => Math.Abs(s - speed)).ToArray());
                        if (speed > .001 && spread < Math.Max(.002, speed * .3))
                        { remaining = Math.Max(0, (1 - value.Value) / speed * 1000); estimateAt = now; estimateProgress = value; }
                    }
                }
            }
        }
        return Payload(now);
    }
    private static double Median(double[] values)
    { Array.Sort(values); var middle = values.Length / 2; return values.Length % 2 == 0 ? (values[middle - 1] + values[middle]) / 2 : values[middle]; }
    public EvidenceObject Payload(double now)
    {
        var stale = lastValid is null || now - lastValid > 1; var value = progress; var estimate = remaining;
        if (held && state == "cooldown" && remaining is not null && estimateAt is not null)
        {
            var elapsed = Math.Max(0, now - estimateAt.Value) * 1000;
            if (elapsed >= remaining)
            { state = "ready"; progress = value = 1; remaining = estimate = 0; estimateAt = null; }
            else { value = estimateProgress + (1 - estimateProgress) * elapsed / remaining; estimate -= elapsed; }
        }
        if (state == "ready") { value = 1; estimate = 0; }
        return TraceData.Make(("status", state), ("progress", value), ("estimated_remaining_ms", estimate), ("stale", stale), ("held", held));
    }
}
