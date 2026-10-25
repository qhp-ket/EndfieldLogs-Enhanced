# 实时摘要与完整报告

## 数据链路

`TraceBridge` 将同一份 canonical trace 有序落盘并交给两个 publisher。
两者共用 `LiveOverlayBattleParser` 的增量语义、贡献分配、计时和质量规则，分别生成展示投影：

```text
canonical trace
  ├─ 摘要进程 → battle / participants / quality_summary → Qt / summary WS → 伤害浮窗
  └─ 完整进程 → analysis_snapshot → 完整 WS / observer / 自定义模板
历史文件 → 按需完整分析 → 战斗分析界面
```

摘要只构建计算必需的语义窗口、逐击贡献和质量结果。
连携 `combo_snapshot` schema 2 由 GUI 的独立视觉服务发布。

## WebSocket

服务监听 `127.0.0.1`，两个入口均发送当前 BUFF 状态及后续状态，保留 `event_batch` 诊断流。

| 入口 | 初始消息 | 后续战斗状态 |
| --- | --- | --- |
| `/ws?analysis=summary` | `hello`、当前摘要、当前 BUFF | `analysis_summary` |
| `/ws` | `hello`、当前完整报告、当前 BUFF | `analysis_snapshot`，含 `snapshot_quality` |

带 `Origin` 的连接（含 `Origin: null`）须提供查询参数 `access_token`，匹配配置中的随机 `ws_browser_token`。
缺失或错误凭据在握手返回 403；请求结构无法识别时拒绝连接。无 Origin 的原生本地客户端可直接连接。

握手和处理器分别兼容以下结构并校验：

- asyncio：`(connection, request)`，读取 `request.headers`。
- legacy：`(path, request_headers)`，读取 `request_headers`。

配置缺少凭据时生成并保存到个人设置，配置 repr 隐藏该字段。远程模板凭据由用户管理。

## 摘要消息

```json
{
  "type": "analysis_summary",
  "schema_version": 1,
  "stream_id": "service-stream",
  "sequence": 42,
  "source_generation": 3,
  "source_revision": 812,
  "snapshot": {"battle": {}, "participants": [], "quality_summary": {}}
}
```

| 字段 | 语义 |
| --- | --- |
| `battle` | 关卡、队伍、起止、时长、DMG/DPS 及计时质量；集合见 `parser_core.live_summary.BATTLE_FIELDS` |
| `participants` | canonical 角色统计：DMG、rDMG、DPS/rDPS、最大值及暴击；前端排序、画条和格式化 |
| `quality_summary` | 同轮 preflight/basis 的整体、rDPS、timing 状态、原因和阻塞计数 |
| `snapshot: null` | 清空状态，可携带 `error` |
| `stream_id` / `sequence` | 识别消息流及顺序，丢弃重复、过期或已退休流 |
| `source_generation` | reset 边界 |
| `source_revision` | 实际完成分析的输入版本 |

每条状态整份替换。摘要与完整报告各自完成，只有 generation/revision 相同才属于同轮结果。
缓存读取和结束后的纯心跳保持版本；新增证据完成分析后可发布数值相同的新版本。
`current_message()` 返回独立副本；service 可只读借用已发布版本，在 observer 边界复制。

## 调度与恢复

- 摘要最短启动间隔 100ms，同时运行一次计算；完成后处理最新积累输入。
- 抓包启动后后台预热摘要进程，输入同步接收，冷加载耗时单列。
- 完整进程按 WS 连接、握手、observer 和模板需求启动，最短间隔 1s；首个消费者立即请求当前状态。
- 最后一个完整消费者离开后可释放进程；重新连接时从保留的有序输入恢复。
- 每个 WS 连接独立发送并保留同流最新待发状态，控制帧按序发送；持续落后的连接断开。
- reset 先发布 null，再进入下一场；计算及异步发布都校验 generation，丢弃过期结果。
- worker 故障时保留输入、清空错误状态，再由新进程恢复。

JSON 序列化、observer 复制在后台线程执行；Qt 在控制边界内只保留最新待展示摘要。

## 增量复用与诊断

增量 ingestion 维护笔意/计时索引、贡献前缀累计和变化组。迟到证据触发后缀回撤，必要时有序重放。
命中签名、依赖比较、严格质量和部分复制仍访问历史，因此耗时随证据规模变化。

复用条件：

- 依赖内容精确匹配时复用隔离副本或 detached immutable 证据；意外写入触发重放。
- 已证明纯时钟变化且语义成员稳定时，只更新计时派生值。
- 官方结束后的纯心跳复用报告；迟到伤害、属性、BUFF、来源及未知输入继续分析。
- 静态元数据预载后冻结 GC 图，战斗可变状态由正常生命周期管理。

诊断区分 `semantic`、`clock`、`cached`，记录各计算阶段、复制/IPC、队列、水位、重放和贡献复用情况。
早期未决证据可能延长待计算后缀，`GAME_CLOCK_SYNC` 也可能触发语义更新。

## 验证

相关测试位于应用 `service/` 与核心 `live/`、`reporting/`，运行方式见 [测试分类](../tests/README.md)。
持续回放按输入水位计量到摘要及 WebEngine DOM 更新的延迟，合并显示版本也计入；冷启动、战中和战后分开统计。
完整消费者使用独立 worker 和真实 localhost WS。显示器、Npcap 和游戏网络另行实机验证。
