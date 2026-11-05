using System.Text.Encodings.Web;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class BattleSummaryWindow : Window
{
    internal DataGrid Participants { get; } = Ui.Table();
    internal TextBox Quality { get; } = new()
    {
        IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, Padding = new(8),
        VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
    };
    internal BattleSummaryWindow(EvidenceObject snapshot, SettingsStore settings)
    {
        Title = "战斗概况与质量"; Width = 900; Height = 480; MinWidth = 540; MinHeight = 320;
        WindowPlacement.Initialize(this);
        TabControl tabs = new() { Margin = new(12) }; Content = tabs;
        Ui.Column(Participants, "角色", nameof(ParticipantRow.Name), width: 180);
        Ui.Column(Participants, "DMG", nameof(ParticipantRow.Damage), true, "N2");
        Ui.Column(Participants, "rDMG", nameof(ParticipantRow.RDamage), true, "N2");
        Ui.Column(Participants, "DPS", nameof(ParticipantRow.Dps), true, "N2");
        Ui.Column(Participants, "rDPS", nameof(ParticipantRow.RDps), true, "N2");
        Ui.Column(Participants, "暴击率", nameof(ParticipantRow.CritRate), true, "P2");
        Style row = new(typeof(DataGridRow)); row.Setters.Add(new Setter(ToolTipProperty, new Binding(nameof(ParticipantRow.Full)))); Participants.RowStyle = row;
        Participants.ToolTip = "直接展示核心报告中的角色统计；缺失字段显示未知。";
        Participants.ItemsSource = BattleSummaryView.Rows(snapshot);
        var quality = snapshot.Get("snapshot_quality") as EvidenceObject ?? snapshot.Get("quality_summary") as EvidenceObject ?? EvidenceView.Empty();
        var text = PythonSortedJson.Serialize(quality);
        try
        {
            using var document = JsonDocument.Parse(text);
            Quality.Text = JsonSerializer.Serialize(document.RootElement, new JsonSerializerOptions { WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
        }
        catch (JsonException) { Quality.Text = text; }
        tabs.Items.Add(new TabItem { Header = "角色统计", Content = Participants });
        tabs.Items.Add(new TabItem { Header = "快照质量与原始字段", Content = Quality });
        TablePreferences widths = new(settings); widths.Attach("participants", Participants); Closed += (_, _) => widths.Save();
    }
}
