using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Checks relocated apphost/runtime loading without a Window, capture or input hooks.</summary>
internal static class PortableLayoutProbe
{
    internal static int Run(string output)
    {
        try
        {
            var root = ProductApplication.ResolveRoot();
            var application = Path.Combine(root, "_internal", "app");
            if (!Path.GetFullPath(AppContext.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar).Equals(application, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("应用没有从包内 app 目录加载");
            if (Environment.ProcessPath != Path.Combine(root, "EndfieldLogs-Enhanced.exe"))
                throw new InvalidOperationException("应用没有使用根目录入口");
            var image = EndfieldLogs.Native.Windows.WebPImage.Decode(Convert.FromBase64String("UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAdQlFKUp/+BiOh/AAA="));
            if (image.Width != 1 || image.Height != 1 || image.PremultipliedBgra.Length != 4)
                throw new InvalidOperationException("包内 WebP 解码失败");
            var framework = Path.GetDirectoryName(typeof(System.Windows.Application).Assembly.Location)!;
            var sdl = NativeLibrary.Load(Path.Combine(ServiceComposition.InputNativeDirectory(root), "SDL3.dll"));
            var wpf = NativeLibrary.Load(Path.Combine(framework, "wpfgfx_cor3.dll"));
            try
            {
                using var process = Process.GetCurrentProcess();
                var modules = process.Modules.Cast<ProcessModule>().ToDictionary(module => module.ModuleName!, module => module.FileName!, StringComparer.OrdinalIgnoreCase);
                string[] required = ["hostfxr.dll", "coreclr.dll", "wpfgfx_cor3.dll", "vcruntime140.dll", "libwebpdemux.dll", "SDL3.dll"];
                foreach (var name in required)
                    if (!modules.TryGetValue(name, out var path) || !Path.GetFullPath(path).StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("未使用包内组件：" + name);
                var assemblies = AppDomain.CurrentDomain.GetAssemblies().Where(assembly => !assembly.IsDynamic && assembly.Location.Length > 0)
                    .ToDictionary(assembly => assembly.GetName().Name!, assembly => assembly.Location);
                if (assemblies.Values.Any(path => !Path.GetFullPath(path).StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)))
                    throw new InvalidOperationException("加载了包外托管程序集");
                File.WriteAllText(output, JsonSerializer.Serialize(new { passed = true, root, application, executable = Environment.ProcessPath,
                    modules = required.ToDictionary(name => name, name => modules[name]), assemblies, webp_decoded = true,
                    windows_created = 0 }, new JsonSerializerOptions { WriteIndented = true }));
                return 0;
            }
            finally { NativeLibrary.Free(wpf); NativeLibrary.Free(sdl); }
        }
        catch (Exception error) { File.WriteAllText(output, JsonSerializer.Serialize(new { passed = false, error = error.ToString() })); return 1; }
    }
}
