# Endfield Logs - Enhanced

《明日方舟：终末地》的第三方战斗日志客户端，基于 ZMDLogs / Endfield Logs 源码开发。
提供实时伤害浮窗、图像识别连携 CD、输入记录及本地战斗分析，界面和文档使用中文。
此分支为 0.3.0 C#／WPF 预发布本体：主界面、战斗分析和浮窗采用 Windows 原生实现，便携包自带 .NET／WPF 运行时。
Python／Qt 维护版位于 `main/python-qt`。候选包的验证结果与剩余限制见 [迁移说明](_development/docs/csharp-migration.md)。
本文中的「官网版」指 ZMDLogs 发行版。

0.3.0 同时提供 Python／Qt 和 C#／WPF 两种本体，请完整解压其中一种。C# 版仍有 WGC 反复重启后句柄增长及纯浮窗私有内存超出 Qt 对照容差的已知限制；真实游戏、OBS、管理员输入和混合 DPI 按实机验收，不将本次预发布视为这些项目全部通过。

相关项目：[ZMDLogs 官网](https://zmdlogs.com/)、[AKEData 网站](https://www.akedata.wiki/)、[AKEData 仓库](https://github.com/NagiYume/AKEDatabase)。

## 功能概览

程序不含针对游戏进程的运行时侵入：注入、Hook、读写内存或修改游戏文件。
采集使用 Npcap 被动抓包，解码在本程序进程内调用本机游戏 `GameAssembly.dll` 导出函数；游戏 DLL 由用户安装提供。

| 功能 | 使用体验 |
| --- | --- |
| 伤害统计 | 实时显示伤害与贡献，默认按 rDMG 显示和排序；支持列选择、头像、暴击率及完整数值悬停 |
| 连携 CD | 四角色圆环或横条；就绪时整块角色背景变绿，识别暂不可读时延续上次可信状态 |
| UID 遮挡 | 可调整位置和尺寸的矩形或圆角遮挡 |
| 原生皮肤 | 内置终末地风格，可导入本地 JSON 皮肤，组合伤害、连携和遮挡模块 |
| 战斗分析 | 时间轴、累计 rDMG 等伤害曲线、技力、失衡、BUFF、技能构成、敌方数据及逐击贡献证据 |
| 角色轨道 | 默认战技独立，连携与终结共轨；角色名称格的设置按钮可调整技能归属和轨道顺序 |
| 输入记录 | 键鼠及手柄输入随伤害日志录制，每场绑定文件后可按战斗时间轴查看操作意图 |
| 历史与上传 | 导入本地 trace、回看历史伤害浮窗，日志兼容官网版 uploader |

连携和输入服务可独立运行；抓包可为连携补充姓名和头像。

## 使用便携包

1. 将本体 ZIP 完整解压到可写目录，双击 `EndfieldLogs-Enhanced.exe`。系统要求为 Windows 10 2004 或更新版本、x64。
2. 在「设置 → 游戏路径」选择 `Endfield.exe` 或游戏目录。
3. 实时抓包另需 [Npcap 官方安装程序](https://npcap.com/#download)，安装时勾选 **Install Npcap in WinPcap API-compatible Mode**。点首页「启动抓包」后进入游戏。
4. 历史分析可直接在「战斗日志」导入本地 trace。

GUI 启动默认未记录。首页「伤害日志」中启动抓包后，点击「开始记录」或按 `Ctrl+I` 开始保存，再次操作停止记录。每次开始创建新的一组 session、trace 文件；停止会写完缓冲并关闭文件，抓包和实时伤害分析继续运行。伤害浮窗常驻显示「记录中／未记录」及红点／灰点。
抓包默认关闭，可在设置中开启随启动运行；自动抓包也不会自动开始记录。
**停止抓包后再启动，需要重开游戏。** 配置、日志和历史列表位于 `.dev-gui/`，运行输出见「运行日志」。

常用控制：

- **导航**：左侧依次为首页、悬浮窗、战斗日志、运行日志、设置；左上角按钮可收起／展开侧栏。
- **GUI**：`Ctrl+Shift+O` 或首页按钮隐藏/恢复到托盘，后台服务继续运行。
- **记录**：`Ctrl+I` 启停伤害日志记录，与首页按钮相同；设置中可修改快捷键，录入期间会显示提示。
- **浮窗**：`Ctrl+O` 一键显隐；列表可调整顺序并保存。「启用」控制功能，「显示浮窗」控制桌面可见性。
- **浮窗设置**：字体和头像比例分别调整；窗口宽高比随当前内容自动适配，拖动边缘等比例缩放，不保留多余空白。位置和大小通过拖动调整，设置页显示当前值并提供重置；锁定、穿透、透明度及窗口设置按实例保存。
- **OBS**：添加窗口采集，方式选 Windows 10（WGC）；隐藏浮窗期间仍可捕获。
- **更新**：设置的「关于」检查正式 Release 版本和发布日期，前往发布页手动下载；支持忽略版本。

本候选的真实游戏、管理员录制、实物手柄、OBS、混合 DPI 和长期资源稳定性仍待实机验收；当前 WGC 重启句柄门禁未通过。
原生皮肤、架构、构建与各项验证范围统一见 [迁移说明](_development/docs/csharp-migration.md)。

### 输入记录

输入仅采集游戏前台操作，普通权限下由记录子进程申请管理员授权。
首页或设置中启用输入记录后，输入文件随伤害记录同步启停，保存为同一日期目录中的配套 `trace_*.input.jsonl`；仅启用选项不会开始落盘。

战斗分析可自动发现配套文件，也可每场「绑定 input log」，再勾选「显示输入」。选择覆盖本场时间的文件，以毫秒级系统时间对齐到战斗范围。
输入用于展示操作意图，技能释放与贡献计算采用 trace 证据。
连携输入标记横跨可见角色轨道，其余输入按所属角色展示。

### 战斗分析

时间轴默认显示累计 rDMG 曲线，可切换 DMG、DPS、rDPS 或关闭曲线。
顶部可直接筛选角色、切换 BUFF 和输入、调整时间与图形缩放，以及选择秒／帧单位。
头像等选项位于「显示设置」，底部详情按需展开，提供事件概况、贡献分配、逐击和原始证据。

角色轨道设置只列出该角色实际出现的技能。默认隐藏「其他」轨道；自定义配置中未分配的技能进入「其他」。
绑定输入文件与显示输入分别设置，时间轴始终采用本场战斗的起止范围。

### 官网上传

当前源码新录制默认使用 `trace_*.jsonl`，历史日志仍可读取。在战斗日志页选中一场，点击「导出官网兼容日志…」生成 `.log` 后再上传；多选时导出最后选中的一场，保留该场完整证据及必要上下文，不包含其他场次。JSONL 连续分卷应一起保留。配置中的显式 `service.trace_format: "legacy"` 继续有效。

历史分析与单场导出均保留必要的战前角色／敌人属性。跨午夜战斗按录制时区和回放起点还原日期；默认导出名为 `trace_战斗N-官网兼容.log`，不沿用源录制日期。重新导入兼容日志会优先读取文件名中的 `YYYYMMDD`，否则采用文件修改日期，因此请保留默认名称及修改时间，避免将整份录制的日期写入单场文件名。

**旧格式 `trace_*.log` 连同 `.log.status.json` 可直接用于 ZMDLogs 官网版 uploader。**
官网 uploader 独立打包，文件从校验过的官方 ZIP 原样提取；输入文件仅用于本地分析。
上传前提见 [运行资源](_development/docs/runtime-resources.md)。

## 从源码开发

本体使用 .NET SDK 10.0.403、C# 和 WPF，目标 Windows x64。准备 SDK 与运行资源后，直接双击仓库根目录 `Start-GUI.cmd`，会增量构建并打开当前源码版；不需要进入 `bin/`。也可手动执行：

```powershell
dotnet restore _internal/dotnet/EndfieldLogs.slnx --locked-mode
dotnet run --project _internal/dotnet/Desktop/EndfieldLogs.Desktop.csproj -c Release --no-restore
```

资源准备与本地验证工具使用 Python；本体运行仅使用包内 .NET／WPF 和批准的原生依赖。
工程职责、固定 Python 参考与工具链设置见 [迁移说明](_development/docs/csharp-migration.md)。

| 目录 | 内容 |
| --- | --- |
| `_internal/dotnet/` | C# 本体、WPF 界面、分类差分与契约验证 |
| `_internal/data/`、`jsondata/` | 精简运行数据、来源清单与规则，见 [数据维护](_internal/data/README.md) |
| `_development/` | 当前维护的测试、工具、中文文档，见 [开发导航](_development/README.md) |

Git 采用源码白名单，个人状态、真实日志、原始数据、安装环境及发行产物留在本地。
`.gitattributes` 指定源码 LF、Windows 启动脚本 CRLF，校验敏感资源保留原字节。

### 功能实现链路

以下代码路径相对 `_internal/dotnet/`：

| 功能 | 实现链路 | 代码入口 |
| --- | --- | --- |
| 采集与日志 | Npcap → TCP 重组 → 解密／分帧 → protobuf → 业务会话 → trace | `Native/`、`Capture/`、`Protocol/`、`Runtime/Capture/`、`Runtime/Tracing/` |
| 实时伤害／贡献 | trace 增量摄取 → 基线／效果／逐击归因 → 简报或完整报告 → 本机发布 | `Core/Ingestion/`、`Core/Reporting/`、`Core/Realtime/`、`Runtime/Realtime/` |
| 历史与战斗分析 | 文件范围索引 → 选中后后台分析 → 原生时间轴及证据详情 | `Runtime/History/`、`Desktop/Presentation/` |
| 浮窗 | v2 JSON 皮肤 → 最小数据订阅 → Direct2D／DirectWrite 绘制 → 原生窗口 | `Runtime/Overlays/`、`Desktop/Overlays/`、`Native/Windows/` |
| 连携 CD | 游戏 HWND → WGC → HUD 像素 → 四槽识别与角色绑定 → 浮窗 | `Native/Windows/`、`Runtime/Vision/`、`Runtime/Services/` |
| 输入记录 | 独立提权进程 → Raw Input／兼容采集、SDL3 → JSONL → 每场绑定及操作解释 | `Native/Input/`、`Runtime/Input/`、`Desktop/Presentation/` |
| 官网上传 | 原始 trace／status 与兼容证明 → 独立官网 uploader | `Core/Integrity/`、`Runtime/Tracing/`、`Runtime/History/` |
| 数据与发行 | 资源清单校验 → 应用及私有 .NET／WPF → 源码／许可／逐文件 SHA-256 → ZIP | `Core/Catalog/`、`_development/tools/build_dotnet_portable.py`（仓库根目录） |

简报和完整报告共用 Core 的计算入口，支持迟到证据、缓存失效和会话重置；固定 Python 计算参考用于差分，独立契约测试验证关键边界。Python／Qt 产品源码由 `main/python-qt` 分支维护，此目录不再保留副本；差分工具通过显式参考路径和哈希清单读取基准。

## 测试与打包

在 Windows 开发环境执行分类验证：

```powershell
& _internal/dotnet/Verify.ps1
& _internal/dotnet/Verify.ps1 -Suite history-index,live-engine -Group history-storage,history-analysis,live-engine
```

测试结果、性能方法与未验证项见 [迁移说明](_development/docs/csharp-migration.md)。本分支 CI 执行 C# 契约及固定差分、无窗口导航和打包工具测试；真实游戏、桌面交互和捕获仍由实机验收覆盖。
版本来源为 `_internal/dotnet/Directory.Build.props`。便携发布示例：

```powershell
dotnet publish _internal/dotnet/Desktop/EndfieldLogs.Desktop.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=false -p:PublishTrimmed=false -p:DebugType=None -p:DebugSymbols=false -p:PortableAppHost=true
```

使用 `_development/tools/build_dotnet_portable.py` 将发布目录、批准资源、应用本地 VC 运行库、源码和许可组装为目录式 ZIP，并验证逐文件清单。
包根目录只保留启动 EXE、使用说明、文件清单及 `_internal/`、`licenses/` 目录。`_internal/app/` 存放应用程序集；`_internal/dotnet/` 按标准 host／shared 框架与版本存放私有运行库，语言资源跟随所属框架；`_internal/native/` 按输入、图片解码区分。数据、图片、运行资源、对应源码和许可分别存放。完整移动整个目录即可，无需安装 .NET。
完整目录说明、构建与搬目录验证见 [打包说明](_development/docs/portable-packaging.md)。官网 uploader 保持独立打包。

## 许可与来源

本项目新增/修改代码及组合 GUI 程序采用 **GPL-3.0-only**，见 [LICENSE](LICENSE)；上游 MIT 版权和许可原文保留，各依赖按各自许可授权。
第三方数据、图片和名称的权利归各自权利人，来源及版本记录见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
分发时的源码和许可交付要求见 [许可说明](_development/docs/licensing.md)。
