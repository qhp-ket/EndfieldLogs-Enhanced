using System.Security.Cryptography;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Capture;

namespace EndfieldLogs.Runtime.Configuration;

/// <summary>Explicit installation and process roots; product settings travel with the portable directory.</summary>
public sealed record SettingsContext
{
    public string ApplicationRoot { get; }
    public string WorkingDirectory { get; }
    public string DefaultPath => Path.Combine(ApplicationRoot, ".dev-gui", "settings.json");
    public SettingsContext(string applicationRoot, string? workingDirectory = null)
    {
        ApplicationRoot = Path.GetFullPath(applicationRoot);
        WorkingDirectory = Path.GetFullPath(workingDirectory ?? Environment.CurrentDirectory);
    }
}

public sealed record ServiceSettings
{
    public int WebSocketPort { get; init; } = 29325;
    public string BrowserToken { get; init; } = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    public required string LogDirectory { get; init; }
    public string LogLevel { get; init; } = "INFO";
    public string TraceFormat { get; init; } = "jsonl";
    public string GameExecutable { get; init; } = "Endfield.exe";
    public string NpcapDevice { get; init; } = "auto";
    public string NativeGameDirectory { get; init; } = @"C:\Program Files\Hypergryph Launcher\games\Endfield Game";
    public bool DebugEnabled { get; init; }
    public required string DebugDirectory { get; init; }
    public required string RsaKeyPath { get; init; }
    public required string NameIndexPath { get; init; }
    public bool MergeMultiPhaseEnemyBattles { get; init; }

    public GameCaptureOptions ToCaptureOptions() => new(GameExecutable, NativeGameDirectory, RsaKeyPath,
        LogDirectory, NpcapDevice, MergeMultiPhaseEnemyBattles, DebugDirectory: DebugEnabled ? DebugDirectory : null,
        WebSocketPort: WebSocketPort, BrowserToken: BrowserToken, NameIndexPath: NameIndexPath, TraceFormat: TraceFormat);

    public static ServiceSettings Default(SettingsContext context) => new()
    {
        LogDirectory = Path.Combine(context.ApplicationRoot, ".dev-gui", "logs", "battles"),
        DebugDirectory = Path.Combine(context.ApplicationRoot, ".dev-gui", "debug"),
        RsaKeyPath = Path.Combine(context.ApplicationRoot, "_internal", "secrets", "client_privkey.pem"),
        NameIndexPath = Path.Combine(context.ApplicationRoot, "_internal", "jsondata", "CharacterNameIndex.json"),
    };
}

public sealed record OverlayGeometry(int X, int Y, int Width, int Height);
public sealed record OverlaySettings
{
    public string Id { get; init; } = Guid.NewGuid().ToString();
    public string Name { get; init; } = "伤害统计";
    public string SourceType { get; init; } = "builtin";
    public string SourceValue { get; init; } = "damage";
    public bool Enabled { get; init; } = true;
    public bool Hidden { get; init; }
    public bool Locked { get; init; }
    public bool ClickThrough { get; init; }
    public double Opacity { get; init; } = 1;
    public double Scale { get; init; } = 1;
    public double FontScale { get; init; } = 1;
    public OverlayGeometry? Geometry { get; init; }
    public EvidenceObject TemplateSettings { get; init; } = SettingsData.Empty();
    public string BarMode { get; init; } = "rdps";
    public IReadOnlyList<string> VisibleColumns { get; init; } = ["damage", "damage_rate", "rdamage", "rdamage_rate"];
    public string Theme { get; init; } = "light";
}

public sealed record ApplicationSettings
{
    public required ServiceSettings Service { get; init; }
    public IReadOnlyList<OverlaySettings> Overlays { get; init; } = [];
    public string ThemeMode { get; init; } = "system";
    public int FontPercent { get; init; } = 115;
    public string ToggleOverlaysHotkey { get; init; } = "Ctrl+O";
    public string ToggleGuiHotkey { get; init; } = "Ctrl+Shift+O";
    public string ToggleRecordingHotkey { get; init; } = "Ctrl+I";
    public IReadOnlyList<string> ImportedTraceFiles { get; init; } = [];
    public IReadOnlyList<string> HiddenHistoryRecords { get; init; } = [];
    public int OverlayMigrationCount { get; init; }
    public EvidenceObject BattleTableWidths { get; init; } = SettingsData.Empty();
    public EvidenceObject BattleLaneConfigs { get; init; } = SettingsData.Empty();
    public IReadOnlyList<string> OverlayRestoreIds { get; init; } = [];
    public bool StartCaptureOnLaunch { get; init; }
    public bool CheckUpdatesOnStart { get; init; } = true;
    public string IgnoredUpdateVersion { get; init; } = "";
    public bool ShowCharacterAvatars { get; init; } = true;
    public int CharacterAvatarPercent { get; init; } = 100;
    public bool InputRecordingEnabled { get; init; }
    public bool StartInputRecordingOnLaunch { get; init; }
    public EvidenceObject InputSettings { get; init; } = SettingsData.Empty();
    public EvidenceObject InputLogBindings { get; init; } = SettingsData.Empty();
    public EvidenceObject VisionSettings { get; init; } = SettingsData.Empty();
}
