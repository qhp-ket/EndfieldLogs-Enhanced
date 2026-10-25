# 预期失败用例

本目录包含 109 项显式标注的预期失败，用于核对测试输入、断言与当前证据契约的差异。
各用例声明具体原因、`strict=True` 和限定的异常类型；意外通过或声明范围外的异常都会使测试失败。

| 分类 | 数量 | 核对范围 |
| --- | ---: | --- |
| `attribution` | 61 | typed 批准、实际基线/包字段、归属和解释字段 |
| `mapping_and_report` | 16 | 静态别名/技能映射、候选或 confidence 结构、显示名与报告投影 |
| `identity` | 13 | actor/目标恢复、短 ID/装备推断、映射字段契约 |
| `lifecycle` | 13 | 持续时间、同帧刷新、层叠实例、缺少结束证据的推断 |
| `hit_evidence` | 6 | 缺精确 action/unit、伤害类别和条件状态的样本 |

这些用例需要逐项核对输入证据和预期，不能直接视为 109 个当前功能故障。
[`review.json`](review.json) 记录每项名称、文件、实际失败点、异常类型和分类，供复核时与源码中的标记对照。
正常契约用例见 [`../reporting/test_unbound_display_evidence.py`](../reporting/test_unbound_display_evidence.py)：

- DPD 不提供未知命中的伤害元素，也不能借此分配外部贡献。
- 已知技能 family 可以归一化；没有绑定证据的伤害 BUFF 不能被吸入同一次连携施放。
- 缺少施放绑定时保留大招各伤害阶段的技能键与伤害，不凭名称构造一次施放。

本目录随 `parser_core` 全套执行，也可单独运行 `python -B _development/run_tests.py legacy`。
调查实际断言时追加 `--runxfail --tb=short`；该模式关闭 xfail，预期返回非零，不能作为正常验收命令。
