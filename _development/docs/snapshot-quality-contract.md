# Snapshot Quality Contract v1

本次范围仅为 canonical parser 结果增加证据质量投影和四入口回归门禁。输入窗口、战斗边界、伤害与 rDPS 分配算法、DPS 时长算法、旧数值、fingerprint、parser/rules version 均沿用原实现。

## 接口与兼容性

直接 `parse_raw_battle_log_text` 的两类成功返回（正常战斗、有上下文但无伤害）均新增顶层 `snapshot_quality`。`parse_upload_battle_log_text` 自然继承；hit viewer、overlay 显式透传相同对象，`LiveOverlayBattleParser` 通过 overlay 接口自然继承。live 的窗口、刷新、缓存与时钟策略没有修改。

Overlay 还补传原来的 `rdps_preflight`、`unresolved_hits`、`unresolved_buff_actions`，原有 `rdps_damage_basis` 保留。viewer 原来已有这四个证据字段，本次增加 quality。四入口的含义为 raw / hit viewer / overlay snapshot / live snapshot；上传 wrapper 另外检查与直接 raw 等价。

```json
{
  "snapshot_quality": {
    "schema_version": 1,
    "status": "provisional",
    "rdps": {
      "status": "provisional",
      "reasons": ["rdps_preflight_ok_failed"],
      "evidence": {
        "rdps_preflight": {},
        "rdps_damage_basis": {},
        "unresolved_hits": [],
        "unresolved_buff_actions": []
      }
    },
    "timing": {
      "status": "provisional",
      "reasons": ["timer_integrity_unknown"],
      "evidence": {
        "duration_ms": 2000,
        "timer_integrity_ok": null
      }
    }
  }
}
```

示例为结构节选，实际 `reasons` 包含全部适用的投影理由，timing evidence 固定包含模块 `_TIMING_FIELDS` 声明的全部键。实现为 `parser_core.snapshot_quality.build_snapshot_quality(report)`；它只读取已有结果，不解析日志、不重新求和、不验证或推断游戏证据。

## 三态的适用范围

| 状态 | 含义 |
| --- | --- |
| `verified` | 该维度的必要证据显式通过，且没有投影识别的负面证据。 |
| `provisional` | 数值结果仍存在，但存在未通过、缺失或未完成的必要验证。 |
| `unavailable` | 该维度缺少可用基础：rDPS basis 缺失或显式无 hit；计时无正数 duration 或窗口显式无效。 |

聚合 `status` 优先级为 `unavailable` > `provisional` > `verified`。例如 rDPS verified、timing provisional，则聚合 provisional；这不撤销 rDPS 子状态。聚合 unavailable 也不会删除任何已算出的数值。

这是 rDPS 归因和计时证据的契约，不是整场战斗的真实性、账号身份、上传资格或所有显示元数据的通用认证。未完成官方计时验证只表示 provisional，不代表计时错误或篡改。

### rDPS

verified 必须同时满足：

- `rdps_preflight.ok`、basis 的 `rdps_preflight_ok`、`rdps_strict_ok`、`rdps_conservation_ok` 均严格为布尔 `true`。
- preflight `blocker_count` 为整数 0，`blockers` 为显式空列表。
- basis `hit_count` 为正整数。
- 如 basis 报告未解析伤害角色、缺失 packet hit 或单 hit 守恒差异，则必须没有这些负面计数。

缺少必要字段不会默认通过。数值守恒本身不等于来源已验证。原始 blocker 的 reason、missing、UID、来源等保留在 evidence；投影 `reasons` 只给稳定的质量理由代码，不替换原始解释。

`unresolved_hits` 和 `unresolved_buff_actions` 保留原始完整列表，其范围可能比当前战斗窗口大。是否阻断当前战斗沿用 canonical preflight / basis 已有的窗口判定，quality 不另做跨窗口筛选或把历史未解析行自动当成本场错误。

### Timing

verified 必须有正数且有限的 `duration_ms`、非空 `time_source`、显式 `timer_integrity_ok=true`、显式空 `timer_integrity_reasons` 列表、显式 `timer_window_valid=true` 和显式 `timer_start_inferred=false`。推断起点或未完成官方校验保持 provisional。原始官方/packet 计时、零点来源、起止观察、timer evidence、完整原始失败理由均透传到 evidence。

`timer_integrity_ok=false` 保持 provisional，并保留原始理由；只有原核心同时给出无效窗口或不可用 duration 时计时才 unavailable。quality 不纠正时间、不用墙钟覆盖游戏时间，也不比较不同时钟域来推断篡改。

## Null、零与 JSON

缺失证据投影为 `null`，已知的 0 保持 0；缺失列表为 `null`，已知空列表为 `[]`。无伤害 report 的既有 0 数值和 roster 展示仍保留；rDPS/timing quality 为 unavailable。完全空输入仍由 raw/viewer/overlay 抛出原 `ValueError`，live 初始/重置后仍可能返回 `None`，没有伪造一个 report。

quality evidence 是递归复制的数据，修改 quality evidence 不会修改原始 preflight、basis 或未解析列表。复制时，绝对值超过 `2^53-1` 的整数转成十进制字符串以防 JavaScript 舍入；UID 字符串原样保留；非有限浮点投影为 `null`，对应不可用计时带理由。旧字段不转换、不删除、不覆写。quality 必须能通过 `json.dumps(..., allow_nan=False)`。

没有写入 `battle.rdps_available`。旧 Overlay 用该字段控制 rDPS/DPS 显示回退，因此质量必须作为独立字段供未来消费者采用，本次不改变旧 UI 的数值与显示。

## 回归门禁

`_internal/packages/parser_core/tests/test_snapshot_quality.py` 使用 `fixtures/rdps_snapshot_contract.log` 断言四入口的总伤害 760、总 DPS 380、时长 2000 ms、rDPS 总归属 640/120、参与者 rDPS 320/60，且质量与原始证据一致。fixture 数值守恒，但缺少严格 action-unit 证据和官方计时验证，结果应为 provisional。

门禁还覆盖官方计时成功与冲突、每个必要验证字段缺失、负面 rDPS 与计时证据、null/0、上下文无伤害、空文本原异常、uint64 与证据副本隔离、live 无新输入缓存、reset、连续官方战斗的质量隔离。单纯投影的正控用显式合成证据验证 verified 路径，不声称该合成对象是真实完整战斗。

测试使用准备好的开发环境，不需要真实抓包密钥或私人日志。

## 边界与后续

质量契约不改抓包、解密、协议、原伤害或 rDPS 数学，也不代表官网后端的上传审核结果。
GUI/Overlay 可显示质量摘要；完整接口保留证据明细，不能将缩减摘要冒充完整质量对象。
