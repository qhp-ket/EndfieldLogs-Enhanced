# 公开回归样本

本目录六份 `.log` 均为合成解析输入。模板/action ID 用于选择真实解析分支，actor、会话、属性、HP 和时间戳使用构造值。
样本验证解析契约，实战机制与上传资格需另行验证。

| 文件 | 构造与断言 |
| --- | --- |
| `rdps_snapshot_contract.log` | 上游合成记账例：伤害 760，攻击者/辅助归属 640/120 |
| `ink_recording_contract.log` | 命中 120、10% 记录、释放 12 及独立日志权重 |
| `synthetic_combo_skill.log` | 攻击/战技分类、三层 Buff 来源链、逐击归属 |
| `synthetic_combo_ultimate.log` | 终结技/燃烧分类、三层 Buff 来源链、逐击归属 |
| `synthetic_corrosion_packet.log` | 刷新身份、抗性观测、自身无视及冲突更新 |
| `synthetic_fire_corrosion.log` | 严格刷新身份、增长、继承及低层数创建 |

四份 `synthetic_*` 日志及清单由常量生成：

```powershell
python -B _development/tools/generate_test_fixtures.py
```

其他 JSON 输入为合成批准矩阵与官方条目文案参考表；身份、元数据和武器审计场景由对应测试模块的常量构造。
`.gitignore` 只放行上述六份日志。新增样本需说明构造方法、预期不变量及证据范围。
