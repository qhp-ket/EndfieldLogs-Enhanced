using EndfieldLogs.Runtime.Services;

internal static class RuntimeLogSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var folder = Directory.CreateTempSubdirectory("endfield-runtime-log-");
        try
        {
            var path = Path.Combine(folder.FullName, "logs", "runtime.log");
            string Read() { using var input = new StreamReader(new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)); return input.ReadToEnd(); }
            using (var log = new RuntimeLog(path, maxBytes: 200))
            {
                log.Write("程序启动；尚未记录战斗");
                check(Read().Contains("程序启动"), "Startup diagnostics flush without battle recording");
                log.Write("后台异常", new InvalidOperationException("测试错误"));
                check(Read().Contains("InvalidOperationException: 测试错误"), "Runtime diagnostics preserve exception type and detail");
                for (var i = 0; i < 15; i++) log.Write("周期统计 " + new string('x', 100));
                check(File.Exists(path + ".1") && File.Exists(path + ".2") && !File.Exists(path + ".3"), "Runtime log retains two bounded backups");
                check(Read().Contains("周期统计"), "Rotated writer retains current diagnostics");
            }
            using (var restarted = new RuntimeLog(path)) restarted.Write("再次启动");
            check(File.ReadAllText(path).Contains("再次启动"), "Runtime log reopens after shutdown");
            var blocked = Path.Combine(folder.FullName, "blocked"); File.WriteAllText(blocked, "file");
            using var failure = new RuntimeLog(Path.Combine(blocked, "runtime.log"));
            check(failure.Write("不可写目录").Contains("不可写目录") && failure.Error is not null, "File failure remains observable without interrupting capture");
        }
        finally { folder.Delete(recursive: true); }
    }
}
