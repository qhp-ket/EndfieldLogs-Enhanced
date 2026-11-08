using System.Windows;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleTimeline
{
    // These resources describe styles, never report data. Frozen instances can be retained
    // by successive drawing instructions without allocating one resource per mark/hit.
    private static T Frozen<T>(T value) where T : Freezable { value.Freeze(); return value; }
    private static readonly Brush trackTint = Frozen(new SolidColorBrush(Color.FromArgb(10, 128, 128, 128)));
    private static readonly Brush skillFill = Frozen(new SolidColorBrush(Color.FromRgb(132, 186, 230)));
    private static readonly Brush comboFill = Frozen(new SolidColorBrush(Color.FromRgb(239, 176, 106)));
    private static readonly Brush ultimateFill = Frozen(new SolidColorBrush(Color.FromRgb(225, 136, 142)));
    private static readonly Brush otherFill = Frozen(new SolidColorBrush(Color.FromRgb(164, 174, 185)));
    internal static Brush SkillFill(string? category) => category switch
        { "战技" => skillFill, "连携" => comboFill, "大招" or "终结" => ultimateFill, _ => otherFill };
    private static readonly Brush buffFill = Frozen(new SolidColorBrush(Color.FromRgb(149, 167, 130)));
    private static readonly Brush markOutline = Frozen(new SolidColorBrush(Color.FromRgb(96, 106, 116)));
    private static readonly Pen gridPen = Frozen(new Pen(new SolidColorBrush(Color.FromArgb(32, 128, 128, 128)), .7));
    private static readonly Pen groupPen = Frozen(new Pen(gridPen.Brush, 1.2));
    private static readonly Pen axisGridPen = Frozen(new Pen(new SolidColorBrush(Color.FromArgb(30, 128, 128, 128)), .7));
    private static readonly Pen labelPen = Frozen(new Pen(new SolidColorBrush(Color.FromArgb(45, 128, 128, 128)), .8));
    private static readonly Pen labelDividerPen = Frozen(new Pen(labelPen.Brush, .7));
    private static readonly Pen labelHandlePen = Frozen(new Pen(Brushes.SteelBlue, 1.5));
    private static readonly Pen normalMarkPen = Frozen(new Pen(markOutline, 1));
    private static readonly Pen selectedMarkPen = Frozen(new Pen(Brushes.DodgerBlue, 2));
    private static readonly Pen fallbackMarkPen = Frozen(new Pen(markOutline, 1) { DashStyle = DashStyles.Dash });
    private static readonly Pen selectedFallbackPen = Frozen(new Pen(Brushes.DodgerBlue, 2) { DashStyle = DashStyles.Dash });
    private static readonly Pen originalRangePen = Frozen(new Pen(markOutline, 1.5));
    private static readonly Pen selectedRangePen = Frozen(new Pen(Brushes.DodgerBlue, 1.5));
    private static readonly Pen selectedInsetPen = Frozen(new Pen(Brushes.White, .8));
    private static readonly Pen buffPointPen = Frozen(new Pen(Brushes.AliceBlue, .8));
    private static readonly Pen damageHitPen = Frozen(new Pen(Brushes.IndianRed, 1.3));
    private static readonly Pen estimatedEnergyPen = Frozen(new Pen(Brushes.SteelBlue, 1.8) { DashStyle = DashStyles.Dash });
    private static readonly Pen poisePen = Frozen(new Pen(Brushes.DarkGoldenrod, 1.9));
    private static readonly Pen poiseDividerPen = Frozen(new Pen(new SolidColorBrush(Color.FromArgb(50, 128, 128, 128)), 1));
    private static readonly Brush[] controlColors = [
        Frozen(new SolidColorBrush(Color.FromRgb(128, 162, 184))), Frozen(new SolidColorBrush(Color.FromRgb(134, 172, 141))),
        Frozen(new SolidColorBrush(Color.FromRgb(183, 154, 118))), Frozen(new SolidColorBrush(Color.FromRgb(171, 141, 174)))];
}
