using System.Windows;
using System.Windows.Controls;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Desktop.Presentation;

/// <summary>Pixel widths are saved on close rather than during a drag.</summary>
internal sealed class TablePreferences(SettingsStore settings)
{
    private readonly List<(string Key, DataGrid Table)> tables = [];
    internal void Attach(string key, DataGrid table)
    {
        if (settings.Current.BattleTableWidths.Get(key) is EvidenceArray widths)
            for (var index = 0; index < Math.Min(widths.Items.Count, table.Columns.Count); index++)
                if (EvidenceView.Number(widths.Items[index]) is >= 40 and <= 2000 and var width) table.Columns[index].Width = width;
        tables.Add((key, table));
    }
    internal void Save()
    {
        var values = settings.Current.BattleTableWidths.Fields.ToDictionary();
        foreach (var (key, table) in tables)
            values[key] = new EvidenceArray(table.Columns.Take(12).Select(column => (EvidenceValue)new EvidenceInteger((int)Math.Clamp(Math.Round(column.ActualWidth), 40, 2000))).ToArray());
        var saved = new EvidenceObject(values);
        if (!EvidenceJson.PythonEquals(saved, settings.Current.BattleTableWidths)) settings.Update(current => current with { BattleTableWidths = saved });
    }
}
