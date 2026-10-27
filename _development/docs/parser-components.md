# 解析与上传代码导航

路径相对 `_internal/packages/`。

## 解析核心

`parser_core/parser_core/parser.py` 协调摄取和报告；`battle_log_parser.py` 保留显式兼容导入。内部代码直接依赖实现所在模块。

| 目录 | 职责 |
| --- | --- |
| `catalog/` | 数值 ID、技能、装备、静态资源和诊断目录；缓存由所属目录函数维护 |
| `ingestion/` | `IngestionState`、有序日志摄取、实体、技能、装备、BUFF 和包证据 |
| `effects/` | 生命周期、条件、来源绑定、语义批准、窗口及叠加规则 |
| `allocation/` | `HitAllocation`、匹配、基线、乘区、反事实贡献和解释投影 |
| `reporting/` | `ReportState`、计时、参与者、逐击、技能统计及最终报告 |
| `realtime/` | 增量解析、重放、冻结、简报、累计和性能计数 |
| `timing/` | 计时证据、排轮时钟和引导 |
| `diagnostics/` | 系数文档、装备面板、BUFF 审计及命中解释 |
| `battle_splitter/` | 本体历史和上传器共用的 trace 战斗切分 |

摄取流持有可变证据；报告阶段接收隔离快照。单次命中的阶段顺序在 `allocation/hit.py`，报告顺序在 `reporting/battle.py`。资源、typed-root 索引和逐流缓存各有明确所有者。

## 上传兼容

`uploader_core/uploader_core/battle_payload_builder.py` 保留文件构建入口与兼容导出，格式实现位于 `payload/`。

| 文件 | 职责 |
| --- | --- |
| `catalog.py` | 武器、装备目录及运行资源定位 |
| `loadout_evidence.py` | 有序 trace 装备组、场次对应和先前快照 |
| `loadout.py` | 字段归一、证据优先级、装备槽位及上传装备结构 |
| `projection.py` | canonical 报告到上传字段的投影 |
| `files.py` | 完整性读取、分场、跨场属性观测及文件入口 |

上传投影保持现有秒级日期契约；本地分析使用毫秒日期。完整性校验由 `log_integrity.py` 管理。

## 验证

`run_tests.py parser_core` 验证解析与增量；`uploader_core` 验证切分和上传字段。`compare_parser_reference.py` 在独立进程中使用固定源码及依赖比较完整报告、逐击解释、分块摄取和重复快照，并记录源码、资源和依赖哈希。
