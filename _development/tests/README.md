# 测试分类与运行

计数按 pytest 参数展开用例统计。运行入口隔离 GUI 配置、Qt 缓存与输出，普通回归使用合成输入。

## 应用测试

`live` 运行整个应用测试集。以下目录相对本文件：

| 目录 | 主要覆盖 |
| --- | --- |
| `battle/` | 原生分析、角色轨道与“其他”兜底、伤害/技力/失衡、详情、角色统计、质量字段及列宽保存 |
| `gui/` | 启动、配置迁移与恢复、字号、浮窗排序、日志、凭据与更新 |
| `history/` | 索引、缓存、选择竞态、重命名回滚、文件引用和上传证明 |
| `overlays/` | 显隐、几何/DPI、原生布局与绘制、连携状态、v2 组合皮肤、WS 重连及乱序 |
| `service/` | 简报/完整发布、WS 认证/慢消费者、抓包故障传播、reset/退出隔离、订阅及 trace |
| `resources/` | 数据、头像边界、依赖锁/闭包、打包、版本及 ignore |
| `independent/` | 输入后端/去重/前台/溢出、管道退出、JSONL、绑定与对齐、视觉状态与生命周期 |
| `integration/` | 可选外部资源的发行约束，单独执行 |

`app_test_support/` 提供共享支持：`ui/` 为 Qt/主窗夹具，`scenarios/` 构造日志和战斗状态，`runtime/` 模拟服务并加载维护工具。

## 核心测试

[parser_core 测试](../../_internal/packages/parser_core/tests/README.md)：

| 目录 | 通过数 | 主要覆盖 |
| --- | ---: | --- |
| `allocation/` | 73 | rD 分配、守恒、顺序无关、乘区/抗性反事实及数值边界 |
| `baseline/` | 159 | 武器/装备/技艺静态基线、精炼、来源去重和公式 |
| `evidence/` | 222 | 精确命中、身份/目标、条件、动态属性、BUFF 和暴击证据 |
| `live/` | 72 | 未决后缀、前缀复用、迟到回放、累计撤销、副本隔离和摘要 |
| `mechanics/` | 220 | 动态腐蚀、笔意、连携包链及技能类别 |
| `whitelist/` | 783 | 角色/武器/装备批准矩阵、元素/条件/来源约束 |
| `reporting/` | 238 | 公共入口、质量、显示名、完整性和缺证据报告 |
| `timing/` | 147 | 计时冲突、换场/跨日、rotation 及技能计划 |
| `legacy/` | 109 项预期失败 | [断言与核对方法](../../_internal/packages/parser_core/tests/legacy/README.md) |

uploader_core 共 22 项：20 项 payload/过滤/证明与边界，另有暴击历史、场景武器精炼各 1 项。

## 运行与验证范围

仓库根目录选择所需测试集：

```powershell
python -B _development/run_tests.py live
python -B _development/run_tests.py parser_core
python -B _development/run_tests.py uploader_core
python -B _development/run_tests.py app-battle
python -B _development/run_tests.py app-overlays
python -B _development/run_tests.py core-live
python -B _development/run_tests.py legacy
```

`app-目录名` / `core-目录名` 选择分类，可追加 pytest 参数如 `-k`。
`legacy --runxfail --tb=short` 用于调查实际断言，该模式关闭 xfail，预期返回非零。

CI 在 `main/python-qt` 与 `main` 的 push、PR 和手动触发时运行仓库审计、`live`、`parser_core`、`uploader_core`，依赖使用 `constraints-ci.txt` 固定版本。测试日志和 JUnit 结果保存为 Actions artifact。
原生布局、绘制、皮肤迁移、输入绑定和角色轨道的自动测试纳入 `live`；桌面捕获及便携 ZIP 由本机发行验收覆盖。

三个可选桌面用例分别依赖 Windows HWND、混合 DPI 双屏、WGC DLL/桌面会话。另有本地官网源码审计用例，仅在对应参考目录存在时运行。
真实更新查询用例设置 `ENDFIELD_LIVE_UPDATE_TEST=1` 后运行 `app-integration -k live_updates`，验证正式 Release API 与 GUI 后台提示。
外部资源检查按前提单独执行，跳过记录为未验证；实体手柄和实战画面另行实机验收。
输出位于 `_development/verification/`，按改动选择测试见 [打包验证表](../docs/portable-packaging.md)。
