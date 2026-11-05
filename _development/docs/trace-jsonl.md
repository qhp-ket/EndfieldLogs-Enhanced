# 结构化 trace JSONL

本规范用于 Python 与 C# 的共同事件边界。当前源码新录制默认使用 JSONL；新配置、未声明格式的已有配置及无效格式均使用该默认值。显式 `service.trace_format: "legacy"` 或 `"jsonl"` 按原选择读取、保存，旧 `.log` 仍可分析及导出。inputlog 格式不变。默认切换的源码修改和专项回归不代表整机性能、资源及最终候选验收已经通过。

GUI 默认未记录；首页按钮或 `Ctrl+I` 启停 session、trace 及启用的输入侧录，每次开始创建新文件组。历史分析和单场导出共用 `HistorySelection`：按原有规则补入必要的角色、敌人属性等前文，排除前场伤害，回放日期取首个回放事件在录制时区的日期，首击 Unix 时间仍用于记录身份。

兼容正文只有时分秒。导出修改日期对应首条实际输出事件的录制本地日期；界面调用 `TraceExportService.DefaultBattleFileName`，默认名 `trace_战斗N-官网兼容.log` 不含日期。旧文本导入优先取文件名中的 `YYYYMMDD`，所以源录制日和首击日均不能直接用于单场默认命名。跨午夜计时、次日后续战斗、两种来源格式及东八区／西五区由契约回归覆盖。

## 现有事件盘点

下表依据当前两版生产与消费源码，不依据日志样本推测。Python 生产目录为 `endfield_pcap/trace/`，消费目录为 `parser_core/ingestion/`；C# 分别为 `Runtime/Tracing/`、`Core/Ingestion/`。同名文件在两版按对应职责映射。历史兼容项不能因当前生产器不再输出而删除。

| 旧标记 | 字段、存在性与生产位置 | 消费位置 | 新事件及字段 |
| --- | --- | --- | --- |
| `HP_V2`、`PKT_MOD`、`PKT_MOD_DETAIL`、`PKT_ATTR_INFO`、`PKT_ATTR`、`PKT_DBG` | `damage.py`／`TraceDamage.cs`；每条 damage detail 的身份、数值、修正项句柄、属性及 protobuf presence；没有属性报告与报告为空不同 | hits、packet_evidence；`HitObservationState`、`PacketObservationState` | `damage`；一条 detail 一个事件，`actors`、`action`、`amounts`、`blackboards`、`evidence`；子观测保持原先后顺序 |
| `DPD_RAW`、`BASELINE` | 仅历史兼容；逐击原始计算及基础属性，不能由新伤害值反推 | fields、packet_evidence；`TraceFields`、`PacketObservationState` | `damage_raw`、`damage_baseline`；显式 hit 身份与原始字段；来源不明时保持未解析 |
| `ACTOR_MAP`、`SQUAD`、`CHAR_SKILLS` | actors、skills、damage、blackboard；映射来源、队伍顺序、技能等级；角色身份只接受已有显式证据 | identity、loadouts、entities；`ActorIdentity`、`LoadoutObservations` | `actor_mapping`、`squad`、`character_skills`；ID 与模板分开，保留顺序与映射来源 |
| `ENTITY_STATS`、`ENTITY_ATTR_UPDATE`、`ENTITY_VALUE`、`ENTITY_DIE` | actors、observations；属性值／基础值，血量、终结能量和死亡观测；缺失字段不同于零 | entities、enemy observations；`EntityObservationState`、展示适配器 | `entity_stats`、`entity_attributes`、`entity_value`、`entity_die`；属性为数组，保留属性类型、值、基础值与 presence |
| `LOADOUT`、`LOADOUT_STATS` | actors；队伍头、槽位装备、强化、精炼、套装、宝石和同步来源；未知装备与已知空装备不同 | loadouts、loadout parser；`LoadoutObservations`、`LoadoutSnapshotParser` | `loadout_group`、`loadout_slot`、`loadout_stats`；保存结构，不保存已拼装的整行 |
| `SKILL_CAST_START`、`SKILL_CAST_END`、`ATB_UPDATE`、`POISE_V1` | skills、resources；技能生命周期、技力、失衡；没有目标的失衡观测不能补造目标 | skills、packet_evidence；`SkillObservationState`、`PacketObservationState`；分析技能／技力／敌方页面 | `skill_cast`、`atb`、`poise`；阶段、实例、来源及时间依据 |
| `BUFF_START`、`BUFF_END`、`BB[uid]` | buffs；合并后的生命周期、原始黑板和顺序；延迟组仍使用原捕获时间 | buffs、buff_observations；`BuffInstanceState` | `buff_start`、`buff_end`、`buff_blackboard`；黑板独立事件，不按时间邻近塞入伤害 |
| `BUFF_CREATE_OBSERVED`、`BUFF_ORIGIN`、`BUFF_ENABLE`、`BUFF_ACTION_UNRESOLVED` | buffs；operation/session/generation、动作 oneof、来源与模板身份、创建／刷新证据及验证错误 | buff_observations；`BuffPacketObservations`、`BuffCreationObservations` | `buff_creation`、`buff_origin`、`buff_enable`、`buff_unresolved`；保留源字段和未解析状态 |
| `BUFF_KEYWORD_UPDATE`、`BUFF_KEYWORD_UPDATE_UNRESOLVED` | observations；更新序号、层数索引／值、presence 和验证错误 | buff_observations；`BuffKeywordObservations` | `buff_keyword`；`validation_errors` 非空表示未解析，不转为有效状态 |
| `BB_MODIFY_DYNAMIC`、`BUFF_ATTR_REFRESH`、`BUFF_ATTR_REFRESH_UNRESOLVED`、`BB_READ_SKILL_SETTING`、`BB_READ_SKILL_SETTING_UNRESOLVED` | blackboard；完整 operation 身份、模板 oneof、runtime／序列化证据 | dynamic_evidence；`BuffDynamicObservations`、`BuffCreationRuntimeProof` | `blackboard_dynamic`、`buff_attribute_refresh`、`blackboard_skill_setting`；保留空 runtime 与缺失 runtime 的区别 |
| `BB_SIMPLE_CALC`、`BB_MULTI_MODIFY`、`BB_SET_PRESET`、`INK_RELEASE` | blackboard、skills；动作、输入／结果、字段存在性及墨迹释放关系 | ink provenance、分析原始证据 | `blackboard_calculation`、`blackboard_modify`、`blackboard_preset`、`ink_release`；独立来源引用 |
| `ABILITY_ENTITY_SPAWN` | skills；实例、来源、实体坐标和旋转 | 原始证据 | `ability_spawn`；实体身份与坐标分开，缺失轴不补零 |
| `ATTR_MOD`、`DMG_MOD` | 仅历史兼容；BUFF属性类型、黑板键与值 | hits、buffs；`LegacyBuffResistance` | `legacy_attribute_modifier`、`legacy_damage_modifier`；保留原证据，不赋予新的白名单权限 |
| `GAME_CLOCK_TICK`、`GAME_CLOCK_SYNC`、`GAME_TIME_FREEZE_REQUEST`、`GAME_TIME_FREEZE_STATE` | context、observations；捕获时间、tick、ping／pong、冻结请求与响应；clock 旁路不得冲刷待处理 BUFF 组 | 实时计时、timer observations、历史分场 | `clock_tick`、`clock_sync`、`time_freeze_request`、`time_freeze_state` |
| `GAME_TIMER_TICK`、`HEARTBEAT`、`LIVE_TIMER_TICK` | 前两项为历史 clock-only 标记；`realtime/live.py`／`LiveBattleSession` 在请求实时快照时临时补入 `LIVE_TIMER_TICK`，不属于抓包生产器输出 | 实时引擎的时钟旁路、timers／`TimerObservationState`；前两项不触发战斗重放，后一项提供当前 elapsedMs | 前两项保留为 `clock_tick` 的历史来源；`live_timer` 为运行时计时观测，不伪装成抓包证据 |
| `GAME_TIMER_START`、`GAME_TIMER_END`、`GAME_TIMER_RESET`、`BATTLE_PHASE_START`、`BATTLE_TIMER_MISSING` | context；tick、耗时、官方标记、边界及来源 | timers、battle_splitter；`TimerObservationState`、`TraceBattleSplitter` | `battle_timer`、`battle_phase`、`battle_timer_missing`；阶段和缺失原因分开 |
| `OFFICIAL_TIMER_START`、`OFFICIAL_TIMER_END`、`OFFICIAL_TIMER_AWAIT`、`OFFICIAL_TIMER_MISSING` | context；gameId、passTime、isPass及presence；未完成不是0秒完成 | timers、分场和报告计时 | `official_timer`；阶段、实测字段、未确定原因 |
| `DUNGEON_CONTEXT`、`CONTRACT_TAGS`、`BATTLE_RESULT` | context；场景、关卡／词条、结果与来源 | timers、stage context、分场、质量及报告 | `dungeon`、`contracts`、`battle_result` |
| `GAME_INST_ENTER`、`GAME_INST_LEAVE`、`GAME_INST_RESTART`、`GAME_MECHANICS_PREPARE_FINISH`、`GAME_MECHANICS_REQ_START`、`GAME_MECHANICS_REQ_STOP`、`GAME_MECHANICS_TIME_FREEZE` | context；副本动作与请求、冻结条目及总计 | 分场、实时计时与原始证据 | `game_instance`、`game_mechanics`；动作、原字段和来源 |
| `SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD` | context 的 mechanics 默认标签保留原消息名；奖励完成通知不等于已观测到官方结束用时 | 原始证据；不能替代 challenge complete／settlement 的结束计时证据 | `game_mechanics`；动作标识保留原消息名，不补造 `pass_time` |
| `SCENE_BATTLE_STATE`、`BATTLE_RESET_STATUS`、`SESSION_WARNING` | context、bridge；场景战斗状态、reset原因、TCP缺口等质量信息 | 分场、报告质量、诊断 | `scene_battle`、`battle_reset`、`session_warning` |
| `IDENTITY_INFERENCE` | 历史兼容诊断；不得凭文本推断替代身份 | Python ingestion 初始化、报告质量 | `identity_inference`；保留推断来源与限制 |

此外，分析曲线、BUFF轨道、输入轴对齐与原始证据视图也使用行号／时间／原标记。迁移时用 `(event_seq, observation_index)` 标识证据；旧导入仍保留原行号。完整报告与质量输出中的标记名称是来源标签，不能把清理字符串依赖误作删除证据标签。

## 文件与事件

UTF-8，无 BOM，每个 JSON 对象一行，以 LF 结束。文件头只在各卷第一行出现：

```json
{"format":"endfield.trace","version":1,"recording_id":"example","volume":1,"previous_volume":null,"generator":{"language":"python","version":"0.3.0"},"timezone":{"id":"Asia/Shanghai","offset_minutes":480},"resources":{"runtime_sha256":"..."}}
```

后续每行是事件：

```json
{"seq":1,"captured_at_ms":1793412000123,"client_tick_ms":1234,"source":{"session_id":"example-session","operation_seq":7,"owner_id":"18446744073709551615","generation":0,"action_id":14,"detail_index":0},"type":"damage","data":{}}
```

- `captured_at_ms` 为完整 Unix 毫秒；不把跨午夜或迟到事件压成递增时间。`client_tick_ms` 只在上游实际有该时钟时出现。
- `seq` 为录制内连续整数，分卷后接续。延迟发出的观测可以具有较早捕获时间；顺序由序号决定。
- 文件头的 `recording_id` 标识整个连续录制，`volume` 从1开始。`previous_volume` 为前卷文件名及其卷号；关联缺失必须在分析／导出中给出不完整提示。
- 事件 `type` 使用表内小写名称。`source` 只包含已存在的上游身份；不把缺失字段补成0或字符串 `unknown`。`data` 为事件专用字段，不能嵌入旧文本行或整个 session。
- 实例ID（actor、buff、skill、projectile、equipment 等）使用十进制字符串。序号、索引、模板数值ID与计数使用整数，数值证据保留原精度。无效上游值保存在未解析证据中，不冒充有效ID。
- 缺失键表示未观测；`null` 表示显式无值；`0`、`false`、`[]`、`{}` 各有自身含义。读取器不统一替换。IEEE非有限值以显式状态及原始类别表示，不输出非标准JSON数字。
- 伤害自身的修正项、属性报告／presence、计算参数及调试证据位于 `data.evidence`。源动作有多个details时分别发出事件，`detail_index` 保留原索引；独立BUFF、属性和黑板事件不合并进伤害。

## 伤害事件边界

一条通过原生产器有效伤害筛选的 detail 对应一个 `damage`；跳过零伤害项不重排 `source.detail_index`。以下字段已接入迁移工作树中的两版生产器与摄取入口；实体属性及其他事件边界分述如下。

| 字段 | 含义 |
| --- | --- |
| `data.hit_seq` | 原命中编号，区别于录制事件 `seq`；会话开始后按原规则重新编号 |
| `data.actors` | 已解析的 `attacker`／`target` 标签及存在时的 `attacker_id`／`target_id`；标签是展示与现有身份规则的输入，不凭技能名补造身份 |
| `data.action` | `skill`、`skill_level`、`template_int_id`、`template_type`、`action_id`、`original_template_int_id`、`damage_unit_index`；实例身份为 `event_inst_id`、`event_owner_id`、`part_inst_id` |
| `data.amounts` | `value` 保留原符号和精度；`current_hp`、`is_crit` 仅在原 detail 有对应字段时保存 |
| `data.blackboards` | 有序 `dynamic` 数组包含 `action_id`／`value`；有序 `calculation` 数组包含 `action_id`／`key`／`value`。重复 action／key 的原顺序保留，摄取沿用旧规则取最后值 |
| `data.evidence` | 当前 detail 的 `modifier_args`、`battle_report_info`、`calculate_damage_check_args` 等原始证据；`presence` 保存独立 protobuf presence，`packet_context` 保存原修正项／属性验证所用的 `packetSeq`、`packetSessionId`，包括无效或缺失的来源状态 |
| `data.legacy_layout` | 旧格式独立导出所需的结构布局；只保存字段顺序、实例 ID 的原始标量类别及规范化丢失的原值，不保存旧文本行 |

摄取先处理伤害，再按旧顺序处理修正项 UID、完整处理器句柄、属性报告 presence 和属性行。冲突仍使对应证据永久未解决，不能被随后合法数据覆盖。实测数值保留在事件中，现有分析投影继续采用旧 `hit` 取整、`raw` 两位小数、HP 整数和黑板六位有效数字规则。新入口直接更新共享状态，不渲染 `HP_V2`／`PKT_*` 后再解析。

伤害中的 `attacker_id`、`target_id`、`event_inst_id`、`event_owner_id`、`part_inst_id` 及嵌套 `buff_inst_id` 统一投影成十进制字符串；无效身份为 `null`，原始无效观测保留在布局中。原先整数与字符串形式的 ID 不混淆。未知嵌套字段保留，后续事件族接入时继续盘点其身份字段。

`legacy_layout` 的 `children` 按字段名记录子布局，`items` 按十进制数组索引记录子布局。旧格式 JSON 需要保序的 `modifier_args` 与 `observation` 子树记录 `keys` 数组，缺失或重复键不能被静默忽略。实例字段使用 `scalar` 标注 `integer`、`real`、`text`、`boolean` 或 `null`；仅规范化会丢失原表示时保存 `raw` 文本（例如前导零、负数或非法字符串）。非有限值在原字段位置使用 `{"number_status":"nan"}`、`positive_infinity` 或 `negative_infinity`，布局以 `nonfinite` 标明类别；有限数值保持原值与精度。这些状态不能作为有限伤害值参与计算。

两版独立伤害导出器只接收事件与原时区偏移，不持有 TraceBridge 状态。保存、读取 JSONL 后，它们恢复原数值表示与修正项键顺序，再生成 `HP_V2`／`PKT_*`。既有固定 TraceBridge 样本用于逐字节验证，不更新原参考。实时摄取不调用导出器。

## 实体属性事件边界

`SC_SELF_SCENE_INFO` 和 `SC_OBJECT_ENTER_VIEW` 按现有规则发出 `entity_stats`，`SC_SYNC_ATTR` 发出 `entity_attributes`。缺少有效属性类型且未观测到等级／血量的完整快照不发出事件；增量属性没有有效类型时也不发出事件。名称映射仍由原生产器维护。

| 字段 | 含义 |
| --- | --- |
| `data.entity_id` | 十进制字符串实体身份；实例 ID 的原标量表示由 `legacy_layout` 保留 |
| `data.template` | 当前显式模板或沿用已有映射，不从相邻事件猜测 |
| `data.kind` | 完整快照的 `character`／`object` 等类别；增量更新不补造类别 |
| `data.attributes` | 原属性数组，包含各条 `attr_type`、`value`、`basic_value` 及其他已有字段；保留数组顺序、重复属性、原精度、空值和字段存在性 |
| `data.level`、`data.hp` | 完整快照中原字段存在时保存，包括显式 `null` 与零；缺失时不补键 |
| `data.object_id` | 增量更新中的对象身份；明确的零仍为 `"0"`，未观测到值为 `null` |
| `data.legacy_layout` | 与伤害共用的标量表示与非有限状态布局，不保存原日志行 |

完整快照进入属性时间轴并替换该实体的暴击观测；增量属性只更新既有暴击观测，不替换完整快照。模板不匹配时清除旧暴击观测；重复属性类型保持失效，后续重复项不能重新使其有效。缺少可转换属性值沿用原生产器的零值，缺少可转换基础值沿用属性值，不能把这些既有兼容规则扩展为其他未知证据的默认值。分析继续使用六位有效数字；原精度及非有限状态仍留在事件中。非有限属性值不进入有效属性字典。

两版独立实体导出器只接收事件和原时区偏移，生成 `ENTITY_STATS`／`ENTITY_ATTR_UPDATE`；完整／增量摄取共用原状态更新规则，不调用旧文本解析或导出器。固定 TraceBridge 样本覆盖伤害与实体的有序混合输出、属性时间轴、暴击状态、角色身份及独立导出字节。

`BattleOpEntityValueModify`、`BattleOpEntityDie` 和生成实体动作分别发出 `entity_value`、`entity_die`、`ability_spawn`。这些与旧标记一样仅作诊断，摄取更新时间上下文，不据此生成属性快照、命中或队伍绑定。`entity_value.data` 按原字段存在性保存 `entity_id`、`operation_seq`、`scene_num_id`、`hp`、`ultimate_sp`、`delta` 及当前／原始来源类型和编号；`entity_die` 未观测到身份时不补键。

每个有效生成实体明细形成一个 `ability_spawn`，顺序不变。动作层保存序号、时钟、动作编号、环境／所有者实例及技能和名称；`detail` 独立保存原始 `source_actor_id`、`entity_id`、`position` 和 `rotation`。来源零仍明确保存为 `"0"`，旧导出沿用回退所有者的规则；缺失坐标轴不补零，原精度、负零和非有限状态均保留。实例统一使用十进制字符串，`legacy_layout` 恢复旧死亡标记等原始标量表示。独立实体导出器同时覆盖这三类诊断，不依赖生产器状态。

## 队伍与角色映射事件边界

`squad.data.members` 是有序数组，每个成员分别保存 `template` 和 `entity_id`，不保存拼好的旧成员标签。场景队伍与装备回退队伍的发出条件沿用原生产器；已有场景队伍时不额外发出装备回退队伍。`entity_id` 使用与实体属性相同的十进制字符串投影及原标量布局，保留原前导零等导出表示。

旧文本入口和结构化入口共用队伍状态更新：观测过的角色 ID 累积保留；当前成员映射保留顺序，同一 ID 重复出现时清空整份当前映射；空队伍只清空当前映射。旧格式成员识别规则继续应用于独立字段中的已有标签，不把任意模板、负 ID 或缺失身份当成已绑定角色，也不把模板截断造成的历史识别差异默默改掉。结构化入口不拼装旧 `SQUAD` 行后再解析。

`actor_mapping.data` 包含 `entity_id`、`template`、`mapping_source` 和 `skill`。`mapping_source` 保留 `skill_attach`、`launch_source`、`launch_projectile`、`damage_original_skill` 等现有来源；`skill` 可以明确为 `null`。生产器沿用已存在的显式来源及去重规则，不用新事件建立额外推断。与旧 `ACTOR_MAP` 一样，摄取只把它视为诊断，不用该诊断修改队伍或角色绑定权限。

两版独立身份导出器按原顺序生成 `SQUAD`／`ACTOR_MAP`，保留原标量表示、空技能占位和时区。固定混合场景同时比较实体状态、队伍映射顺序、角色 ID 集合和导出字节。

## 角色技能清单事件边界

`character_skills.data` 分别保存角色 `template`、十进制字符串 `entity_id` 和有序 `skills` 数组。每条技能观测包含 `skill` 与原始 `level`，不存拼好的技能等级标记。缺失等级、未解析技能模板和重复清单的发出条件沿用原生产器；等级零仍保存为观测，不能因此变成有效技能等级。技能实例到模板的映射仍按原条件更新，缺失等级不会阻止该映射供后续施放使用。

旧文本入口和新事件入口共用技能归一与等级折叠规则：只接受正的精确整数等级，数字技能通过已有表解析；无法解析的运行时技能不参与计算。相同规范技能出现不同等级时整项失效，后续重复不能重新使其有效；整份清单无有效技能时不擦除先前等级。事件内仍保留原顺序、无效等级和数值精度供导出。

精炼补全共用原装备规则：必须有唯一队伍角色绑定、匹配的角色和有效武器实例，当前精炼未知，且官方武器主技能等级能唯一确定精炼。已有精炼零不是未知，不覆盖；缺少身份或等级有冲突时不补造精炼。成功补全另建 `CHAR_SKILLS` 装备观测组，保留证据索引、采集时间与独立历史快照，不修改先前观测组。结构化清单本身不增加队伍身份依据。

两版独立身份导出器按事件和原时区生成 `CHAR_SKILLS`，恢复原等级表示、未知角色实例占位及换行。固定混合样本逐条比较技能等级与装备状态，并验证全部已连接事件的 JSONL 交叉读写和旧正文逐字节一致；独立测试另外覆盖唯一绑定、实例缺失、已知精炼、等级冲突及历史快照隔离。

## 装备观测事件边界

一次业务装备快照先发出 `loadout_group`，再为每个有效对象行依次发出 `loadout_slot` 和 `loadout_stats`；非对象行保留在原槽位／成员计数中，但不生成行事件。不改变已有队伍回退、技能归属和角色别名的更新条件。

| 事件 | 数据 |
| --- | --- |
| `loadout_group` | `reason`、原 `slot_count`／`member_count` 和有序 `roster`；每个名册成员单独保存 `entity_id`，不保存拼好的旧名册 |
| `loadout_slot` | `template`、原 `slot`、角色等级／潜能、武器模板／等级／精炼／突破、装备及套装观测、技能编号和完整性标志；角色、武器、宝石实例分别为 `entity_id`、`weapon_id`、`gem_id` |
| `loadout_stats` | `template`、原 `slot`、武器模板及同步来源、各攻击力观测、精炼证据及来源、来源技能、宝石模板／词条；实例分别为 `weapon_id`、`gem_id`、`gem_weapon_id` |

只保留上游实际存在的字段，不把缺失精炼、等级或攻击力补成已知值。`unplaced_equipment` 是有序 `{entity_id}` 数组；完整性标志严格保留 `true`／`false` 与缺失的区别。实例身份按共同规则投影为十进制字符串，原前导零等标量表示保存在 `legacy_layout` 中。攻击力原始精度、显式零与缺失各自保留。

`equips`、`equip_suit`、`weapon_refine_stats`、`weapon_source_skills`、`gem_terms` 等沿用上游解码器已有的字段专用紧凑语法。这些字段是原始观测，不是整条旧日志；结构化摄取直接解析其子结构，构造与旧入口共用的装备观测对象和合并状态，不重新拼装 `LOADOUT`／`LOADOUT_STATS` 行。

装备合并继续使用原规则：只有完整快照中的空装备能清空已有装备；部分快照不据缺失字段擦除旧值。武器实例更换清除旧武器的精炼、宝石及来源技能，权威覆盖同步作用于当前状态、观测组和活动武器，历史组保持独立。未知字段经原合并规则可能保持缺失，不统一补 `null`。装备事件本身不建立新的队伍身份依据。

宝石辅助精炼仅在当前组的时间戳完全相同、来源为 `SC_SYNC_CHAR_BAG_INFO` 或 `SC_SELF_SCENE_INFO`，且有效武器／宝石实例及绑定关系匹配时参与；歧义、重复或损坏词条不能补造精炼。`LOADOUT_STATS` 原本没有武器等级，因此结构化统计事件不借用其他行的等级补攻击力。分析沿用旧整数攻击力投影，事件和导出仍保留原数值精度。

两版独立装备导出器按事件与原时区生成 `LOADOUT`／`LOADOUT_STATS`，恢复原标量表示、未知占位、字段顺序和换行。固定混合场景逐个装备事件比较当前状态、历史组、活动武器／套装与角色技能，并验证完整已连接事件流的交叉读写及旧正文逐字节一致。

## 技能施放、技力与失衡事件边界

| 事件 | 数据 |
| --- | --- |
| `skill_cast` | `phase` 为 `start`／`end`；`skill_inst_id`、`owner_id` 分别保存技能及角色实例；`owner`、`skill`、`skill_source` 保存该次观测时已解析的身份及来源 |
| `atb` | `owner_id`、`owner`、原 `reason`、`value`、`recovery_speed`、`delta` 和已解析的 `source`／`original_source` |
| `poise` | `attacker_id`、`attacker`、原 `modify_type`、`value`、`current_value`、`owner_type`、来源类型／模板编号、已解析来源及 `action_id`；没有目标身份，不补目标 |

三类事件仅在原字段存在时保存 `operation_seq` 与 `client_tick_ms`；缺失、显式 `null` 和零保持不同。实例投影与其他事件相同，保存原标量布局；模板数值编号不是实例 ID。未解析的身份标签使用 `null`，不把旧格式的 `unknown` 或 `?` 占位变成已确定身份。旧格式导出时才按原规则生成占位。

施放生产器保留原实例有效性、技能映射和角色归属更新条件。结构化与旧文本入口共用施放状态：开始记录加入完整清单及活动实例；同实例再次开始时活动引用指向最新施放，不改写较早记录；结束只关闭匹配实例，以采集时间及证据索引标记，不使用客户端 tick 替换，也不因迟到而重排。不匹配的结束不补造施放。每角色近期索引保留16项，完整施放清单不裁剪；未解析的通用运行时技能不提前建立首次角色动作时刻。

技力保持纯观测：原值、差值和恢复速度保留原精度，分析沿用旧六位有效数字。只将已绑定角色的正有限 `AddValue` 差值记作回能证据，不积分恢复速度，不推算未观测的消耗或初始技力。未知及非有限数值不能转为有效能量；非有限原证据使用共同显式状态保留，仍可独立还原旧导出表示。

失衡直接构造与旧入口共用的观测对象。只有 `PoiseDamage` 且存在明确技能来源时进入逐击失衡证据；当前来源未知时按原规则回退到明确原始来源，模板编号零仍不作为有效匹配编号。没有上限或目标时继续保持未知，不按时间邻近补造敌人身份。

两版独立技能／资源导出器生成 `SKILL_CAST_START`／`SKILL_CAST_END`／`ATB_UPDATE`／`POISE_V1`，保留原时区、开始时的 `captureMs`、结束时角色实例的原表示和数值格式。固定混合场景在每次事件之后比较施放、活动实例、近期索引、回能标记和失衡状态，并验证跨语言 JSONL 字节与独立旧正文。

`damage_sink` 仅替换伤害族输出，`event_sink` 接收已连接的全部生产事件族，两者互斥。Python 禁止将局部模式直接写成旧日志。验证工具的 `trace-observation-events`／`trace-observation-export` 和 Python `--connected` 覆盖已连接的事件；旧 `--entities` 参数作为验证工具兼容别名保留。两版产品录制使用完整事件入口；历史兼容事件与官方 uploader 导出继续保留独立验证。

## BUFF 生命周期与黑板快照边界

`buff_start`、`buff_end` 保存原 `buff_seq`、十进制字符串 `buff_inst_id` 和已解析 `template`；开始另存 `owner`、`source`、`target_id`、`source_actor_id`。未解析标签使用 `null`。结束时 `template_status: "unresolved"` 区分已观测但无法解析的模板与没有先前模板的情况；旧格式导出据此恢复原 `unknown_buff` 或空字符串。延迟组保留原捕获时间、合并顺序与对应的上游来源。

`buff_blackboard` 保存 `buff_inst_id` 与有序 `values: [{key, value}]`，保留原数值精度、正负号、零和非有限类别。分析沿用六位有效数字投影；非有限值只保留键，不进入可用值。该事件继续附到共享摄取状态中的待处理快照，不根据 UID 或时间邻近增加旧入口没有的重绑定规则。

两种入口调用相同生命周期与黑板状态更新。重复活动 UID 建立新快照并继承原实例起点和允许继承的证据，先前快照保留边界；结束只关闭当前活动快照。无效哨兵 UID 仍保留为仅供观察的记录；没有可识别角色或敌人的开始不建立窗口。动态黑板与包级证明分别见后文；仍不能把本节单独视为完整 BUFF 结构化链路。

独立导出器按原编号、精度、时区和换行还原 `BUFF_START`／`BB[uid]`／`BUFF_END`；固定混合场景逐个 BUFF 事件比较完整快照状态及活动／待处理索引。独立测试另检查重复 UID、迟到结束、宽实例 ID、观测哨兵、未知角色及非有限黑板值。

## BUFF 包级证据边界

`buff_creation`、`buff_origin`、`buff_enable`、`buff_keyword` 使用 `data.observation` 保存现有包级证明，字段采用 snake_case；其中 `schema_version` 是原证明版本，区别于 JSONL 文件协议版本。`buff_inst_id`、`source_actor_id`、`target_id`、`owner_id`、`operation_owner_id` 和 `environment_inst_id` 使用十进制字符串。模板、动作编号、序号、generation 与数值不是实例身份。`assigned_items` 和模板 oneof 保留原始嵌套结构，关键词 `modify` 行使用 `config_index`、`rate_after`；未知模板为 null 并以外层 `template_status: "unresolved"` 标记。

新旧入口共用创建、来源、启用及关键词验证，不以结构化格式代替证据审批。创建仍要求活动 UID、匹配模板、session／owner／generation 及原操作边界；重复、乱序与冲突沿用原历史和快照恢复规则。来源必须匹配实例及动作阶段；同操作的相反启用观测保留为冲突。关键词还需已绑定创建、审批来源和当前配置中的标记，缺失或损坏的行保留为未解析更新，不生成可用倍率。

`buff_unresolved` 单独保存 `buff_inst_id`、可选 `operation_seq` 以及 nullable 的 `trigger_type`、`action_id`、`target_id`、`source_actor_id`；缺少序号、显式 null 和零不同。旧占位只在共享兼容适配与导出时恢复。独立导出器恢复原字段顺序、嵌套顺序、精度和换行，启用观测沿用原 ASCII JSON 策略。固定混合场景逐事件比较包括创建历史、未解析动作和关键词状态在内的完整 BUFF 状态，并与原参考正文逐字节比较。

## 动态黑板与属性刷新边界

`blackboard_dynamic`、`buff_attribute_refresh`、`blackboard_skill_setting` 也用 `data.observation` 保存结构化证明。除上述共同字段外，保留 `template_type`、`template_id_case`、`action_type`、`action_runtime_case`、历史 `event_context`、`runtime` 与 `action_serialization`。动作 runtime 的缺失、null、空对象和明细数组不合并；验证错误使用 `validation_errors`，导出时才恢复原 `_UNRESOLVED` 标记。

动态值事件另存原 `operation_seq`、`client_tick_ms`、`buff_inst_id`、`owner_id`、`packet_session_id`、已解析的 `owner`／`skill`、`action_id` 与浮点 `value`。这些是原 scalar 观测，和证明中的 operation／owner／template 独立保留以检查冲突；不能根据证明补造缺失 scalar 字段。身份依共同规则投影，数值保留原精度与负零，旧缺省占位在兼容投影／导出时恢复。

两种入口共享原动态状态机：运行时 client value 是赋值后的结果，不能再次执行 Add／Sub；只暂存到匹配 session、owner、generation 的状态，明确属性刷新才生成参数快照。UID、创建锚点、模板 oneof、动作类型／阶段和当前启用配置仍必须匹配。重复更新保持幂等，迟到冲突使先前快照失效，已观测参数不冒充已验证最终修正值。窄范围历史腐蚀证据仍走共享旧规则，不允许无效现代证明回退为历史证明。

技能设置读取原本仅供诊断，新入口同样不生成动态倍率或属性刷新。三类事件的独立导出保留完整 JSON 嵌套顺序、scalar 字段顺序及换行。固定样本逐事件比较动态／刷新事件、待处理状态、创建历史和完整快照；独立测试禁止在类型化消费阶段反解析 JSON，并检查刷新边界及迟到冲突。

## 黑板计算与笔意账本边界

`blackboard_calculation`、`blackboard_modify`、`blackboard_preset` 共用动态值的原操作序号、tick、实例、owner、packet session、技能和动作字段。计算保存 `key`、`final_value` 和实际存在的 `value_a`／`value_b`；批量修改保存实际存在的 `key`／`value`；预设保存原 `modified_value`。保留原浮点精度、非有限类别及负零，旧导出才应用各标记原有的浮点或六位有效数字格式。生产器内供后续伤害引用的最近计算缓存仍按原顺序保留最近12项。

`ink_release` 的 `data.observation` 保存 `schema_version`、`template_key`、`action_id`、`session_id`、`operation_seq`、`client_tick_ms`、`buff_inst_id`、`owner_id`、`source_actor_id` 和 `projectile_id`。实例均使用十进制字符串；原缺失身份为 null，布局记录原标量表示。独立导出器才恢复旧 `buff_uid` 字段名、顺序及占位表示，不把它们作为已解析身份。

两版笔意账本共用原状态机，增加直接事件观测入口；旧日志只在边界解析为同种观测。计算、动态赋值、释放、角色映射和施放不拼成旧行或做 JSON 往返。源命中仍须满足同 session、目标、tick、前一操作序号及金额匹配；释放冻结来源份额，随后清零累加器不会丢失在途 projectile。重复操作幂等、冲突及乱序保持失效，缺失来源不补造外部贡献。历史映射／施放释放块继续要求同实例、tick 及明确先后关系。

一般摄取入口不把计算观测转成 BUFF 效果。账本直接入口已独立验证分批延续、reset、显式释放及历史释放块。C# 摄取同时维护只读的笔意观测序列，报告快照共享不可变前缀；分配账本优先使用捕获的观测，缺少该输入的旧外部调用保留文本兼容入口。实时笔意缓存按同一摄取所有者与消费数量推进，正常追加不扫描或解析旧文本；来源贡献、记录绑定、回退前缀或更换所有者仍触发独立重放。返回证据与事件生产者相互隔离。Python 直接事件报告、产品发布和历史入口也把相应观测交给同一账本。

## 时钟与计时事件边界

`clock_tick`、`clock_sync`、`time_freeze_request` 和 `time_freeze_state` 保存来源、原始 tick／ping 时间戳、操作序号、消息编号、冻结原因与实际存在的响应状态。缺失字段不补零，显式 null 与零分别保留；负时间戳仍留作原始证据，但不作为可用同步时钟。冻结响应只有原值为布尔时才是已观测状态，数字零或字符串不解释成“未冻结”。

时钟事件沿用原旁路：不冲刷待处理 BUFF 组，也不推进最后语义事件时间；后续 BUFF 仍使用原采集时间和共享事件序号。普通摄取只更新时间上下文，不生成权威耗时、命中或角色绑定。Python 轮转计时已有直接时钟观测入口，旧文本入口调用相同的计时状态；产品计时与分场入口使用同一有序计时状态，仅普通时钟事件不产生战斗开始或完成证据。

`battle_timer.data.phase` 为 `start`、`end` 或 `reset`；字段包含 `source`、`operation_seq`、`scene_num_id`、`start_ms`、`end_ms`、`elapsed_ms`、`packet_elapsed_ms`、`wall_elapsed_ms`、`expire_ms`、`official`、`sane` 和 `fallback` 中实际存在的项。采集墙钟耗时与包时钟差值分开保存，不能用后者覆盖前者。没有有效包 tick 的 `BattleOpModifyBattleState` 仍不构成权威计时。

`official_timer.data.phase` 接入 `start`、`end`、`await` 和 `missing`。保存 `source`、非空 `game_id` 及上游实际存在的 `challenge_start_ts`、`challenge_expire_ts`、`prepare_seconds`、`is_pass`、`pass_time`、`force_leave_ts`；周常结算另保存原规则解析的 `bp_score`、`danger_meter`。缺失、null、零或无效 `pass_time` 不产生正耗时；原布尔时长不会变成 1 毫秒。通关标记和时长独立：观察到通关不等于已经观察到有效结束用时。`battle_phase` 和 `battle_timer_missing` 分别保留阶段与计时缺失；等待和缺失事件不补造完成或时长。

新旧入口共用有序计时状态。新的官方开始清除上一轮完成证据；`CAPTURE_SESSION_START` reset 按原语义清除暴击观测，不额外清空旧入口本来保留的计时状态。官方计时证据在摄取时维护，报告捕获独立副本，避免报告阶段再次扫描整份日志；旧的外部报告输入仍可走文本兼容收集器。独立导出保留原顺序、标量表示、时区和 LF；类型化消费不调用旧行解析器。产品接入及默认格式状态见后文。

`game_instance`、`game_mechanics`、`scene_battle`、`battle_reset` 和 `session_warning` 已接入生产、共享状态及独立旧格式导出。离开／重启按原顺序输出副本、计时缺失与重置；冻结条目保留原计数和有效对象的字段，缺失、null、零与 false 分开保存。奖励通知保持原消息来源，不变成官方完成证据。上下文诊断不推断新伤害、角色身份或用时。

## 关卡与合约事件边界

`dungeon` 保存规范化的 `dungeon_id`、`source` 和实际存在的场景、到期、离开、队伍数量与奖励／结算／通关字段。明确的结算且通过时，先发出 `battle_result`，再发关卡上下文，保持原顺序；战斗开始时重新发出的上下文也继续保留。通关结果本身不补造官方用时。

`contracts` 保存关卡身份、来源、原 `tag_ids` 及备用／显示列表、积分、方向和消息编号的存在性；没有关卡身份时保存 null，不在事件中写入 `unknown`。旧导出才沿用列表回退、过滤零与无效值、整数投影、消息零回退和未知占位。分析保留原文本入口的标签数字投影：负标签的符号仍在原事件与导出中，分析继续使用其绝对值；重复标签不去重。没有关卡的历史分析兼容状态仍保留旧 `unknown` 标签，不将其解析为已知关卡。

两版结构化入口直接进入共享关卡状态，不拼旧行或标签列表再解析。固定混合样本逐条比较关卡、合约、通关和计时状态；该工具使用两端一致的空目录解析器，真实目录解析仍由既有固定计时差分覆盖。

## 历史专用证据

`damage_raw`、`damage_baseline` 的 `data.observation` 保留旧逐击序号的原数字串。原始计算的 `calc`、`atk_scale`、`blocked`、类型、掩码、碰撞体与攻击／防御区域均保留原观测，不由现代伤害反推。基础属性使用有序 `values`，保留重复项，分析仍按旧规则取最后值。浮点数字串保留精度、科学计数和负零；未知区域留作证据。

`legacy_attribute_modifier`、`legacy_damage_modifier` 保存有序 `fields`，每项包含字段名、原值和引号状态。重复字段及其先后顺序不丢失；分析沿用旧筛选和最后值规则，不增加来源权限。孤立逐击明细不凭时间邻近附到其他命中。

`identity_inference` 仅更新诊断质量标记，不建立角色或队伍身份。该诊断以及来源为 `GAME_TIMER_TICK`／`HEARTBEAT` 的历史 `clock_tick`，与旧入口一样结束待处理黑板窗口；普通现代时钟仍保留原旁路。只有旧 `GAME_TIMER_TICK` 进入对应计时观测，心跳不能补造耗时。两版对照同一手工固定历史样本，验证逐事件状态、独立导出及跨语言文件字节。

## 计算与旧格式导出

结构化入口直接更新既有摄取状态。旧文本入口先解析为相同观测，再调用同一状态更新；不得将新事件渲染成旧行再解析，也不得在实时链中序列化JSON后反解析。

C# `LiveBattleEngine.SnapshotEvents` 接收 generation、revision、已消费证据水位及新增事件后缀；重复读取使用空后缀，过期或不连续水位明确拒绝。正常路径不拼接累计文本，不逐项比较既有前缀；批次中途失败后必须从零重放。原事件的 Unix 时间保持不变，报告坐标显式转换为原日志时区的日内毫秒并沿用跨午夜规则。临时观察者时钟直接传递数值，不写回业务证据，也不拼造 `LIVE_TIMER_TICK`。Runtime 的 session、摘要和完整报告发布器已提供事件批次入口；同一业务组不会被快照捕获成半组，reset 的清空帧仍先于新数据。JSONL 采集服务使用该事件入口；入口契约不代表当前版本已经通过独立增量性能验收。

Python `EventBattleParser.snapshot_events` 使用相同的 generation／revision／后缀水位边界，复用原增量归因器的报告投影。输入事件的 Unix 时间保持原值，摄取副本转换为记录时区的日内坐标；数值观察者时钟只影响当前报告。无新事件、相同观察时钟及输出模式复用缓存，返回结果与内部状态隔离；批次失败后拒绝从旧水位继续。`LiveEventOverlayBattleParser` 与旧 live parser 共用战斗边界和发布状态机；正常更新只摄取新增事件，恢复重放限定在当前请求捕获的前缀。发布器及其独立子进程已接入事件批次，保留重置清空帧、旧代结果丢弃和 worker 重启后恢复。

两版服务配置默认使用 `service.trace_format: "jsonl"`；显式 `"legacy"` 保留旧录制路径，C# 保存配置时也保留这一字段。新文件头记录实际生成器版本、录制时区偏移及已有运行资源清单／压缩包的 SHA-256；记录后的事件直接交给完整和摘要发布器。Python 原始 session 历史回放也直接使用事件，保留选定范围前的有效上下文和官方开始证据，不生成临时旧文本。必要的 Python 协议、录制、实时和历史接入维护在 `main/` 工作树；当前版本的独立增量性能与资源验收另行记录。

保留原数值，同时保持旧分析的取整与精度规则：例如伤害 `int(abs(value)+0.5)`、旧 `raw` 两位小数以及部分六位有效数字证据。精度投影由对应旧适配／共享观测构造明确处理，不改变计算结果。仅在用户导出时生成旧布局；需要的编号、字段存在性、子观测顺序和格式类别保存在结构字段中，不存整行副本。导出正文须逐字节匹配固定 TraceBridge 参考。

记录启用时使用常驻流，停止时在完整业务事件边界刷新并关闭文件，再次开始创建新文件组；实时分析会话继续，不因记录启停重置计时／缓存／笔意账本。不增加自动分场或容量轮转。活动文件末尾未完成的一行留待下次读取，不作为完整事件处理。两版交叉读写、旧正文、完整报告、逐击／来源／质量、增量与分卷验证共用既有工具及固定样本。

### 记录启停与历史分卷

两版的“开始／停止记录”均由采集所有者在完整业务调用之间同步启停 session 与 trace；C# 经采集队列，Python 经服务事件循环调度，不调用分析会话结束或重置。JSONL 和显式 legacy 格式均适用；启用的输入侧录随新 trace 路径开始，并在停止时写完缓冲后关闭。既有分卷文件继续按以下协议读取。

新 session 的首行是 `type: "session_volume"`、`schema_version: 1` 的元数据，后续仍为原始业务事件。它包含稳定的 `recording_id`、`session_id`、从 1 开始的 `volume`，以及 `previous_volume: {"volume": 1, "file": "session_…ndjson"}`；首卷的前卷为 null。`event_offset` 表示此前各卷的业务事件行数，不包含文件头。`trace_recording_id`、`trace_volume` 标明配对的 trace，`timezone_offset_minutes` 保留记录时区。各卷位于同一目录，文件名改变后按身份和卷号恢复关联。

历史列表以首卷为记录身份，沿连续业务行分场并按需直接产生事件用于分析；文件头不参与战斗计算。所有来源卷参与索引与快照失效，缺卷明确提示不完整。session 分场区分新的官方挑战与同一挑战中的包计时阶段；已索引战斗按固定业务行范围和 SHA-256 校验，正常追加不影响已有范围，原内容改写、截断或缺卷仍拒绝重放。重命名和列表移除沿用原文件操作，移除不删除原文件。界面导出只生成当前选中的一场，session 导出时重新确认该场范围，纳入同场追加证据并截止于下一场边界；通过同一事件选择器保留必要前文，不带入上一场伤害。独立旧格式导出器生成正文及证明，无需配套 trace 才能导出。输入证据自动发现 session 对应各 trace 卷的侧录及片段，各自校验所关联的 trace；手动时间对齐保存全部已选侧录路径，旧单路径配置继续支持。JSONL 的角色槽位从 `loadout_group`／`loadout_slot` 直接读取，不为输入展示导出旧文本。

C# `TraceRecording.CreateStructured` 显式启用常驻 JSONL 写入：在完整业务调用后按组写入、刷新，再将同一批事件直接交给实时入口。刷新保证完整行对文件读者可见，不等同于每组 `fsync` 或断电持久化；磁盘及交付错误向采集所有者传播。底层 `RotateVolume` 保留既有协议与回归能力，沿用同一个 TraceBridge、待处理 BUFF 和事件序号；首页不再提供手动换卷入口。各卷保留在第一卷目录，跨午夜也不改变目录，避免前卷文件名失去定位能力；资源元数据在创建记录时隔离调用方修改。

`TraceVolumes` 只读取相邻 JSONL 文件头以发现同一录制，按卷号流式读取并校验跨卷序号；重命名后以录制 ID／卷号恢复关联，不改写用户文件。缺卷明确报告不完整，重复卷、元数据冲突、序号缺口及不完整尾行会阻止完整导出。历史索引仅保留分场元数据和各卷来源签名，分场与旧入口复用同一规则；按需分析直接消费所选事件范围及必要前文，使用原记录日期／时区，不先导出旧文本。来源任一卷变化后，旧范围和缓存快照失效。

Python `TraceRecording` 同样使用常驻流，在业务组完成后刷新并直接发布事件；换卷保留生产器、延迟 BUFF 与序号。`trace_volumes` 按录制身份发现同目录分卷，重命名后仍可连读；缺卷、重复卷、来源变化、序号缺口和不完整尾行阻止完整导出。`history.export_trace_log` 对 JSONL 调用公共独立导出器，针对最终旧正文生成证明，保留原文件参考日期。

Python 历史导入接受 `.jsonl` 和旧 `.log`。JSONL 流式提取分场元数据，与旧文本共用范围选择规则；列表阶段不执行报告计算。选中记录后只将该范围的事件交给直接分析入口，报告时间使用记录时区和范围首事件的日期，跨午夜不重复加日。卷链的路径、大小、修改时间与文件身份共同参与索引及快照失效；任一卷追加、重命名或缺失都会重新校验。同一录制从不同卷导入只显示一组记录，以首卷为文件定位和列表移除身份；重命名不改写卷内证据，列表移除不删除文件。

用户导出 JSONL 时，C# `TraceLegacyExporter` 和 Python `trace.legacy` 汇总各自独立事件导出器，最终证明另记录源录制及卷名。固定混合样本的正文 6,292 字节与旧参考逐字节相同；两版最终导出均经未修改的官方 parser／uploader 本地读取、证明校验、业务载荷及原文上传文档构建验证。两版的配对 session／trace 分卷可交叉读取、历史分析和导出；相同合成业务与资源得到相同旧正文，各自的最终证明独立校验。该验证没有登录或网络上传，也不替代当前版本的性能、资源及最终发行验收。
