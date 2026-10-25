# 提取后的运行数据

开发环境和便携版共用这份数据。运行数据包提取自固定的 ZMDLogs 3.0.12 / 2026-10-16
资源，另保留本项目维护的四份开发规则。

## 来源记录

- `runtime-data.zip`：直接来源是固定 ZMDLogs 发行包，下载地址与哈希见 `resource-manifest.json`；
  其中 `akedata` 沿用上游目录名，相关资料来自 [AKEData 数据站](https://data.akedata.wiki/)，不据此推定某个 AKEDatabase commit。
- `local_semantics/team_energy_rules.json`：依据 [AKEDatabase](https://github.com/NagiYume/AKEDatabase)
  的技力机制与技能表提取，提交 `31b53147cd88fb6e9576b5c389967d21687c85cf`、表版本和哈希保留在 `source` 中。
- `local_semantics/skill_frame_rules.json`：依据 AKEDatabase 的角色 SkillData 提取，资源时间、摘要及文件数保留在 `source` 中。
- `game_resource_snapshot.json` 与 `packet_semantics/rdps_semantics_registry.json`：本项目维护的快照元数据和开发版解析规则，保留输入哈希、证据及修改说明。
- `ui/characters/`：独立的离线展示资源，来自 AKEData 图片索引的 35 个角色圆形头像，约 1.18 MB。
  角色映射、原始链接和校验值见该目录 `manifest.json`，更新工具与缺图规则见 [头像维护说明](ui/characters/README.md)。
  不进入 trace、canonical 报告或上传数据，不属于 `runtime-data.zip` 的解析字段投影。

上游源码与 AKEData 的链接集中列在根目录 `THIRD_PARTY_NOTICES.md`；上游 MIT 声明保留原文。

## 体积

原始资源约 390.1 MB；按读取字段提取后为 16.9 MB（2,740 个文件），
源码附带的 `runtime-data.zip` 约 5.8 MB。大小使用十进制 MB，不含 Python、Qt、图片和官网 uploader。

## 保留范围

- 所有已收录 ID 的名称、角色技能分组、潜能、各等级的 HP/ATK/DEF 与四项主属性、武器和装备数值。
- 技能类别、动态黑板动作索引；Buff 持续时间和强化子 Buff 关系。
- 解析器使用的关联关系、分类提示、协议数字映射、乘区与 rDPS 批准规则。
- 时间轴的技能帧和技力规则，关卡、敌人、词条及 GUI 辅助表。
- 严格计算依赖的完整 typed Buff roots、伤害 catalog 和原始证据哈希。

原始技能的动画等配置、未消费的导出字段、重复语义副本、审计扫描和旋转资产不随程序分发。
typed roots 的整体结构和证明保持原样；被解析器计算字节哈希的武器定义也保持原始字节。
三份仅测试使用的审阅/公式证据位于 parser_core 的 `tests/fixtures/runtime_evidence/`。
技能 manifest 仅保留武器 Buff 层数上限所需的 23 条记录；`sourceResourceCount` 和
`sourceManifestSha256` 单独标识原始 2,928 项清单，不能把精简条目数当作完整扫描数量。

提取是静态字段规则，不按某场战斗裁角色或技能。新增读取字段时必须同时更新提取规则，
不能用缺失字段的默认值代替完整数据后再宣布兼容。

## 读取范围与体积复核

资源读取覆盖应用、parser_core、uploader_core，包括按角色、技能、Buff ID 动态拼接路径的分支。当前分组如下：

| 资源组 | 大小 MB | 主要读取者 / 用途 |
| --- | ---: | --- |
| `akedata` | 1.65 | parser、hit_debug、uploader payload、data/loadout、buff_display；按 ID 查定义和名称 |
| `local_static` | 7.23 | parser；完整 typed Buff roots、技能伤害与公式证据 |
| `local_semantics` | 3.51 | parser、battle_energy_evidence、skill_frame_reference；关系、分类、技力与帧规则 |
| `local_tables` | 3.04 | parser、hit_debug、uploader payload、capture/resolver、data/names、data/loadout、trace/bridge |
| `packet_semantics` | 1.24 | parser、capture/resolver、hit_debug；协议映射与语义批准 |
| 消息 ID 表 | 0.18 | message_registry；协议消息识别 |
| `public` | 0.02 | parser；关卡词条名称 |
| `jsondata` | 0.007 | data/names、gui/resources、service、trace/bridge；名称、头像映射和关卡辅助表 |

等级属性表约 1.27 MB，技能 manifest 约 5 KB。数据保留各等级、突破阶段、记录顺序，以及层数提示与创建 Buff 列表的回退顺序。
剩余最大的 `typed_roots.json.gz` 为 3.56 MB、`damage_element_catalog.json` 为 3.34 MB，
含严格解析依赖的对象边界、动作、公式与来源证明，不能当作展示字段直接删除。
其余资源未发现可在保持现有读取和证明语义的前提下再裁去 MB 级内容的项目。

复核索引可重新生成到本地忽略目录：

```powershell
python -B _development/tools/audit_runtime_data.py --references
python -B _development/tools/audit_runtime_data.py --exercise
```

`--references` 输出静态 IO/路径候选、分组大小和大文件列表；含非资源 IO，以免漏掉间接读取入口。
`--exercise` 记录合成场景实际打开的文件。两者都不是完整调用图，未出现的字段不自动等于无用。

## 初始化与打包

```powershell
python -B _development/tools/prepare_resources.py
python -B _development/tools/prepare_resources.py --check
python -B _development/tools/audit_runtime_data.py
```

默认仅解开源码附带的精简数据包，无网络请求。
`resource-manifest.json` schema 2 记录恢复包及每个输出文件的大小和 SHA-256；
开发规则在源码中单独保留，不由包覆盖。已有文件被改动时提示人工核对。
便携构建只复制清单中的输出文件，不递归收集 data、不附带恢复 ZIP 或原始数据。

## 原始数据与重建

完整输入只放本地被 Git 忽略的 `_development/raw-resources/_internal/`；
程序不读取该目录。缺少原始输入时可显式执行：

```powershell
python -B _development/tools/prepare_resources.py --raw
python -B _development/tools/prepare_resources.py --raw --archive PATH --offline
```

重建到一个新的目录，先比较，再安装：

```powershell
python -B _development/tools/extract_runtime_data.py --source _development/raw-resources/_internal --output _development/verification/new-runtime
python -B _development/tools/verify_runtime_projection.py --raw _development/raw-resources/_internal --runtime _development/verification/new-runtime --output _development/verification/runtime-comparison
```

开发规则始终从当前源码取值。审核通过后，在 Python 中调用提取工具的
`activate(project_root, projection_root)`，或使用一个新输出目录重新执行提取命令并添加 `--install`。
首次安装会先完整校验并归档安装前的输入；输出 ZIP 采用固定时间戳，可重复生成。

等价检查覆盖规范化解析目录、所有技能动作索引、Buff 派生规则、合成 trace 的完整报告、
Overlay 和 uploader payload，以及 GUI 数据。另需运行应用、parser_core 和 uploader_core 全套回归。
不要仅因一份日志通过就删除其他角色、敌人或回退所需的字段。

## 新角色与资源升级

提取工具的 `ITEMS` 定义目录，`FIXED` 定义共享表，`project()` 定义保留字段；没有角色 ID 白名单。
同一来源清单新增的角色、技能、Buff 和等级文件会按目录自动收录；缺少清单登记的原件则拒绝提取，
避免因下载不完整而悄悄漏掉角色。增加一个角色不需要增加一份专用提取代码。

更新上游版本时，先核实完整发行 ZIP、SHA-256 和数据解码版本，再同步提取工具的 `SOURCE`、
原始输入清单和对应的 typed 证据绑定。使用新的本地原始目录，保留基准版本用于比较；
不要把网站最新 JSON 直接覆盖进基准版本的已校验目录。确认共享 manifest、数字映射及技能/Buff 条目一起更新。
四份开发规则从当前源码保留；新的外部 rDPS 效果仍须单独审核批准，不能因出现新 ID 就自动批准。
随后按上面的“重建、对照、回归、安装”步骤生成恢复包和新清单，再构建发行版。

新增字段时同步修改 `project()` 和读取代码；新增目录时同步修改 `ITEMS` / `FIXED` 及用途说明。
字符名称来自角色 manifest，技能显示可回退到解析器名称或原 ID；独立显示词典只增强显示，
不作为识别新角色的必要条件。新技能没有帧配置时，保留日志起止／命中证据，不借用别人的时长。

若日志中的角色不在资料中，或其角色定义缺失，仍保留有明确身份和目标证据的伤害、计时、
实时汇总和本地分析；名称可显示原 ID，头像可为空。缺少动作、属性或 Buff 语义时，
对应 rDPS 保持待确认并保留质量原因，不猜测角色数值或给出完整归因承诺。
这不保证未来协议变化仍可解码；缺失角色条目也不同于整份关键数据包损坏，后者应重新恢复校验。

相关回归在 `_development/tests/resources/test_runtime_projection.py` 和
`_development/tests/resources/test_missing_character_resources.py`：包括未见过的新 ID 自动提取、
原件缺失拒绝，以及缺少角色资料时历史报告、实时摘要和本地时间轴仍可使用。

项目的代码许可不会重新授权游戏数据、图片或外部资料。提取不改变其来源和权利边界，
见根目录 THIRD_PARTY_NOTICES.md。
运行数据包的直接来源以固定 ZMDLogs 发行包和哈希为准；
单独维护的 AKEData 派生规则以各自的 `source` 为准。
