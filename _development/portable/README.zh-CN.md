# Endfield Logs - Enhanced 便携包

适用于 Windows 10/11 x64，界面和说明使用中文。包内携带 Python、Qt 原生界面和运行依赖。
完整解压到可写目录，双击 `Start-GUI.cmd`；启动时 CMD 等待 GUI 显示后退出。

项目仓库及使用说明：https://github.com/qhp-ket/EndfieldLogs-Enhanced

程序通过 Npcap 被动抓包，在自身进程解码，再生成 trace、增量统计和浮窗。
程序不含对游戏进程的注入、Hook 或内存读写；登录解码调用用户游戏 DLL 的导出函数。

## 开始使用

1. 在「设置 → 游戏路径」选择 `Endfield.exe` 或游戏目录，游戏迁移后可重新选择。
2. 抓包需先安装 [Npcap](https://npcap.com/#download)，安装时勾选 **Install Npcap in WinPcap API-compatible Mode**，并关闭其他抓包客户端。
3. 首页点「启动抓包」后启动游戏。抓包默认关闭，可在设置启用随启动运行。
4. 悬浮窗页选择功能、显隐、样式、字号和尺寸，列表顺序支持拖拽保存。
5. 战斗日志页导入 trace，加载分析或发送到伤害浮窗；「返回实时日志」恢复实时。

**停止抓包后重新启动，需要重开游戏。**
`Start-GUI.cmd --check` 可单独检查启动条件。解压路径支持中文和空格。

| 功能 | 使用方式 |
| --- | --- |
| GUI 托盘 | 首页按钮或 `Ctrl+Shift+O` 隐藏/恢复全部 GUI |
| 浮窗显隐 | `Ctrl+O` 或悬浮窗页按钮；显隐期间后台功能继续运行 |
| 伤害浮窗 | 默认按 rDMG 显示和排序，列宽随内容适配，字体和头像比例分别调整 |
| 原生皮肤 | 内置终末地风格，支持导入 JSON 皮肤和组合模块 |
| OBS | 窗口采集选择 Windows 10（WGC），桌面隐藏期间仍可捕获 |
| 连携 CD | 悬浮窗页启用，图像识别独立运行；就绪时整块角色背景变绿，抓包补充角色身份 |
| 输入记录 | 首页独立启停，默认关闭；仅采集游戏前台输入，记录子进程按需申请管理员授权 |
| 战斗分析 | Qt 原生时间轴、累计 rDMG 等曲线、技能、BUFF、贡献和离线头像 |
| 更新 | 设置「关于」检查正式版本及日期，前往发布页手动下载 |

连携可在识别设置中预览和校准。不可读时延续可信状态，有可靠速度时继续估算，到零保持就绪。
CD 就绪表示冷却状态，技能触发条件由游戏判断。

战斗分析默认将战技独立成轨、连携与终结合轨。角色名称格的设置按钮可添加、排序轨道并选择技能；默认隐藏「其他」，自定义配置中未分配的技能进入「其他」。
曲线、头像等选项在「显示设置」中调整，底部详情按需展开。

## 输入文件与上传

输入与 trace 存在同一日期目录。独立录制为 `input_*.input.jsonl`，抓包开始或 trace 换文件时切到配套 `trace_*.input.jsonl`。
战斗分析自动发现同名文件，也可每场「绑定 input log」，再开启「显示输入」；请选择覆盖本场时间的文件。
默认长按阈值 280ms 为参考值，标记表示操作意图。
连携输入标记仅横跨角色轨道；伤害曲线、技力及失衡轨道保持独立。显示范围始终采用本场战斗起止时间。

官网 uploader 独立下载，完整解压后运行 `Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe`。
选择 `.dev-gui/logs/battles/` 日期目录中的 `trace_*.log`，保留 `.log.status.json`，即可按官网规则解析和上传。
输入文件供本地分析使用。

配置、日志和历史列表保存在 `.dev-gui/`，运行日志可在 GUI 查看。
向他人分发请使用原始 ZIP。

## 内容与许可

| 路径 | 内容 |
| --- | --- |
| `launch_gui.py`、`_internal/src/`、`_internal/packages/` | 程序源码 |
| `_internal/python/`、`_internal/python_deps/` | 隔离运行时及依赖 |
| `BUILD-MANIFEST.json` | 版本、依赖及逐文件 SHA-256 |
| `licenses/`、依赖的 `*.dist-info/` | 上游许可和声明 |

本项目代码及组合程序采用 GPL-3.0-only，保留上游 MIT 声明；各依赖采用各自许可，第三方数据保留来源记录。
交付要求见 `licenses/EndfieldLogs-LICENSING.zh-CN.md`，来源见 `licenses/EndfieldLogs-THIRD_PARTY_NOTICES.md`。
