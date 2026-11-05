namespace EndfieldLogs.Desktop.Presentation;

/// <summary>Prunes time ranges while preserving source/painter order, including nested and overlapping intervals.</summary>
internal sealed class TimelineIntervalIndex<T>
{
    private readonly IReadOnlyList<T> items;
    private readonly (double Start, double End)[] bounds;
    internal TimelineIntervalIndex(IReadOnlyList<T> items, Func<T, (double Start, double End)> extent)
    {
        this.items = items; bounds = new (double, double)[Math.Max(1, items.Count * 4)];
        if (items.Count > 0) Build(1, 0, items.Count);
        void Build(int node, int first, int end)
        {
            if (end - first == 1) { bounds[node] = extent(items[first]); return; }
            var middle = first + (end - first) / 2;
            Build(node * 2, first, middle); Build(node * 2 + 1, middle, end);
            bounds[node] = (Math.Min(bounds[node * 2].Start, bounds[node * 2 + 1].Start),
                Math.Max(bounds[node * 2].End, bounds[node * 2 + 1].End));
        }
    }
    internal void Query(double start, double end, List<T> result)
    {
        result.Clear(); if (items.Count > 0) Visit(1, 0, items.Count);
        void Visit(int node, int first, int last)
        {
            var range = bounds[node]; if (range.End < start || range.Start > end) return;
            if (last - first == 1) { result.Add(items[first]); return; }
            var middle = first + (last - first) / 2;
            Visit(node * 2, first, middle); Visit(node * 2 + 1, middle, last);
        }
    }
}
