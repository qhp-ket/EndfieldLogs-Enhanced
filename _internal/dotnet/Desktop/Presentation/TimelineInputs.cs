using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed record TimelineInputSpan(EvidenceObject Evidence, int FirstRow, int RowCount);
internal sealed record TimelineInputLayout(IReadOnlyList<TimelineInputSpan> Spans, IReadOnlyList<EvidenceObject> Raw, bool ExtraRow);

/// <summary>Positions already interpreted evidence; role spans exclude the separate raw-input track.</summary>
internal static class TimelineInputs
{
    internal static TimelineInputLayout Layout(EvidenceObject evidence, IReadOnlyList<(string Owner, string Lane)> lanes, string filter)
    {
        List<TimelineInputSpan> spans = []; List<EvidenceObject> unowned = [];
        var other = (evidence.Get("settings") as EvidenceObject)?.Get("show_other") is EvidenceBoolean { Value: true };
        foreach (var action in EvidenceView.Rows(evidence.Get("actions")))
        {
            var type = EvidenceView.Text(action.Get("action"));
            if (type is not ("skill" or "ultimate" or "combo") && !other) continue;
            var owner = EvidenceView.Text(action.Get("character_key"));
            if (type == "combo")
            {
                if (lanes.Count > 0) spans.Add(new(action, 0, lanes.Count));
                continue;
            }
            var rows = Enumerable.Range(0, lanes.Count).Where(index => lanes[index].Owner == owner && owner.Length > 0).ToArray();
            if (rows.Length > 0) spans.Add(new(action, rows[0], rows[^1] - rows[0] + 1));
            else if (!(filter.Length > 0 && owner.Length > 0 && filter != owner)) unowned.Add(action);
        }
        var raw = EvidenceView.Rows(evidence.Get("raw")).ToArray();
        spans.AddRange(unowned.Select(action => new TimelineInputSpan(action, lanes.Count, 1)));
        return new(spans, raw, unowned.Count > 0 || raw.Length > 0);
    }
}
