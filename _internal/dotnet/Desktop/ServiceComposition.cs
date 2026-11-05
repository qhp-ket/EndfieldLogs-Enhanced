using System.IO;
using EndfieldLogs.Desktop.Vision;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Input;
using EndfieldLogs.Runtime.Services;
using EndfieldLogs.Runtime.Vision;

namespace EndfieldLogs.Desktop;

/// <summary>Product adapters are selected here; Runtime never needs a WPF control or projected Windows type.</summary>
internal static class ServiceComposition
{
    internal static string InputNativeDirectory(string root)
    {
        var native = Path.Combine(root, "_internal", "native");
        var input = Path.Combine(native, "input");
        return Directory.Exists(input) ? input : native; // Source checkout uses the reviewed resource projection.
    }

    public static IndependentServiceController Independent(SettingsStore settings, Action<IReadOnlySet<string>> setCaptureStreams,
        Action<string>? diagnostic = null)
    {
        var input = new InputRecordingController(Environment.ProcessPath ?? throw new InvalidOperationException("无法定位本体程序"));
        var executable = Path.Combine(settings.Current.Service.NativeGameDirectory, settings.Current.Service.GameExecutable);
        var vision = new VisionService(() => new WgcCaptureBackend(), executable, settings.Current.VisionSettings);
        return new(input, vision, setCaptureStreams, settings, InputNativeDirectory(settings.Context.ApplicationRoot), diagnostic);
    }
}
