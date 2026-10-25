# 解析核心测试

按验证行为分类：

- `allocation/`：分配数学、乘区、抗性反事实与守恒。
- `baseline/`：武器、装备、技艺、精炼和静态公式来源。
- `evidence/`：身份、精确命中、条件、暴击、动态属性与 BUFF 状态证据。
- `live/`：增量缓存、失效/回放、隔离、水位、摘要与累计值修正。
- `mechanics/`：腐蚀、笔意、连携、技能类别与真实包链。
- `whitelist/`：角色/装备批准矩阵与来源约束。
- `reporting/`：公共入口、完整报告、质量与显示契约。
- `timing/`：计时、换场与 rotation。
- `legacy/`：显式标记的预期失败用例，仍参与完整回归。
- `parser_test_support/`：共享场景与 fixture 路径，不含测试用例。
- `fixtures/`：合成日志、版本绑定的规则/公式证据；不含用户战斗录制。

测试分类、计数和运行命令见 [应用测试说明](../../../../_development/tests/README.md)。在根目录执行 `python -B _development/run_tests.py parser_core`；按目录运行可用 `core-evidence`、`core-live` 等。
