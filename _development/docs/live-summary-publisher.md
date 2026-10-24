# 实时摘要与按需完整报告

2026-10-23。此文描述当前实时发布路径；最初的完整快照接口仍然兼容。

## 输入与计算

`TraceBridge` 仍把同一份 canonical trace 行按相同顺序落盘并交给 service。service 将行交给摘要 publisher，同时保留完整 publisher 的当前输入。没有改抓包、解密、trace 文本和上传格式。

两种分析使用相同的 `LiveOverlayBattleParser`、增量 ingestion、BUFF/属性语义、贡献分配、笔意账本、计时和质量规则。区别是报告投影：

```text
canonical trace
  ├─ 摘要进程：语义与贡献 → battle / participants / quality_summary
  │                    → Qt queue / summary WebSocket → 内置伤害窗
  └─ 按需完整进程：相同核心 → analysis_snapshot → 完整 observer / 自定义模板 / 原 WS
历史分析：按需读取文件 → 原完整报告（全部时间轴、悬停与选项）
```

摘要分支不构建展示用时间轴、角色技能构成、完整 BUFF 展示事件、暴击上下文明细和完整质量证据，再将它们删除。它仍构建计算必需的语义窗口、逐击贡献及严格质量判断。BUFF 浮窗消费独立的 `buff_snapshot`；连携 CD 已停用，不再发布 `combo_snapshot`。

## 消息与订阅

服务仅监听 `127.0.0.1`。带 `Origin` 的网页连接必须在查询参数中提供 `access_token`，
与当前保存配置的随机 `ws_browser_token` 匹配；未授权连接在握手阶段返回 403，发送任何战斗数据前即拒绝。
兼容新版 `(connection, request)` 和 legacy `(path, request_headers)` 两种回调结构；
处理器也分别读取 `request.headers` 或 `request_headers` 再次校验，无法识别的请求结构默认拒绝。
`Origin: null` 的本地文件或沙盒页面也必须带凭据。设置页可复制含凭据的摘要 WS 地址；
访问完整流时保留 `access_token`、移除 `analysis=summary` 即可。不要把凭据交给不可信页面或写入公开模板。
旧配置加载时生成凭据，保存到被忽略的个人设置；配置 repr 不输出该字段，发行包不收集个人设置。

不带 Origin 的原生本地客户端仍可使用原有接口。这是防未授权网页访问的边界，
并非隔离本机程序的完整身份认证。GUI 的进程内模板桥保持原样。

摘要入口是 `/ws?analysis=summary`。连接后依次收到 `hello`、当前 `analysis_summary`（无状态时为 null）、当前 BUFF 状态，随后接收后续状态。raw `event_batch` 仍保留。

```json
{
  "type": "analysis_summary",
  "schema_version": 1,
  "stream_id": "service-stream",
  "sequence": 42,
  "source_generation": 3,
  "source_revision": 812,
  "snapshot": {
    "battle": {},
    "participants": [],
    "quality_summary": {}
  }
}
```

- `battle` 为关卡、对象、起止、时长、团队 DMG/DPS、队伍和计时质量相关字段；明确字段集合见 `parser_core.live_summary.BATTLE_FIELDS`。
- `participants` 使用 canonical overlay 角色统计，包括 DMG、rDMG、DPS/rDPS、最大伤害/贡献与暴击统计。前端仅排序、画条和格式化；不能累加伤害或重算 DPS/rDPS。
- `quality_summary` 来自同轮 canonical preflight/basis 和质量逻辑，包含整体、rDPS、timing 的状态/原因及阻塞计数。它独立命名，不冒充带完整证据的 `snapshot_quality`。
- `snapshot: null` 是清空；`error` 可随清空帧给出异常。reset、停止、错误等控制边界不能被较新数值状态合并掉。
- `stream_id` 与 `sequence` 用于丢弃重复、过期和已退休流。`source_generation` 隔离显式 reset；`source_revision` 标识实际完成分析的输入版本，不是发送时已接收的最高水位。
- 新证据完成分析后，即使显示数值不变，也可发布带新来源版本的状态；没有重新分析的缓存读取与结束后纯心跳不会推进版本或重复发布，空启动也不反复发清空帧。
- 摘要与完整报告独立计算，不保证同时完成。仅来源 generation/revision 相同的内容可视为同一轮结果。当前内置伤害窗只消费摘要，不把较旧明细拼入摘要。

原 `/ws` 仍返回 `analysis_snapshot`，完整字段和 `snapshot_quality` 继续提供。完整、摘要均采用整个状态替换。默认 `current_message()` 返回独立副本；service 可只读借用不可变的已发布版本，并在 observer 边界隔离副本。

## 调度与隔离

摘要完成驱动，最短启动间隔 100 ms。一次计算超过 100 ms 时，完成后立即取最新积累输入；同时只有一个计算，不为每批输入另排旧任务。输入仍全部保留、按序处理。

服务成功启动抓包后即在后台预热摘要进程，争取在进游戏/开战前完成静态数据加载；不等待预热完成才接收输入。首次冷加载成本仍单独报告。

完整进程只在存在完整 WS 连接（包括握手中）、完整 observer 或启用的完整自定义模板时运行。最短启动间隔 1 秒；首个消费者要求当前状态，无须等待下一次伤害。最后一个完整消费者离开后可关闭进程，后来重新连接时从保留输入恢复；禁止复用 reset 前的缓存。

每个 WS 连接有独立发送任务和待发送状态队列。较新状态替代尚未发送的同流旧状态，控制帧保持顺序；超时/持续落后的诊断消费者断开。完整 JSON 序列化和 observer 复制移到线程，避免长时间占住 service 事件循环。Qt 待显示摘要也只保留控制边界内最新一版。

reset 会先发布 null，再分析下一场；忙碌中的旧 generation 结果被丢弃。完整发布等待刷新间隔或异步复制期间发生 reset，也重新校验版本。独立分析进程故障时保留输入、清空错误状态，然后在新进程恢复，不把故障当作正常换场丢掉证据。

## 复用与诊断

- 行 ingestion、相关笔意/计时行索引随新增输入维护。别名/原始前缀变化仍允许重放。
- 贡献总量与最大贡献维护 canonical 顺序的前缀累计；修正时回撤并重算受影响后缀。
- 摘要的窗口内 DMG、暴击计数和最大伤害可撤回旧命中再应用新命中；视觉最大伤害沿用相同角色/目标/技能分组规则，只重建变化的组，晚到命中按原排序处理。完整报告继续保留技能明细汇总。
- 未变依赖记录使用隔离副本复用；大量只读命中证据及 BUFF 创建/来源证明使用内容精确匹配的 detached immutable 缓存。不能仅按 UID 或超时冻结；意外写入触发保护并用独立图重放。
- 仅已证明纯时钟变化、且不可能扩展语义成员的活动战斗可复用贡献并更新共享计时派生值。条件不满足时仍走语义分析。
- 官方结束后的纯心跳不重新构建报告、不重新分配；迟到伤害、属性、BUFF、来源和未知输入仍按保守路径分析。无伤害且无可报告状态是正常等待。
- 分析进程在 ingestion 前预载静态元数据并冻结其 GC 图，减少常驻大图的周期扫描，不冻结战斗中的可变状态。

诊断区分 `semantic`、`clock`、`cached`；提供新增输入、状态复制、准备、语义窗口、分配、质量、角色汇总、明细投影、输出阶段耗时，以及队列、数据转换和 IPC 耗时。另有 report builds、原始行重放/原因、贡献重算/复用、整场贡献缓存重载/原因、笔意账本重建/原因、连续未决后缀起点。

尚非恒定耗时：语义窗口、依赖比较、严格质量检查和一部分状态复制仍访问历史；汇总也仍扫描命中签名以发现修正。早期未决证据可能让连续后缀长期不闭合。不能通过强行闭合或降低检查来满足延迟指标。

## 验证与测量

```powershell
python _development/run_tests.py parser_core
python _development/run_tests.py live
python _development/run_tests.py uploader_core
```

持续回放不等待计算完成；对每个输入水位计时到首个覆盖它的摘要，以及真实 WebEngine DOM 更新。合并掉的显示版本仍计入水位延迟。冷启动单列，官方结束后的输入不混入战中延迟分位数。完整消费者测试使用独立完整 worker 和真实 localhost WS 接收端。

真实个人日志和针对它们的实验脚本保留在本地忽略目录，不是源码回归前提。
DOM 测试使用 offscreen WebEngine，不能代替显示器、Npcap、游戏网络和物理上屏实测。
官方结束后 GAME_CLOCK_SYNC 仍可能进入语义更新，是目前剩余优化点，不能把纯 TICK
心跳测试通过外推为全部真实同步事件均不会重算。
