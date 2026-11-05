# 开发环境

Windows x64，使用 `_internal/dotnet/global.json` 指定的 .NET SDK 10.0.403。NuGet 版本及内容哈希由各项目的 `packages.lock.json` 固定。

在仓库根目录执行：

```powershell
dotnet restore _internal/dotnet/EndfieldLogs.slnx --locked-mode
python -B _development/tools/prepare_resources.py --offline
python -B _development/tools/prepare_native.py
dotnet run --project _internal/dotnet/Desktop/EndfieldLogs.Desktop.csproj -c Release --no-restore
```

运行资源从已校验的源码恢复包离线提取。抓包另需系统 Npcap、用户游戏目录及批准的运行资源，见 [运行资源](runtime-resources.md)。SDL3 按清单从官方发行包准备；可用 `--archive PATH --offline` 复用本地下载。

Python 仅用于开发工具。资源安装、打包、审计和当前工具测试使用标准库；头像生成需要 Pillow，进程性能对照需要 psutil，按需安装 `_development/environment/requirements-tools.txt`。固定 Python／Qt 差分和性能参考须通过参数显式指定，按其所在分支独立准备依赖。

源码直接启动可双击根目录 `Start-GUI.cmd`，由 `_internal/dotnet/Start.ps1` 定位 SDK、增量构建后打开 C# 界面。也可使用上述 `dotnet run`。`Start-GUI.cmd -Check` 只检查 SDK 与工程路径，不构建或打开窗口。

便携包使用包根目录 EXE。旧 Python 启动逻辑、`Setup-Dev.cmd` 和网页后端已移除。

分类验证见 [测试说明](../tests/README.md)，发行目录结构见 [打包说明](portable-packaging.md)。
