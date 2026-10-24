# 第三方来源与许可

本开发版基于 ZMDLogs / Endfield Logs 的客户端和核心解析代码修改。
保留上游 `Copyright (c) 2026 Endfield Logs contributors` 及 MIT 许可文本。

上游项目：

- ZMDLogs：<https://github.com/deepdarkssj/ZMDLogs>
- Endfield Logs 公开源码套件：<https://github.com/medps16000/endfield-suite-open>
- ZMDLogs 完整发行包：<https://zmdlogs.com/>

开发版修改由本项目贡献者维护，Copyright (c) 2026 EndfieldLogs contributors。
开发版新增和修改代码、包含 GPLv3 GUI 依赖的组合程序采用 GPL-3.0-only，见根目录 `LICENSE`；上游 MIT 原文副本保留在
`_development/portable/licenses/EndfieldLogs-MIT.txt`，便于打包时带上原有声明。
上游原始代码的 MIT 授权继续有效；分发组合程序应满足 GPLv3，同时保留 MIT 的版权和许可声明。
此前已按 MIT 发布的版本不因本次修改被追溯撤销许可。

## 入库资源来源

以下列出源码仓库中保留的第三方资源。有明确许可的保留其许可和版权声明；
未附明确许可的记录来源，不将本项目 GPLv3 标注为这些资源的许可。

| 内容 | 来源与记录 | 许可说明 |
| --- | --- | --- |
| 精简运行数据 `runtime-data.zip` 及清单 | ZMDLogs 3.0.12（2026-10-16）完整发行包；固定下载地址、整包及逐文件 SHA-256 见 `_internal/data/resource-manifest.json` | 未附独立数据许可，按来源记录 |
| AKEData 派生的技力、技能帧规则 | AKEData / `NagiYume/AKEDatabase`；版本、提交或资源摘要保留在对应 JSON 的 `source` 中 | 未附独立数据许可，按来源记录 |
| 中文技能名称词典 `_internal/src/endfield_pcap/data/assets/skill_names_zh.json` | 用户提供的 `zmdlogs技能中文化油猴脚本.js` 中的 `DICT`，仅提取词典；原脚本注明数据来自 AKEData，文件哈希及表名见词典 `_source` | 未附独立词典许可，按来源记录 |
| 解析测试中的文案、公式与审核证据 | 固定 ZMDLogs 资源基线及其中的 AKEData 文案快照；版本、表名和哈希保留在测试 JSON 与 fixtures 说明中 | 未附独立数据许可，按来源记录 |
| 官网风格分析界面参考 | Endfield Logs 公开源码套件，参考提交 `4e65587b36feb4081eadf669391db64fd7469807` | MIT；原文保留在 `_internal/src/endfield_pcap/gui/battle/assets/THIRD_PARTY_NOTICE.txt` |

AKEData：[数据站](https://data.akedata.wiki/)、[网站](https://www.akedata.wiki/)、
[Git 仓库](https://github.com/NagiYume/AKEDatabase)。
运行包中沿用 `akedata` 目录的数据经固定 ZMDLogs 发行包取得；
技力和技能帧规则则另有 AKEData 来源记录，不把两者混写为同一版本。
数据范围、字段提取和更新方法见 `_internal/data/README.md`。

`_development/portable/licenses/Upstream-THIRD_PARTY_NOTICES.md` 是上游声明的原文副本，
其中关于其公开源码树不含游戏资源的描述针对上游。

游戏名称、角色及商标属于各自权利人。本项目代码许可不重新授权这些数据或名称。

源码依赖及 GPLv3 的选择见 `_development/docs/licensing.md`。
