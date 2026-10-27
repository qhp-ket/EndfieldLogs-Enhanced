# 应用源码导航

`endfield_pcap` 按运行职责组织。根目录只保留包入口、版本和跨功能共享的数据模型。

| 目录 | 职责 |
| --- | --- |
| `capture/` | Npcap API、抓包线程、TCP 重组、协议解码、消息注册与资源 ID 解析 |
| `crypto/` | 现有解密与游戏 DLL 桥接 |
| `service/` | 服务配置、会话状态、事件转换和后台任务 |
| `trace/` | 已解码事件转成统一 trace 文本，管理战斗上下文与来源证据 |
| `analysis/` | 实时简报与完整报告发布、战斗分析的界面投影 |
| `history/` | 历史索引、记录文件操作、trace 导入导出与离线分析 |
| `application/` | 设置所有权、历史索引/任务/缓存、输入证据、独立服务协调及异步退出 |
| `settings/` | 配置模型、编解码、迁移、原子写入与备份恢复 |
| `data/` | 数据读取、装备数值、技能名称/帧数与离线头像身份解析；小型映射在 `assets/` |
| `gui/` | 主窗口、侧栏、战斗分析与共享 Qt 控件 |
| `overlays/` | 浮窗管理、原生窗口、QPainter 模块和 JSON 皮肤 |
| `inputlog/` | 独立 Raw Input / SDL3 录制进程、JSONL、离线解释与按需历史索引 |
| `vision/` | WGC 取帧、HUD 布局、小区域像素、跨帧状态和 GUI 侧生命周期 |
| `runtime/` | 运行根目录、Python/DLL 路径、日志、游戏安装位置与正式版更新查询 |
| `proto_generated/` | 自动生成的 protobuf，保留生成器的模块名和依赖结构 |

## GUI 从哪里改

`gui/main.py` 负责窗口和页面组装、导航、消息分发与退出。
`gui/pages/` 的五个子目录与侧栏对应：

- `home/`：抓包按钮、状态、启动条件与错误提示。
- `overlays/`：浮窗列表、配置操作、显隐和快捷键。
- `history/`：记录列表、批量载入、删除、重命名和导入。
- `logs/`：日志显示及 Python logging 转发。
- `settings/`：设置表单、保存动作和游戏路径选择。

页面由 `view.py` 构造界面。历史页通过 `HistoryPresenter` 调用 `HistoryController`，
索引、导入和分析使用独立结果队列，由所属线程提交状态；其他页面的 `actions.py` 负责现有设置与窗口操作。
快捷键与主题各有独立模块。
`gui/lifecycle.py` 管理托盘显隐和后台刷新频率，通过历史控制器释放缓存；GUI 显隐快捷键与浮窗快捷键分别注册。
更新检查的后台任务与提示在 `gui/updates.py`，版本比较与 GitHub 请求在 `runtime/releases.py`。
共享头像由 `data/avatars.py` 按 ID 解析，Qt 缓存在 `gui/shared/avatars.py`，图片在 `_internal/data/ui/characters/`。

`gui/battle/` 是历史战斗分析：`timeline/` 管理原生时间轴，
`plots/` 管理伤害、技力和失衡曲线。
`BattleDetailPresenter` 显式传入显示设置与记录，将窗口信号交给 `SettingsStore` 和 `InputEvidenceController`；Qt 父窗口负责归属与定位。
详细入口见 [战斗分析组件位置](../../_development/docs/battle-analysis-components.md)。

## 服务与 trace

`service/config.py` 是配置。`service/runtime/server.py` 管理生命周期，
同目录的 `flow.py`、`websocket.py`、`analysis.py`、`debug.py` 负责对应后台任务。
`service/session/pipeline.py` 组装单次游戏会话：拆帧、消息分派和事件转换分开，
角色/装备/背包/技能状态更新在 `state/`。
`session/operations/` 按技能、BUFF、实体及资源构造事件，`BattleOperation` 保存单次操作的身份和发送入口；`battle.py` 保持操作遍历及计时观测顺序。

`trace/bridge.py` 是转换入口，其他模块按战斗上下文、角色、技能、伤害、BUFF 分工。
`TraceBridge._append_line()` 仍是写盘与分析 sink 共用的唯一行出口。
`observations.py` 负责时钟旁路、关键词及实体值观测，`blackboard.py` 分阶段处理动态身份、属性刷新和黑板计算；`resources.py` 管理技力、失衡及战斗状态，`damage_evidence.py` 保持逐击包证据的写出顺序。
canonical 解析与分配位于 `_internal/packages/parser_core/`。

## Overlay 资源

内置皮肤声明在 `overlays/assets/<类型>/template.json`，绘制模块在 `overlays/native/`。
GUI 支持的内置类型为 `damage`、`uid_mask`、`combo_skill`。
配置 ID `combo_skill` 对应 `combo/` 目录。
`overlays/client.py` 为独立浮窗提供本地 WebSocket 连接与重连。

`overlays/templates.py` 解析模板，`config.py` 提供默认几何与内置入口，
`window.py` 负责单窗绘制/拖动/缩放，`manager.py` 管理多窗及历史/实时状态切换。
新增模板使用独立目录、稳定配置 ID 和相对资源路径。

`application/independent.py` 协调输入、视觉服务及抓包订阅；`gui/independent/presenter.py` 连接控件、格式化状态并打开绑定配置和预览校准界面。
`application/shutdown.py` 汇总抓包、输入及视觉资源退出进度；窗口通过 Qt 定时器推进关闭，输入进程等待在后台线程执行，视觉捕获通过所属线程释放原生资源。
`gui/battle/input_history.py` 提供绑定、对齐和解释设置编辑控件，`application/input_evidence.py` 管理异步解释及失效结果，原生绘制在 `timeline/inputs.py`。
`inputlog/backends/windows.py` 隔离 Windows 消息线程，`windows_state.py` 提供带精度标记的状态采样兜底；`inputlog/bindings.py` 保存每场战斗的输入文件绑定。
`inputlog/elevation.py` 仅为输入记录器申请管理员权限，通过认证的本机命名管道转发控制和状态，不提升主 GUI 权限。
输入与视觉状态使用独立展示数据。

## 维护约定

按状态所有权和调用边界拆分职责，紧密相关的短代码可保留在同一文件；生成文件按生成工具约定维护。

内部使用完整包导入；页面资源相对所属模块定位，运行数据通过 `runtime.paths` 定位。
开发与便携构建使用同一目录树，构建器递归收集源码和资源。
移动模块时同步检查测试替身、函数内延迟导入、后台进程目标和文档链接。
