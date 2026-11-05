# C# 便携打包

版本来源为 `_internal/dotnet/Directory.Build.props`。本体为 Windows x64 应用，随包提供私有 .NET／WPF 运行库，不依赖目标电脑安装 .NET、Python、Qt 或浏览器运行环境。

在仓库根目录执行（发布输出和候选目录均使用新目录）：

```powershell
dotnet restore _internal/dotnet/EndfieldLogs.slnx --locked-mode
dotnet build _internal/dotnet/Desktop/EndfieldLogs.Desktop.csproj -t:Rebuild -c Release -r win-x64 -p:DebugType=None -p:DebugSymbols=false -p:PortableAppHost=true
dotnet publish _internal/dotnet/Desktop/EndfieldLogs.Desktop.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=false -p:PublishTrimmed=false -p:DebugType=None -p:DebugSymbols=false -p:PortableAppHost=true -o _development/verification/dotnet/candidate-publish
python -B _development/tools/build_dotnet_portable.py --publish-directory _development/verification/dotnet/candidate-publish --target _releases/Endfield-Logs-Enhanced-0.3.0-csharp-windows-x64
```

`PortableAppHost=true` 调用 SDK 的 `CreateAppHost` 任务，把入口程序集设为 `_internal/app/EndfieldLogs-Enhanced.dll`，框架搜索限制为相对应用目录的 `../dotnet`。SDK 固定具体框架补丁版本，禁止版本滚动。打包器从同版本 NuGet runtime pack 收集私有运行库，依据 SDK `RuntimeList.xml` 仅选择桌面框架的 WPF profile，并同步投影其 deps 资产索引，不附带 WinForms 专用组件。包内完整提供本体所需运行库；普通开发构建仍使用原有布局，没有额外常驻启动进程。

0.3.0 预发布的 C# 文件名带 `-csharp-`，Python／Qt 本体使用 `Endfield-Logs-Enhanced-0.3.0-windows-x64.zip`；应用版本均为 `0.3.0`。两版分别从对应分支的已提交源码构建并记录 commit，GitHub Release 标记为预发布，不替代稳定版；源码标签分别为 `v0.3.0`（Python／Qt）和 `v0.3.0-csharp`（C#）。每个 ZIP 附 `.sha256`，本地保留原始 ZIP 和干净解压目录。

已有开发构建输出时也执行上述 `Rebuild`，避免依赖项目沿用不同调试符号参数的增量产物。源码归档须包含 XAML 样式等编译资源；无 Git 的包内源码独立重建必须与最终发布文件逐字节比较，仅比较源码哈希不足以证明发布程序集使用了相同构建参数。

包根目录保留 EXE、`README.zh-CN.md`、`BUILD-MANIFEST.json`；其余文件分类存放：

| 目录 | 内容 |
| --- | --- |
| `_internal/app/` | 本体及第三方托管程序集、应用 deps／runtimeconfig |
| `_internal/dotnet/host/fxr/<版本>/` | .NET 启动组件 hostfxr |
| `_internal/dotnet/shared/Microsoft.NETCore.App/<版本>/` | .NET 基础框架、原生运行库及诊断辅助程序 |
| `_internal/dotnet/shared/Microsoft.WindowsDesktop.App/<版本>/` | WPF／桌面框架；语言资源位于各自的文化子目录 |
| `_internal/native/webp/` | WebP 解码组件及其 VC 运行库 |
| `_internal/native/input/` | SDL3 输入组件和来源清单 |
| `_internal/data/`、`_internal/jsondata/` | 已校验解析数据和 UI 资源 |
| `_internal/secrets/` | 批准的统一 RSA 运行资源 |
| `_internal/source/SOURCE.zip` | 对应 C# 源码和独立重建说明 |
| `licenses/` | 主程序、NuGet、运行时及原生依赖许可 |

`vcruntime140.dll` 跟随 WebP 放在 `_internal/native/webp/`，仅接受 `dotnet-native.json` 审核的大小和哈希；`--vc-runtime PATH` 可显式指定微软分发文件。解码器按完整路径加载，并从同目录解析其原生依赖。构建及运行资源来源见 [迁移说明](csharp-migration.md) 与 [第三方声明](../../THIRD_PARTY_NOTICES.md)。

打包器校验精确框架配置、当前版本、架构、入口、文件分类、资源哈希和许可；拒绝将框架文件混入应用目录。ZIP 使用 CRC、规范路径、大小和 SHA-256 再校验，拒绝覆盖已有候选。清单如实标记 `source_dirty`，带未提交修改的候选不视为正式发布物。

重打包须用 `compare_packages(previous, candidate)` 按相对路径、大小和 SHA-256 比较上一包。新包实际解压到全新中文／空格路径，再完整移动目录验证；从包根 EXE 分别运行 `--check-portable-layout` 和 `--check-product-startup`，核对依赖加载、真实主窗口、隔离配置保存及服务退出，并确认 CoreCLR／WPF 实际来自包内。临时移走私有运行库时，即使全局 .NET 可用也必须拒绝启动。实际游戏、物理输入、OBS 和跨屏交互另行验收。源码未变且回归已通过时复用既有回归，不重复全套测试。

提交前审查 diff、忽略规则和实际暂存内容，排除密钥、真实日志、个人配置、缓存、原始上游数据与测试产物。本体保留已批准的统一 RSA 运行资源，但该资源不入 Git。

官网 uploader 单独交付，从校验过的官方 ZIP 原样提取，不由本体构建或修改。
