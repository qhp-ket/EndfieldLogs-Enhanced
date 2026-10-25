# 运行数据维护

开发环境与便携版共用精简数据。基准为 ZMDLogs 3.0.12（2026-10-16），另含四份项目维护规则。
解析数据 2,740 个文件，约 16.9 MB；源码恢复包 `runtime-data.zip` 约 5.8 MB。体积使用十进制 MB。

## 来源与保留范围

| 内容 | 来源记录 |
| --- | --- |
| `runtime-data.zip` | 固定 ZMDLogs 发行包，地址与 SHA-256 见 `resource-manifest.json`；`akedata` 保留上游目录名 |
| `local_semantics/team_energy_rules.json` | [AKEDatabase](https://github.com/NagiYume/AKEDatabase) 技力机制与技能表，提交 `31b53147cd88fb6e9576b5c389967d21687c85cf` 及表哈希见 `source` |
| `local_semantics/skill_frame_rules.json` | AKEDatabase SkillData，资源时间、摘要和文件数见 `source` |
| `game_resource_snapshot.json`、`packet_semantics/rdps_semantics_registry.json` | 本项目维护的元数据及解析规则，含输入哈希和证据 |
| `ui/characters/` | [AKEData 数据站](https://data.akedata.wiki/) 35 个离线头像，约 1.18 MB；映射和校验见 [头像说明](ui/characters/README.md) |

来源和已有许可声明见根目录 `THIRD_PARTY_NOTICES.md`。
头像是独立展示资源，解析字段投影单独存入 `runtime-data.zip`。

提取规则按目录和静态字段保留：

- 全部已收录 ID 的名称、技能分组、潜能、等级属性、武器和装备数值。
- 技能类别、动态黑板动作索引、Buff 时长及子 Buff 关系。
- 协议数字映射、语义关系、分类、乘区与 rDPS 批准规则。
- 技能帧、技力、关卡、敌人、词条及 GUI 辅助表。
- 完整 typed Buff roots、伤害 catalog 和原始证据哈希。

typed roots 的结构/证明、按字节校验的武器定义保持原样。
技能 manifest 保留层数上限所需的 23 条记录；`sourceResourceCount`、`sourceManifestSha256` 记录原始 2,928 项清单。
测试专用公式证据位于 `parser_core/tests/fixtures/runtime_evidence/`。

## 读取范围与体积

| 分组 | MB | 主要读取者 |
| --- | ---: | --- |
| `akedata` | 1.65 | parser、hit_debug、uploader、loadout、buff_display |
| `local_static` | 7.23 | parser 的 typed roots、伤害及公式证据 |
| `local_semantics` | 3.51 | parser、技能帧、技力证据 |
| `local_tables` | 3.04 | parser、capture/resolver、名称、loadout、trace |
| `packet_semantics` | 1.24 | parser、协议映射、hit_debug |
| 消息 ID 表 | 0.18 | message_registry |
| `public` | 0.02 | 关卡词条名称 |
| `jsondata` | 0.007 | 名称、头像映射、关卡辅助表 |

等级属性表约 1.27 MB，技能 manifest 约 5 KB。
最大的 `typed_roots.json.gz`（3.56 MB）和 `damage_element_catalog.json`（3.34 MB）包含严格解析证据。

```powershell
python -B _development/tools/audit_runtime_data.py --references
python -B _development/tools/audit_runtime_data.py --exercise
```

`--references` 列出静态 IO/路径候选、分组及大文件；`--exercise` 记录合成场景实际打开的文件。
删字段需结合动态路径和解析语义复核。

## 恢复与打包

```powershell
python -B _development/tools/prepare_resources.py
python -B _development/tools/prepare_resources.py --check
python -B _development/tools/audit_runtime_data.py
```

默认离线恢复。schema 2 清单记录恢复包和各文件的大小/SHA-256；开发规则从当前源码读取，已有文件不匹配时人工核对。
便携构建只复制清单输出文件，恢复 ZIP 留在源码环境。

## 重建与升级

完整输入位于本地 `_development/raw-resources/_internal/`，供提取工具使用。

```powershell
python -B _development/tools/prepare_resources.py --raw
# 也可加 --archive PATH --offline
python -B _development/tools/extract_runtime_data.py `
  --source _development/raw-resources/_internal `
  --output _development/verification/new-runtime
python -B _development/tools/verify_runtime_projection.py `
  --raw _development/raw-resources/_internal `
  --runtime _development/verification/new-runtime `
  --output _development/verification/runtime-comparison
```

升级步骤：

1. 核对完整发行 ZIP、SHA-256、解码版本，更新 `SOURCE`、输入清单及 typed 证据绑定；保留基准目录用于比较。
2. 同步 manifest、数字映射、技能/Buff 条目和四份开发规则；新增 rDPS 效果单独审核批准。
3. 在新目录提取、对照，并运行应用、parser_core、uploader_core 回归。
4. 审核后调用 `activate(project_root, projection_root)`，或在新输出目录重提取并加 `--install`。
5. 生成恢复 ZIP 和清单，再构建便携包。安装前完整校验并归档基准输入，ZIP 使用固定时间戳。

等价检查覆盖解析目录、技能索引、Buff 派生规则、合成 trace 完整报告、浮窗、GUI 及 uploader payload。
新增字段同步修改 `project()` 与读取代码；新增目录同步修改 `ITEMS` / `FIXED`。

## 新角色与缺失资料

提取器按 `ITEMS` 目录、`FIXED` 共享表和 `project()` 字段收集来源清单内所有 ID；原件缺失时拒绝提取。

| 缺失情况 | 运行行为 |
| --- | --- |
| 名称 | 回退核心名称或原 ID |
| 头像 | 使用占位/空头像 |
| 技能帧配置 | 使用日志起止与命中证据 |
| 角色定义 | 保留有身份/目标证据的伤害、计时、汇总和本地分析 |
| 动作、属性或 Buff 语义 | 对应 rDPS 待确认，保留质量原因 |
| 关键数据包损坏 | 重新恢复并校验 |

相关测试：`_development/tests/resources/test_runtime_projection.py`、`test_missing_character_resources.py`。
