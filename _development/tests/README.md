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

CI 在 `main/python-qt` 与 `main` 的 push、PR 和手动触发时执行。`tools/select_tests.py` 集中维护影响范围：PR 比较 merge-base，push 比较 before/after；新增、删除、重命名前后路径共同决定测试集合。

| 改动 | 默认验证 |
| --- | --- |
| 文档与许可 | 仓库审计、文档链接及便携说明引用 |
| GUI、历史、浮窗、输入与视觉 | 对应应用分类及已知调用方 |
| parser_core／运行数据 | parser_core、分析／历史／服务及 uploader_core；运行数据另含 resources |
| uploader_core | uploader_core、历史导出与上传证明 |
| 打包与启动工具 | resources、GUI 启动相关分类 |
| 共享模型、服务协议、配置、依赖、测试基础设施、CI、未知路径或差异不完整 | 全套 |
| 手动完整验证与发布验收 | `live`、`parser_core`、`uploader_core` |

测试分类按顺序执行并去重；选择 `live` 后合并其包含的应用分类。纯文档路径免装运行依赖，其余使用 `constraints-ci.txt`。汇总区分通过、失败、未执行和按范围跳过；日志、JUnit、源码状态、资源／依赖清单哈希及选择原因保存为 artifact。
原生布局、绘制、皮肤迁移、输入绑定和角色轨道的自动测试纳入 `live`；桌面捕获及便携 ZIP 由本机发行验收覆盖。

三个可选桌面用例分别依赖 Windows HWND、混合 DPI 双屏、WGC DLL/桌面会话。另有本地官网源码审计用例，仅在对应参考目录存在时运行。
真实更新查询用例设置 `ENDFIELD_LIVE_UPDATE_TEST=1` 后运行 `app-integration -k live_updates`，验证正式 Release API 与 GUI 后台提示。
外部资源检查按前提单独执行，跳过记录为未验证；实体手柄和实战画面另行实机验收。
输出位于 `_development/verification/`，按改动选择测试见 [打包验证表](../docs/portable-packaging.md)。

## 开发中的验证选择

修改前明确目标行为、边界和对应测试。先运行最相关分类；新失败或影响扩大时追加验证。完整回归通过后，仅在源码、依赖或资源发生相关变化，或仍有具体疑点时重复。

测试预期来自产品契约、协议、手算结果或固定参考。失败时先区分程序、夹具和环境；截图用于人工检查布局，功能测试等待可观察状态。一次性文案修复直接审阅，无需建立专用审计阻断规则。

私有状态访问应检查职责归属；拆分按状态所有权和调用接口进行。原生句柄、真实管道和 WebSocket 生命周期保留集成验证，退出测试检查有界等待、升级终止及失败诊断，避免固定到具体秒数。

历史请求顺序、晚到失效和缓存释放在 `history/test_history_controller.py` 验证；页面保留真实点击、批量顺序、文件重命名及快照显示集成。输入解释的异步状态在 `independent/test_input_evidence_controller.py`，绑定和菜单交互在 `test_battle_input_binding.py`。`battle/test_detail_presenter.py` 验证独立分析窗口显式保存设置。

独立服务需求和会话关联在 `independent/test_service_controller.py` 验证；Qt 视觉线程停止／重启在 `test_vision_publication.py`。`gui/test_shutdown.py` 覆盖可见／托盘隐藏时的异步退出、GUI 响应和停止失败诊断。

按需视觉取证使用合成 trace 和独立临时配置；输出目录需尚未存在，截图另行检查布局：

```powershell
python -B _development/tools/preview_native_gui.py --output _development/verification/preview-dark --theme dark
```

`--theme light` 生成浅色版本，`--platform windows` 使用实际桌面。此工具只读取仓库合成夹具。
