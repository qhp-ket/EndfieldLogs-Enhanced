# 新版 GUI 源码启动

在根目录双击 `Start-GUI.cmd`，或在 PowerShell 运行：

```powershell
.\Start-GUI.cmd
```

脚本运行本地 `launch_gui.py` / `gui_main.py`，不生成 GUI EXE。普通启动通过 `--detach` 交给同一解释器旁的 `pythonw.exe`（没有时使用无控制台创建标志），CMD 随即退出；启动瞬间可能短暂闪窗。`--check` 保持同步执行及退出码，检查时不会启动 GUI 或抓包。旧工作区使用 `_internal/python_deps/gui`、`_internal/python_deps/common`；新源码环境由 `Setup-Dev.cmd` 准备。Python 优先级为 `ENDFIELD_GUI_PYTHON` 指定路径、包内 `_internal/python/python.exe`、初始化记录的项目环境、根 `.venv`、`py -3`、PATH 中的 python。虚拟环境不混用旧依赖目录。便携 ZIP 已附带隔离 Python，无需另装 Python 或 pip。详见 [开发环境说明](development-environment.md)。

首次使用：

1. 关闭正在抓包的旧客户端，再启动本脚本。
2. GUI 会自动尝试启动抓包一次。缺少 Npcap、抓包密钥或有效游戏目录时显示简短原因；没有强制向导，仍可导入和分析历史日志。可按首页提示选择同时包含 `Endfield.exe` / `GameAssembly.dll` 的游戏目录，然后手动点击「启动抓包」。
3. 在「设置 → 服务连接」设定 WebSocket 端口，修改后「下次启动抓包生效」。首页同一按钮控制启动和停止，不再提供重启按钮。抓包启动成功后再启动游戏；若游戏已经运行，按 GUI 提示重开游戏。
4. 进入战斗检查团队 DMG/DPS、角色 DMG / DMG rate / rDMG / rDMG rate、名字下方 CRIT、时长和质量标签。退出/重开战斗时检查旧数据被清空或新场状态替换。

伤害窗的“来源地址”保持 `damage`。在 GUI 的“悬浮窗”页选中伤害统计，用“伤害条与排序”的 `DMG / DPS`、`rDMG / rDPS` 切换条形依据及排序；可用“显示列”分别开关四列。每个角色的两个 rate 均以 canonical 团队总伤害为分母；零分母或未知值显示 `—`。

首页按钮状态：已停止或失败清理完成时为可点击的「启动抓包」；启动期间为禁用的「正在启动…」；成功启动后（包括等待游戏、等待登录、要求重开游戏）为可点击的「停止抓包」；清理期间为禁用的「正在停止…」。主动停止后保持停止，不会自动再次启动。**停止后再启动无法接续已经运行的游戏会话，需要重开游戏。** 没有新增「暂停实时分析」选项；隐藏 Overlay 也不会暂停抓包或分析。

首页仅保留抓包控制、连接状态和当前队伍。「悬浮窗」页最上方为新增 URL、本地模板入口，随后「一键配置」集中启用全部、停用全部及显隐按钮。显隐按钮与快捷键执行相同操作：隐藏当前显示的浮窗并记住这些项，下次恢复并清空记录；没有显示且没有记录时显示全部已启用项。每个浮窗配置第一行「启用」与「显示浮窗」并排，分别控制该项分析需求与桌面显隐；停用时「显示浮窗」不可操作，并保留原选择。桌面只在两者均开启时显示浮窗；右上角 × 只关闭桌面显示，不停分析和绘制。字体大小位于位置上方，锁定位置与鼠标穿透同排。模板专属选项仍放在各浮窗配置中，位置旁可「重置布局」。详见 [悬浮窗配置](overlay-templates.md)。

「运行日志」是独立栏目，即使没有打开也持续接收日志；支持复制（有选区时只复制选区）、清空显示及打开日志文件夹。清空显示不删除磁盘文件；显示仍只保留最近 800 个文本块。

解除位置锁定后，可将伤害窗缩小至 320×160（Qt 逻辑像素）；小窗口会等比缩小完整表格。默认大小保持 700×350。浅色／深色保留终末地风格装饰；透明背景移除 Overlay 背景与装饰，配合透明度滑块使用。

连携 CD 显示已停用：默认项和旧配置中的入口移除，抓包服务不再创建其分析器、处理队列、更新任务或 WS 消息。原 `combo_cooldowns.py` 和模板资源保留。

OBS 添加「窗口采集」，按浮窗名称选择窗口，捕获方式使用 Windows 10（Windows Graphics Capture）。用户已确认该方式可用；捕获的是 GUI 正在使用的同一个浮窗，因此历史/实时切换、布局、字体和数据均同步。GUI 必须保持运行。

关闭「显示浮窗」、使用一键显隐或点击 ×，只将窗口的桌面透明度设为零，并让鼠标穿透；同一窗口仍保持绘制，Windows 10 捕获继续收到新画面。重新显示恢复原透明度、位置和尺寸。已用原生捕获 API 验证隐藏后连续两次画面更新，并确认桌面上不可见；此结论适用于 Windows 10 捕获方式，未验证 BitBlt/GDI。关闭「启用」则会停止该项分析需求并关闭窗口，OBS 不再有该窗口可采集。

旧 OBS 镜像服务、地址、端口及相关提示已移除。设置中的 WebSocket 端口仍用于实时数据接口。直接打开 `overlay_assets/index.html?wsPort=...` 仍只订阅实时 WS，不会加载 GUI 选中的历史；需要同步 GUI 时请使用窗口采集。

BUFF 与 UID 模板已实现；UID 窗用于遮挡，BUFF 窗显示已捕获的持续状态。历史页支持 Ctrl / Shift 多选及全选，点击「加载选中记录」后后台分析各场，仅将最后选中的战斗送到伤害 Overlay；「返回实时日志」恢复最新实时状态。导入引用原文件，列表移除不删文件；完整统计按需计算，加载后的摘要与 Overlay 使用同一 canonical snapshot。

配置与运行文件保存在开发根目录的 `.dev-gui/`，独立于正式安装的共享配置：

- `.dev-gui/settings.json`：游戏路径、Overlay、WS 端口和 GUI 设置。
- `.dev-gui/logs/launcher.log`：启动错误及运行日志。
- `.dev-gui/logs/launcher-stdio.log`：无控制台启动时的直接输出、Qt/native 标准错误等补充信息。
- `.dev-gui/logs/battles/`：本次开发 GUI 的抓包日志与 trace 存放根目录。

官网 uploader 应选择日期子目录中的 **`trace_日期-时间.log`**。`session_*.ndjson` 是诊断／GUI 历史索引数据，`launcher.log` 是程序运行日志，均不能替代 trace。

新版服务会像官网启动器一样自动写入配套的 `trace_*.log.status.json`，官网 uploader 可将其识别为自动归档日志。移动原始 trace 时应同时保留 status 文件。

GUI 的运行日志接收日志处理器建立后的主进程 Python logging，不承诺覆盖启动早期、直接 print 或全部子进程/native 输出。完整排查请查看上述磁盘日志。GUI 尚未出现就启动失败时，会弹出简短原因与 `launcher.log` 路径；正常 `--detach` 返回 0 只代表子进程已创建，后续初始化失败由子进程提示并记录。手动执行 `python launch_gui.py` 仍可保留控制台进行调试。

GUI 已移除「导出 uploader 日志」按钮。新采集的 trace 连同 status 可直接被官网 GUI 的自动归档入口识别，无需另存 upload 版。底层 `upload_document` 的通用 proof 校验与这个 GUI 例外入口是两回事，status 不能代替完整性 proof。2026-10-21 修正前缺少 status 的旧 trace 可能仍提示 `missing integrity proof`；兼容导出工具 `endfield_pcap.trace_export.export_trace_log` 保留在源码，供旧日志维护使用，不会覆盖原日志或重签已有无效证明。

仅检查依赖、Npcap 和游戏目录，不启动窗口或抓包：

```powershell
.\Start-GUI.cmd --check
```

也可显式保存游戏路径或端口：

```powershell
.\Start-GUI.cmd --game-dir "D:\Games\Endfield Game"
.\Start-GUI.cmd --ws-port 29326
```

已验证 CMD 入口、Python/Qt/WebEngine 导入、Npcap DLL 可加载，以及完整主窗口和默认单个伤害 Overlay 的打开/关闭（关闭真实捕获的离线验证）。真实游戏数据仍需现场验收；当前可以开始基础伤害链路实测。
