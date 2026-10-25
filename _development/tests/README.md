# 测试分类与运行

下表数字为 pytest 参数展开后的用例数，不是函数数。运行入口隔离 GUI 配置、Qt 缓存和输出，不启动真实抓包或上传。

## 应用测试

目录均相对于本目录。`live` 是保留的兼容名称，实际运行整个应用测试集，不代表连接游戏实测。

| 目录 | 通过 | 验证的行为 |
| --- | ---: | --- |
| `battle/` | 69 | 战斗分析的两种界面、技能起止与命中标记、轨道与缩放、失衡/抗性证据、共享技力、BUFF 合并与层数、详情折叠、离线头像及共享开关、文字/头像列宽适配 |
| `gui/` | 61 | 抓包与输入默认不随启动开启、独立启动选项、默认浮窗顺序及排序持久化、字号与头像比例滑条、游戏路径选择、网页访问凭据配置、Npcap 缺失提示、控制台、批量加载、正式版本检测及后台检查/忽略提示 |
| `history/` | 30 | 按需索引与加载、缓存失效、选择竞态、重命名与回滚、列表删除不删文件、导入导出及官方上传证明 |
| `overlays/` | 78 | 模板、启用与显隐、几何/字体/跨屏、关闭按钮、Qt 与 JS 渲染、头像缩放与节点复用、伤害列宽/窗口适配、视觉连携 schema 2、样式切换自动尺寸、进度条横向独立拉伸/高度缩放、列表拖拽排序与保存、主页独立服务导航、可用浮窗类型与订阅边界、网页凭据传递与远程模板隔离、状态重放与清空；另有 3 项原生桌面测试默认跳过 |
| `service/` | 101 | 摘要/完整发布、WS asyncio/legacy API 握手与重连、浏览器访问认证与拒绝未授权 Origin、未知请求结构拒绝、慢消费者、进程退出/reset 隔离、订阅开关、trace 行写入；抓包服务与视觉连携数据源隔离 |
| `resources/` | 67 | 合成样本来源、运行数据投影、新角色与缺失资源、头像清单/哈希/缓存/本地访问边界、环境隔离、Multimedia/SDL3 依赖闭包、打包边界、版本与发行流程、ignore 与运行资源白名单 |
| `independent/` | 87 | 输入解释、缺失区间、手柄事件布局、跨午夜 LOADOUT、视觉像素/状态保持与估算续行、无变化快照去重、独立服务启停、共享历史输入轨道、原生进程路径查询、首页按钮/子进程与 JSONL 启停、Raw Input 传输与兼容采集去重/前台限制/溢出、来源切换中断及录制重启隔离、数字编辑器可用性；真实硬件另行验证 |
| `integration/` | 单独执行 | 可选外部资源的发行约束检查；默认跳过，单独验证 |

`app_test_support/` 存放共享夹具与场景构造器：`ui/` 为 Qt 等待/DOM/主窗夹具，`scenarios/` 为日志与战斗状态构造，`runtime/` 为模拟服务和维护工具加载。测试文件通过支持模块共享夹具和构造器。两个 `.cjs` 是实际渲染脚本的 Node harness，随对应 Python 用例执行，不是另一个重复测试集。

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
| `legacy/` | 109 项预期失败 | 显式声明的预期失败；具体断言、类别和核对方法见 [预期失败说明](../../_internal/packages/parser_core/tests/legacy/README.md) |

上传核心保留独立的 3 个模块、22 项用例：20 项 payload/过滤/边界与证明、1 项暴击历史、1 项场景武器精炼。没有为目录数量强行拆分。

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
```

`app-目录名`、`core-目录名` 直接选择上述目录。可追加 pytest 的 `-k` 等参数。`controls` 是单独的测试集别名。`legacy --runxfail --tb=short` 用于查看实际失败，预期返回非零，不能把它当作正常验收命令。

## 可选验证边界

三项桌面验证分别依赖原生 Windows HWND、不同 DPI 的双屏、WGC 测试 DLL 与桌面会话，默认跳过。
需要外部资源的集成检查单独运行；跳过表示前提未满足，不代表验证通过。
自有动态窗口可验证 Qt WGC → 连携 DOM 链路，游戏画面、实体手柄及无线/独占场景仍需实机验证。
输出保存在被忽略的 `_development/verification/`。
