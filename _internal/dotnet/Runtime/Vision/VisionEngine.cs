using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Vision;

/// <summary>Four-slot HUD evidence and confirmed geometry, independent of capture/UI frameworks.</summary>
public sealed class VisionEngine(VisionConfiguration? configuration = null)
{
    private readonly VisionConfiguration config = configuration ?? VisionConfiguration.Normalize();
    private VisionSlotTracker[] trackers = Enumerable.Range(0, 4).Select(_ => new VisionSlotTracker()).ToArray();
    private string? layout, regionIdentity;
    private (int Width, int Height, PixelArea Area)? geometry;
    private ((int Width, int Height, PixelArea Area) Geometry, string Identity)? pending;
    private int confirmations;
    private EvidenceObject diagnostics = TraceData.Make();
    private sealed record Scored(VisionLayoutCandidate Candidate, VisionObservation[] Observations, int Readable, double Score);
    public EvidenceObject Analyze(VisionPixels pixels, PixelArea client, double now, long frameId)
    {
        var area = VisionLayout.GameArea(pixels, client); var currentGeometry = (pixels.Width, pixels.Height, area);
        var available = VisionLayout.Fitted(area).ToList(); if (config.Regions.Count > 0) available.Add(new("custom", "custom", config.Regions));
        var candidates = config.Layout == "auto" ? available : available.Where(row => row.Name == config.Layout).ToList();
        List<Scored> scored = [];
        foreach (var candidate in candidates)
        {
            if (candidate.Regions.Count != 4) continue;
            var observations = candidate.Regions.Select(row => VisionPixelObserver.Observe(pixels.Crop(area, row.Energy), pixels.Crop(area, row.Hp), pixels.Crop(area, row.Portrait))).ToArray();
            var readable = observations.Count(o => o.Readable); double score = 0; foreach (var observation in observations) score += observation.Confidence; score += readable;
            scored.Add(new(candidate, observations, readable, score));
        }
        scored = scored.OrderByDescending(row => row.Score).ToList(); diagnostics = TraceData.Make(("candidates", scored.Count));
        var best = scored.FirstOrDefault();
        if (best is not null)
        {
            var observations = best.Observations.Select((o, index) => TraceData.Make(("slot", index), ("readable", o.Readable),
                ("progress", o.Progress is { } progress ? PythonDecimalRounding.Round(progress, 3) : null), ("ready", o.Ready), ("consumed", o.Consumed), ("partial", o.Partial), ("reason", o.Reason))).ToArray();
            diagnostics = TraceData.Make(("candidates", scored.Count), ("candidate", best.Candidate.Identity), ("score", PythonDecimalRounding.Round(best.Score, 3)),
                ("readable_slots", best.Readable), ("observations", new EvidenceArray(observations)));
        }
        var other = best is null ? null : scored.Skip(1).FirstOrDefault(row => row.Candidate.Name != best.Candidate.Name);
        var sameRegion = best is not null && best.Candidate.Identity == regionIdentity && currentGeometry == geometry;
        var supported = best?.Observations.Count(o => o.Readable || o.Empty) ?? 0;
        if (best is null || best.Readable < (sameRegion ? 1 : 2) || supported < 3 && !sameRegion
            || !sameRegion && config.Layout == "auto" && other is not null && best.Score - other.Score < .1)
            return Invalid(now, "待校准：无法确认游戏 HUD 布局");
        var candidateIdentity = (currentGeometry, best.Candidate.Identity);
        if (pending == candidateIdentity) confirmations++; else { pending = candidateIdentity; confirmations = 1; }
        if (!sameRegion && confirmations < 2) return Invalid(now, "确认布局中", resetLayout: false);
        if (best.Candidate.Identity != regionIdentity || currentGeometry != geometry)
        { trackers = Enumerable.Range(0, 4).Select(_ => new VisionSlotTracker()).ToArray(); layout = best.Candidate.Name; regionIdentity = best.Candidate.Identity; geometry = currentGeometry; }
        var slots = best.Observations.Select((o, index) => Slot(index, trackers[index].Feed(o.Empty && !o.Readable ? o with { Readable = true } : o, now, frameId))).ToArray();
        return TraceData.Make(("frame_valid", true), ("status", "识别中"), ("layout", best.Candidate.Name),
            ("regions", new EvidenceArray(best.Candidate.Regions.Select(row => row.ToEvidence()).ToArray())), ("game_area", new[] { area.X, area.Y, area.Width, area.Height }),
            ("slots", new EvidenceArray(slots)), ("diagnostics", diagnostics));
    }
    private static EvidenceObject Slot(int index, EvidenceObject payload)
    { var fields = TraceData.Make(("slot", index)).Fields.ToDictionary(); foreach (var (key, value) in payload.Fields) fields[key] = value; return new(fields); }
    public EvidenceObject Invalid(double now, string reason, bool resetLayout = true)
    {
        if (resetLayout) { pending = null; confirmations = 0; }
        foreach (var tracker in trackers) tracker.Invalid(now);
        return TraceData.Make(("frame_valid", false), ("status", reason), ("layout", layout),
            ("slots", new EvidenceArray(trackers.Select((tracker, index) => Slot(index, tracker.Payload(now))).ToArray())), ("diagnostics", diagnostics));
    }
}
