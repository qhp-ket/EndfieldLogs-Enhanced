# 测试分类与精简记录

2026-10-25 已核对测试的输入、调用入口、断言和实际失败点。数字为 pytest 参数展开后的用例数，不是函数数。运行入口会隔离 GUI 配置、Qt 缓存和输出，不启动真实抓包或上传。

## 应用测试

目录均相对于本目录。`live` 是保留的兼容名称，实际运行整个应用测试集，不代表连接游戏实测。

| 目录 | 通过 | 验证的行为 |
| --- | ---: | --- |
| `battle/` | 69 | 战斗分析的两种界面、技能起止与命中标记、轨道与缩放、失衡/抗性证据、共享技力、BUFF 合并与层数、详情折叠、离线头像及共享开关、文字/头像列宽适配 |
| `gui/` | 61 | 抓包与输入默认不随启动开启、独立启动选项、默认浮窗顺序及排序持久化、字号与头像比例滑条、游戏路径选择、网页访问凭据迁移、Npcap 缺失提示、控制台、批量加载、正式版本检测及后台检查/忽略提示 |
| `history/` | 30 | 按需索引与加载、缓存失效、选择竞态、重命名与回滚、列表删除不删文件、导入导出及官方上传证明 |
| `overlays/` | 78 | 模板、启用与显隐、几何/字体/跨屏、关闭按钮、Qt 与 JS 渲染、头像缩放与节点复用、伤害列宽/窗口适配、视觉连携 schema 2、样式切换自动尺寸、进度条横向独立拉伸/高度缩放、列表拖拽排序与保存、主页独立服务导航、停用 BUFF 入口、网页凭据传递与远程模板隔离、状态重放与清空；另有 3 项原生桌面测试默认跳过 |
| `service/` | 101 | 摘要/完整发布、WS 新旧 API 握手与重连、浏览器访问认证与拒绝未授权 Origin、未知请求结构拒绝、慢消费者、进程退出/reset 隔离、订阅开关、trace 行写入；继续保证抓包服务不生成旧连携计时快照 |
| `resources/` | 67 | 合成样本来源、运行数据投影、新角色与缺失资源、头像清单/哈希/缓存/本地访问边界、环境隔离、Multimedia/SDL3 依赖闭包、打包边界、版本与发行流程、ignore 与密钥白名单 |
| `independent/` | 87 | 输入解释、缺失区间、手柄事件布局、跨午夜 LOADOUT、视觉像素/状态保持与估算续行、无变化快照去重、独立服务启停、共享历史输入轨道、原生进程路径查询、首页按钮/子进程与 JSONL 启停、Raw Input 传输与兼容采集去重/前台限制/溢出、来源切换中断及录制重启隔离、数字编辑器可用性；真实硬件另行验证 |
| `integration/` | 单独执行 | 外部抓包密钥的发行白名单检查；常规回归跳过，本次单独执行 1 项通过 |

`app_test_support/` 存放共享夹具与场景构造器：`ui/` 为 Qt 等待/DOM/主窗夹具，`scenarios/` 为日志与战斗状态构造，`runtime/` 为模拟服务和维护工具加载。测试文件不再相互导入。两个 `.cjs` 是实际渲染脚本的 Node harness，随对应 Python 用例执行，不是另一个重复测试集。

## 解析核心与上传核心

解析核心位于 [`../../_internal/packages/parser_core/tests/`](../../_internal/packages/parser_core/tests/README.md)。

| 核心目录 | 通过 | 验证的行为 |
| --- | ---: | --- |
| `allocation/` | 73 | rD 分配、守恒、顺序无关、乘区与抗性反事实、拒绝不合法数值 |
| `baseline/` | 159 | 武器/装备/技艺静态基线、精炼、来源去重、公式版本与对应集成路径 |
| `evidence/` | 222 | 精确 action/unit、目标实例、条件、动态属性、BUFF 生命周期/快照与暴击证据；不以名称或默认值补证据 |
| `live/` | 72 | 连续未决后缀、稳定前缀复用、迟到修正与异常回放、增量累计撤销、拷贝隔离、时钟水位与轻量摘要 |
| `mechanics/` | 220 | 动态腐蚀、笔意记录/释放/爆炸、连携包链及正向技能类别证据 |
| `whitelist/` | 783 | 各角色/武器/装备实际字段与批准关系、元素/条件/来源限制、安塔尔动态来源；矩阵的不同条目不能相互替代 |
| `reporting/` | 238 | 原始/逐击/Overlay/上传入口、质量契约、显示名、完整性、报告及当前缺证据场景 |
| `timing/` | 147 | 官方时钟、计时冲突、换场与跨日、rotation 时钟及技能计划状态 |
| `legacy/` | 109 项预期失败 | 保留的旧契约对照；具体失败、类别和待迁移原因见 [审查记录](../../_internal/packages/parser_core/tests/legacy/README.md) |

上传核心保留独立的 3 个模块、22 项用例：20 项 payload/过滤/边界与证明、1 项暴击历史、1 项场景武器精炼。没有为目录数量强行拆分。

## 精简决定

没有发现 AST 测试体完全相同的复制品；有两项断言被更完整的测试严格包含，因此删除：

| 删除的原用例 | 保留的覆盖 |
| --- | --- |
| `test_unified_rdps_totals_match_between_viewer_and_uploader_logs` | `reporting/test_snapshot_quality.py::test_four_entry_fixture_numbers_and_quality_are_identical` 同样检查逐击/上传两入口的 640/120 归属，并额外检查原始、Overlay、实时入口、计时与质量 |
| `test_overlay_snapshot_uses_viewer_rdps_totals` | 上述四入口测试同样检查 Overlay 总归属；现在还明确断言每个参与者的 `total_rd` |

`test_live_overlay_parser_uses_unified_rdps_totals` 保留：它覆盖默认实时计时路径，不能用显式关闭时钟的四入口测试替代。核心数值、服务传输和实际 Qt/JS 渲染即使使用相同样本，也分别验证不同的故障边界，继续保留。

原 112 项统一按名称标记的预期失败已逐项实际执行；3 项迁移成正常回归：不从 DPD 猜元素、不把未绑定的 BUFF 子伤害并入已知连携 family、不凭伤害技能名称合并大招施放。原输入保留，增加伤害守恒检查；允许已有明确 family 映射。另 109 项保留显式 `strict=True` 标记、指定异常类型、具体失败点与审查记录。未改变解析算法来迎合旧预期。

共享定义抽到 16 个非测试支持模块，清理 457 个多余导入绑定。文件移动和共享工具抽取本身不算删除覆盖，也不宣称大幅减少运行时间。

## 运行

在仓库根目录运行：

```powershell
python -B _development/run_tests.py live
python -B _development/run_tests.py parser_core
python -B _development/run_tests.py uploader_core
python -B _development/run_tests.py app-battle
python -B _development/run_tests.py app-overlays
python -B _development/run_tests.py core-live
python -B _development/run_tests.py legacy
python -B _development/run_tests.py capture-key
```

`app-目录名`、`core-目录名` 直接选择上述目录。可追加 pytest 的 `-k` 等参数。`controls` 兼容旧入口。`legacy --runxfail --tb=short` 用于查看实际失败，预期返回非零，不能把它当作正常验收命令。

## 结构整理时的回归记录

| 测试集 | 整理前 | 整理后 |
| --- | --- | --- |
| 应用 | 297 通过、4 跳过 | 297 通过、4 跳过 |
| 解析核心 | 1913 通过、112 预期失败 | 1914 通过、109 预期失败 |
| 上传核心 | 22 通过 | 22 通过 |
| 外部密钥 | 常规回归跳过 | 单独执行 1 通过 |

常规总量由 2348 变为 2346：删除 2 项重复用例，3 项旧预期迁移不改变用例数。当前无非预期失败、无意外通过。

默认跳过的 3 项桌面验证分别需要原生 Windows HWND、不同 DPI 的双屏、WGC 测试 DLL 与桌面会话，本次另在 Windows 原生平台补跑 HWND 枚举，混合 DPI 双屏和指定 WGC DLL 组合未执行。另用自有动态窗口验证了实际 Qt WGC → 连携 DOM 链路，不能替代游戏画面或混合 DPI 验收。常规第 4 项跳过是密钥检查，已单独补跑。全部输出保存在被忽略的 `_development/verification/*-tests.txt` 和 `*-junit.xml`。
