# Snapshot Quality Contract v1

`snapshot_quality` 投影 canonical 报告中的 rDPS 归因和计时证据。
实现：`parser_core.snapshot_quality.build_snapshot_quality(report)`。

## 入口与结构

raw、upload、hit viewer、overlay 和 live 接口共享质量字段。
正常战斗及有上下文的无伤害报告均包含质量对象：

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
      "evidence": {"duration_ms": 2000, "timer_integrity_ok": null}
    }
  }
}
```

示例节选了 timing evidence；完整键集见 `_TIMING_FIELDS`。
`reasons` 为稳定的质量代码，原始理由、来源和 UID 保留在 `evidence`。

## 状态

| 状态 | 含义 |
| --- | --- |
| `verified` | 必要验证显式通过，投影识别的负面证据为空 |
| `provisional` | 数值可用，但验证失败、缺失或尚未完成 |
| `unavailable` | rDPS basis 缺失或显式无 hit；计时 duration 无正数或窗口显式无效 |

聚合优先级为 `unavailable` > `provisional` > `verified`，各维度状态和已计算数值独立保留。
适用范围为归因和计时质量；上传资格由官网校验。

### rDPS verified 条件

全部满足：

- `rdps_preflight.ok` 和 basis 的 `rdps_preflight_ok`、`rdps_strict_ok`、`rdps_conservation_ok` 严格为布尔 `true`。
- preflight 的 `blocker_count` 为整数 0，`blockers` 为显式空列表。
- basis 的 `hit_count` 为正整数。
- 如有未解析伤害角色、缺失 packet hit、单 hit 守恒差异计数，均须为零。

`unresolved_hits` / `unresolved_buff_actions` 保留完整范围，当前战斗的阻断判断沿用 canonical preflight/basis。

### Timing verified 条件

| 字段 | 要求 |
| --- | --- |
| `duration_ms` | 正数且有限 |
| `time_source` | 非空 |
| `timer_integrity_ok` | 显式 `true` |
| `timer_integrity_reasons` | 显式空列表 |
| `timer_window_valid` | 显式 `true` |
| `timer_start_inferred` | 显式 `false` |

推断起点、校验缺失或 `timer_integrity_ok=false` 为 provisional。
无效窗口或不可用 duration 为 unavailable。原始官方/packet 计时、零点、起止观测和失败理由透传到 evidence。

## 数据类型与隔离

- 缺失字段为 `null`，已知零和空列表分别保留 `0`、`[]`。
- 无伤害报告保留零数值及 roster，质量为 unavailable；空文本由 raw/viewer/overlay 抛出 `ValueError`，live 初始及 reset 后可为 `None`。
- evidence 递归复制；绝对值超过 `2^53-1` 的整数转十进制字符串，UID 字符串保留，非有限浮点转 `null`。
- 原报告字段保持原类型和值，质量对象须通过 `json.dumps(..., allow_nan=False)`。
- `battle.rdps_available` 控制显示回退，`snapshot_quality` 提供证据质量，消费者分别读取。

完整接口携带证据明细，轻量接口使用 `quality_summary`。

## 回归入口

`tests/reporting/test_snapshot_quality.py` 验证 raw / viewer / overlay / live 四入口及 upload wrapper 等价。
合成 `rdps_snapshot_contract.log` 的断言为：伤害 760、DPS 380、时长 2000ms、rDPS 归属 640/120、参与者 rDPS 320/60，质量 provisional。

其他覆盖：verified 合成正控、必要字段缺失、计时冲突、负面证据、null/0、uint64、证据副本隔离、live 缓存/reset 和连续战斗。
