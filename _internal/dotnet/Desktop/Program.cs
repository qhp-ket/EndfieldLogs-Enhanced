using EndfieldLogs.Desktop.Verification;
using EndfieldLogs.Runtime.Input;

namespace EndfieldLogs.Desktop;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args is ["--check-product-startup", var startupOutput]) return ProductApplication.Run(startupCheckOutput: startupOutput);
        if (args is ["--check-navigation", var navigationOutput]) return ProductProbe.RunNavigationChecks(navigationOutput);
        if (args is ["--check-pages", var pagesOutput]) return ProductProbe.RunPageChecks(pagesOutput);
        if (args is ["--check-battle-presentation", var battleSource, var battleRoot, var battleOutput]) return BattlePresentationCheck.Run(battleSource, battleRoot, battleOutput);
        if (args is ["--check-portable-layout", var portableOutput]) return PortableLayoutProbe.Run(portableOutput);
        if (args is ["--probe-window", var output]) return OverlayProbe.Run(output);
        if (args is ["--probe-vision", var visionOutput]) return VisionCaptureProbe.Run(visionOutput);
        if (args is ["--probe-vision-lifetime", var lifetimeOutput]) return VisionCaptureProbe.Run(lifetimeOutput, naturalLifetime: true);
        if (args is ["--probe-vision-lifetime", var reusedOutput, "reuse-device"]) return VisionCaptureProbe.Run(reusedOutput, naturalLifetime: true, reuseDevice: true);
        if (args is ["--probe-vision-lifetime", var cachedOutput, "reuse-item"]) return VisionCaptureProbe.Run(cachedOutput, naturalLifetime: true, reuseItem: true);
        if (args is ["--probe-product", var productOutput]) return ProductProbe.Run(productOutput);
        if (args is ["--probe-overlays", var overlayOutput]) return OverlayProductProbe.Run(overlayOutput);
        if (args is ["--probe-overlay-layout", var layoutProbeOutput]) return OverlayProductProbe.RunLayouts(layoutProbeOutput);
        if (args is ["--check-overlay-lifetime", var lifetimeCheckOutput]) return OverlayLifetimeChecks.Run(lifetimeCheckOutput);
        if (args is ["--probe-overlay-graphics", var graphicsOutput]) return OverlayGraphicsProbe.Run(graphicsOutput);
        if (args is ["--probe-overlay-glyphs", var glyphOutput]) return OverlayGlyphProbe.Run(glyphOutput);
        if (args is ["--probe-overlay-geometry", var geometryOutput]) return OverlayGeometryProbe.Run(geometryOutput);
        if (args is ["--probe-direct-overlays", var directOutput]) return OverlayDirectProbe.Run(directOutput);
        if (args is ["--benchmark-direct-overlays", var directInput, var directBenchmarkOutput]) return OverlayDirectBenchmark.Run(directInput, directBenchmarkOutput);
        if (args is ["--benchmark-overlays", var benchmarkOutput]) return OverlayBenchmark.Run(benchmarkOutput);
        if (args is ["--benchmark-overlays", var benchmarkInput, var preparedOutput]) return OverlayBenchmark.Run(preparedOutput, input: benchmarkInput);
        if (args is ["--benchmark-overlays", var warmInput, var warmOutput, var warmFrames] && int.TryParse(warmFrames, out var count))
            return OverlayBenchmark.Run(warmOutput, input: warmInput, warmupFrames: count);
        if (args is ["--benchmark-overlays", var themedInput, var themedOutput, var themedFrames, var theme]
            && int.TryParse(themedFrames, out var themedCount) && theme is "light" or "dark")
            return OverlayBenchmark.Run(themedOutput, input: themedInput, warmupFrames: themedCount, theme: theme);
        if (args is ["--profile-overlay-raster", var rasterOutput]) return OverlayBenchmark.Run(rasterOutput, profile: true);
        if (args is ["--profile-overlay-memory", var memoryOutput]) return OverlayBenchmark.Run(memoryOutput, memoryProfile: true);
        if (args is ["--profile-overlay-layout", var layoutOutput]) return OverlayBenchmark.ProfileLayouts(layoutOutput);
        if (args is ["--profile-overlay-resources", var resourceOutput, var resourceBackend] && resourceBackend is "hardware" or "software")
            return OverlayBenchmark.ProfileResources(resourceOutput, resourceBackend == "hardware");
        if (args is ["--benchmark-interface", var interfaceInput, var interfaceOutput]) return InterfaceBenchmark.Run(interfaceInput, interfaceOutput);
        if (args is ["--input-worker", var name, var parent, var key] && int.TryParse(parent, out var pid))
        {
            try { return InputWorkerHost.ConnectAsync(name, pid, key).GetAwaiter().GetResult(); }
            catch (Exception) { return 1; }
        }
        if (args.Length == 0) return ProductApplication.Run();
        if (args is ["--root", var root]) return ProductApplication.Run(root);
        if (args is ["--overlays"]) return StandaloneOverlays.Run();
        if (args is ["--overlays", "--root", var overlayRoot]) return StandaloneOverlays.Run(overlayRoot);
        return 2;
    }
}
