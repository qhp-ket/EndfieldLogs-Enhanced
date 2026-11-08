# 第三方来源与许可

本开发版基于 ZMDLogs / Endfield Logs 的客户端和核心解析代码修改。
保留上游 `Copyright (c) 2026 Endfield Logs contributors` 及 MIT 许可文本。

上游项目：

- ZMDLogs 客户端源码：<https://github.com/deepdarkssj/ZMDLogs>
- Endfield Logs Suite（网站、解析器和客户端套件）：<https://github.com/medps16000/endfield-suite-open>
- ZMDLogs 完整发行包：<https://zmdlogs.com/>

开发版修改由本项目贡献者维护，Copyright (c) 2026 EndfieldLogs contributors。
本项目新增和修改代码及组合程序继续采用 GPL-3.0-only，见根目录 `LICENSE`；上游 MIT 原文副本保留在
`_development/portable/licenses/EndfieldLogs-MIT.txt`，便于打包时带上原有声明。
上游原始代码的 MIT 授权继续有效；分发组合程序应满足 GPLv3，同时保留 MIT 的版权和许可声明。

## 入库资源来源

| 内容 | 来源与记录 |
| --- | --- |
| 精简运行数据 `runtime-data.zip` 及清单 | [ZMDLogs](https://zmdlogs.com/) 3.0.14（2026-11-05）完整发行包；固定下载地址及 SHA-256 见 `_internal/data/resource-manifest.json` |
| 中文名称、技力与技能帧规则 | [AKEData 数据站](https://data.akedata.wiki/)、[网站](https://www.akedata.wiki/)及 [AKEDatabase 仓库](https://github.com/NagiYume/AKEDatabase)；版本、提交和原表哈希保留在数据的 `source` / `_source` 中 |
| 圆形角色头像 | AKEData 数据站的 `charroundicon` 图片，缩放并圆形裁切为透明 PNG；角色 ID、原始链接和校验值见 `_internal/data/ui/characters/manifest.json`，维护方式见同目录 README |
| 解析测试中的文案、公式与审核证据 | 固定 ZMDLogs 资源基线及 AKEData 文案快照；版本、表名与哈希见测试 JSON 和 fixtures 说明 |

运行包中沿用 `akedata` 目录的数据经固定 ZMDLogs 发行包取得；
中文名称词典、技力和技能帧规则则各自记录对应的 AKEData 版本。
数据范围、字段提取和更新方法见 `_internal/data/README.md`。

`_development/portable/licenses/Upstream-THIRD_PARTY_NOTICES.md` 是上游声明的原文副本，
其中关于其公开源码树不含游戏资源的描述针对上游。

游戏名称、角色及商标属于各自权利人。本项目代码许可不重新授权这些数据或名称。

源码依赖及 GPLv3 的选择见 `_development/docs/licensing.md`。

## 输入与视觉功能

SDL3 来自 [libsdl-org/SDL](https://github.com/libsdl-org/SDL)，采用 zlib 许可；
版本、官方二进制来源和校验值见 `_internal/native/manifest.json`，许可原文为同目录 `SDL3-LICENSE.txt`。
开发环境按清单恢复，便携包附带已校验运行库。Python 参考版的窗口捕获使用 Qt Multimedia；C# 本体直接调用系统 WGC 与 D3D11。

C# Desktop 使用 Microsoft Windows SDK .NET 投影 `10.0.19041.57`，来源及许可见
[Windows SDK](https://aka.ms/WinSDKProjectURL) 和 [SDK 许可](https://aka.ms/WinSDKLicenseURL)。
随投影提供的 `WinRT.Runtime` 来自 [C#/WinRT](https://github.com/microsoft/CsWinRT)，采用 MIT 许可。

C# 候选包携带 .NET/WPF 10.0.14 运行时，保留 NuGet 运行时包中的许可与第三方声明。
Google.Protobuf 3.36.2 使用 BSD-3-Clause；其许可按 NuGet 元数据所记源提交取得。
Protobuf 与 C#/WinRT 许可副本的来源提交、大小和 SHA-256 见 `_development/portable/dotnet-licenses/manifest.json`。
原生皮肤的 WebP 图片使用 libwebp 1.6.0，通过固定的 `Imazen.WebP.NativeRuntime.win-x64` 1.6.1 提供；
保留 Google 的 BSD 许可、专利授权及 Imazen 的 MIT 许可。动画图片取首帧作为静态背景。

C# 原生浮窗通过 Vortice.Windows 3.8.3 调用系统 Direct2D／DirectWrite，使用 Vortice.Mathematics 2.1.0
和 SharpGen.Runtime／COM 2.4.2-beta；均按锁文件恢复并附带 MIT 许可。
许可来源提交及文件大小、SHA-256 同样记录于上述清单，不依赖已归档的 GameOverlay.Net 或 SharpDX。
包内附带微软签名的应用本地 `vcruntime140.dll`，版本与哈希见 `_development/portable/dotnet-native.json`，
许可原文及来源登记在上述许可清单中。
便携包的 `licenses/` 保留这些副本，`_internal/source/SOURCE.zip` 提供对应 C# 源码及构建说明。

技术参考致谢：[EndfieldComboHUD](https://github.com/naokotg/EndfieldComboHUD)、
[EndfieldHUD](https://github.com/YuumiSama/EndfieldHUD)，以及 EndfieldRotPilot、EndfieldCDHUD 的输入状态机和 HUD 思路。
输入与视觉模块自行实现，未复制上述参考软件的代码、二进制或图片。
