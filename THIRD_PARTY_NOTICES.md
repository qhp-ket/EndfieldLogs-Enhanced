# 第三方来源与许可

本开发版基于 ZMDLogs / Endfield Logs 的客户端和核心解析代码修改。
保留上游 `Copyright (c) 2026 Endfield Logs contributors` 及 MIT 许可文本。

上游项目：

- ZMDLogs 客户端源码：<https://github.com/deepdarkssj/ZMDLogs>
- Endfield Logs Suite（网站、解析器和客户端套件）：<https://github.com/medps16000/endfield-suite-open>
- ZMDLogs 完整发行包：<https://zmdlogs.com/>

开发版修改由本项目贡献者维护，Copyright (c) 2026 EndfieldLogs contributors。
开发版新增和修改代码、包含 GPLv3 GUI 依赖的组合程序采用 GPL-3.0-only，见根目录 `LICENSE`；上游 MIT 原文副本保留在
`_development/portable/licenses/EndfieldLogs-MIT.txt`，便于打包时带上原有声明。
上游原始代码的 MIT 授权继续有效；分发组合程序应满足 GPLv3，同时保留 MIT 的版权和许可声明。
此前已按 MIT 发布的版本不因本次修改被追溯撤销许可。

## 入库资源来源

| 内容 | 来源与记录 |
| --- | --- |
| 精简运行数据 `runtime-data.zip` 及清单 | [ZMDLogs](https://zmdlogs.com/) 3.0.12（2026-10-16）完整发行包；固定下载地址及 SHA-256 见 `_internal/data/resource-manifest.json` |
| 中文名称、技力与技能帧规则 | [AKEData 数据站](https://data.akedata.wiki/)、[网站](https://www.akedata.wiki/)及 [AKEDatabase 仓库](https://github.com/NagiYume/AKEDatabase)；版本、提交和原表哈希保留在数据的 `source` / `_source` 中 |
| 圆形角色头像 | AKEData 数据站的 `charroundicon` 图片，缩放并圆形裁切为透明 PNG；角色 ID、原始链接和校验值见 `_internal/data/ui/characters/manifest.json`，维护方式见同目录 README |
| 解析测试中的文案、公式与审核证据 | 固定 ZMDLogs 资源基线及 AKEData 文案快照；版本、表名与哈希见测试 JSON 和 fixtures 说明 |
| 官网风格分析界面参考 | [Endfield Logs Suite](https://github.com/medps16000/endfield-suite-open)，参考提交 `4e65587b36feb4081eadf669391db64fd7469807`；MIT 原文保留在 `_internal/src/endfield_pcap/gui/battle/assets/THIRD_PARTY_NOTICE.txt` |

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
开发环境按清单恢复，便携包附带已校验运行库。窗口捕获复用 Qt Multimedia 的 FFmpeg / WGC 后端。

技术参考致谢：[EndfieldComboHUD](https://github.com/naokotg/EndfieldComboHUD)、
[EndfieldHUD](https://github.com/YuumiSama/EndfieldHUD)，以及 EndfieldRotPilot、EndfieldCDHUD 的输入状态机和 HUD 思路。
输入与视觉模块自行实现，未复制上述参考软件的代码、二进制或图片。
