# 旧预期审查

2026-10-24 对原 112 项预期失败使用 `--runxfail` 实际执行，核对触发失败的断言和原始输入。删除根目录 conftest 中按测试名称统一添加 xfail 的名单，改为各用例显式声明原因、`strict=True` 和限定异常类型。

3 项已迁移到 [`../reporting/test_unbound_display_evidence.py`](../reporting/test_unbound_display_evidence.py)，用同样输入验证现行契约：

- DPD 不提供未知命中的伤害元素，也不能借此分配外部贡献。
- 已知技能 family 可以归一化；没有绑定证据的伤害 BUFF 不能被吸入同一次连携施放。
- 缺少施放绑定时保留大招各伤害阶段的技能键与伤害，不凭名称构造一次施放。

其余 109 项暂保留：

| 分类 | 数量 | 尚需核对的内容 |
| --- | ---: | --- |
| `attribution` | 61 | 当前 typed 批准、实际基线/包字段、归属和旧解释字段 |
| `mapping_and_report` | 16 | 静态别名/技能映射、候选或 confidence 旧结构、显示名与报告投影 |
| `identity` | 13 | 旧 actor/目标恢复、短 ID/装备推断、已移除的映射字段 |
| `lifecycle` | 13 | 持续时间、同帧刷新、层叠实例、缺少结束证据的旧推断 |
| `hit_evidence` | 6 | 缺精确 action/unit、伤害类别和条件状态的旧样本 |

这些是**旧输入与旧预期的差异清单，不能直接当作 109 个当前功能 bug**。有的样本缺少现行证据，有的字段已经改变，也有的预期仍需重新构造有证据的正向场景。归类不等于已经证明其所有后续断言都过时，因此未批量删除、未放宽核心规则，也未宣称问题已修复。

[`review.json`](review.json) 保留每项原名称、原文件、首次实际失败点、观察到的错误、异常类型、分类和迁移原因；`migrated_to_current_contract` 记录已迁移的 3 项及替代用例。测试源码中的原因与此对照，避免只写一句“legacy”。

这些用例仍随 `parser_core` 全套执行；可单独运行 `python -B _development/run_tests.py legacy`。出现意外通过会失败；出现不在声明范围内的异常也会失败。调查实际断言时追加 `--runxfail --tb=short`，这时 109 项失败是显式关闭 xfail 的预期结果。
