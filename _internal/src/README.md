# 应用源码导航

`endfield_pcap` 按运行职责组织。根目录只保留包入口、版本和跨功能共享的数据模型。

| 目录 | 职责 |
| --- | --- |
| `capture/` | Npcap API、抓包线程、TCP 重组、协议解码、消息注册与资源 ID 解析 |
| `crypto/` | 现有解密与游戏 DLL 桥接 |
| `service/` | 服务配置、会话状态、事件转换和后台任务 |
| `trace/` | 已解码事件转成统一 trace 文本，管理战斗上下文与来源证据 |
| `analysis/` | 实时发布、BUFF 展示，以及完整报告的界面投影 |
| `history/` | 历史索引、记录文件操作、trace 导入导出与离线分析 |
| `data/` | 数据读取、装备数值、技能名称/帧数与离线头像身份解析；小型映射在 `assets/` |
| `gui/` | 主窗口、侧栏、战斗分析与共享 Qt 控件 |
| `overlays/` | 浮窗管理、原生窗口、模板配置和各套网页资源 |
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

页面通常由 `view.py` 构造界面、`actions.py` 实现操作并绑定控件。
`*Actions` 是主窗口使用的 mixin，共用主窗口配置和服务状态，没有独立生命周期；
它们不反向导入 `gui/main.py`，不自行创建抓包线程。
快捷键与主题各有独立模块。
`gui/lifecycle.py` 管理托盘显隐、后台刷新频率和可释放的历史缓存；GUI 显隐快捷键与浮窗快捷键分别注册。
更新检查的后台任务与提示在 `gui/updates.py`，版本比较与 GitHub 请求在 `runtime/releases.py`。
共享头像由 `data/avatars.py` 按 ID 解析，Qt 缓存在 `gui/shared/avatars.py`，图片在 `_internal/data/ui/characters/`。

`gui/battle/` 是历史战斗分析：`timeline/` 管理原生时间轴，
`plots/` 管理技力/失衡曲线，`assets/` 是本地 Web 页面。
详细入口见 [战斗分析组件位置](../../_development/docs/battle-analysis-components.md)。

## 服务与 trace

`service/config.py` 是配置。`service/runtime/server.py` 管理生命周期，
同目录的 `flow.py`、`websocket.py`、`analysis.py`、`debug.py` 负责对应后台任务。
`service/session/pipeline.py` 组装单次游戏会话：拆帧、消息分派和事件转换分开，
角色/装备/背包/技能状态更新在 `state/`。

`trace/bridge.py` 是转换入口，其他模块按战斗上下文、角色、技能、伤害、BUFF 分工。
`TraceBridge._append_line()` 仍是写盘与分析 sink 共用的唯一行出口。
目录拆分不改变协议、trace 格式、伤害公式或归因口径。
canonical 解析与分配仍在 `_internal/packages/parser_core/`。

## Overlay 资源

每套内置模板在 `overlays/assets/<类型>/` 下拥有自己的 `template.json` 和 `index.html`，
需要时附带 `app.js`、`style.css`。启用类型为 `damage`、`uid_mask`、`combo_skill`；`buff`、`input` 的入口停用，底层资产暂保留。
已有配置 ID `combo_skill` 继续映射到 `combo/`，不改变保存的配置。
通用宿主桥和展示辅助脚本在 `shared/`。

`overlays/templates.py` 解析模板，`config.py` 提供默认几何与内置入口，
`window.py` 负责单窗绘制/拖动/缩放，`manager.py` 管理多窗及历史/实时状态切换。
新增模板使用自己的目录和稳定配置 ID，不写死工作区路径。

`gui/services.py` 组装输入与视觉服务，`gui/independent/` 是绑定配置、预览校准界面。
`gui/battle/input_history.py` 为两种分析风格共享输入证据；原生绘制在 `timeline/inputs.py`，网页绘制在 `assets/inputs.js`。
`inputlog/backends/windows.py` 隔离 Windows 消息线程，`windows_state.py` 提供带精度标记的状态采样兜底；`inputlog/bindings.py` 保存每场战斗的输入文件绑定。
`inputlog/elevation.py` 仅为输入记录器申请管理员权限，通过认证的本机命名管道转发控制和状态，不提升主 GUI 权限。
这些展示证据不写入 canonical snapshot 或 trace，旧抓包连携计时器不恢复。

## 维护约定

一个目录开始混入多类职责、文件数量接近七个时，考虑分组；
单个 Python 文件超过约 500 行时，检查是否有可独立维护的职责。
这些是审查提示，不要求把紧密相关的短代码也拆成目录；生成文件按生成工具约定维护。

内部使用完整包导入；页面资源相对所属模块定位，运行数据通过 `runtime.paths` 定位。
开发与便携构建使用同一目录树，构建器递归收集源码和资源。
移动模块时同步检查测试替身、函数内延迟导入、后台进程目标和文档链接。
