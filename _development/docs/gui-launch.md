# GUI 启动与排查

根目录双击 `Start-GUI.cmd`。普通启动交给无控制台 Python，CMD 随即退出，可能短暂闪窗。
便携包自带运行环境；源码环境先执行 `Setup-Dev.cmd`，见 [环境准备](development-environment.md)。

```powershell
.\Start-GUI.cmd --check
.\Start-GUI.cmd --game-dir "D:\Games\Endfield Game"
.\Start-GUI.cmd --ws-port 29326
```

`--check` 同步检查依赖和启动条件，不打开窗口或抓包。普通启动返回成功仅表示 GUI 子进程已创建；
后续初始化错误由子进程弹窗并记录。调试可直接运行 `python launch_gui.py` 保留控制台。
解释器优先级：`ENDFIELD_GUI_PYTHON` → 包内 Python → 初始化记录的项目环境 → 根 `.venv` → `py -3` → PATH。
虚拟环境不混用旧 `_internal/python_deps/`。

## 抓包与设置

GUI 打开后自动尝试启动抓包一次；主动停止后保持停止。
先关闭其他抓包客户端，准备 [Npcap](https://npcap.com/#download)、抓包密钥和本机游戏目录。
缺少这些条件会显示简短原因，仍可导入和分析历史日志。

| 后台状态 | 首页按钮 |
| --- | --- |
| 已停止／失败且清理完成 | 启动抓包 |
| 正在启动 | 正在启动…（禁用） |
| 已启动，包括等待游戏或登录 | 停止抓包 |
| 正在停止 | 正在停止…（禁用） |

「设置 → 游戏路径」可重新选择 `Endfield.exe` 或目录，目录必须同时有 `GameAssembly.dll`。
游戏路径与 WebSocket 端口修改均在下次启动抓包生效。
**抓包停止后再启动不能接续已运行的游戏会话，需要重开游戏。**
隐藏浮窗不暂停抓包或分析，没有“暂停实时分析”选项。

## 浮窗、OBS 与历史

「悬浮窗」页提供新增 URL／本地模板、一键配置、每项「启用」和「显示浮窗」。
启用控制分析需求；显示控制桌面显隐。显隐按钮隐藏当前显示项并记录，下次恢复；没有记录时显示全部已启用项。
位置旁可重置默认尺寸、位置和字体。详细控制及模板接口见 [悬浮窗配置](overlay-templates.md)。

OBS 使用「窗口采集」，捕获方式选 Windows 10（Windows Graphics Capture），按浮窗名称选择。
捕获与桌面使用同一个窗口，历史／实时数据同步；关闭「显示浮窗」或点击 × 后仍绘制并可捕获。
停用该项或退出 GUI 会关闭窗口。BitBlt/GDI 隐藏捕获未经验证。
没有独立 OBS 端口或镜像服务；普通 WS 接口始终是实时数据，不同步 GUI 选择的历史。

「战斗日志」支持 Ctrl／Shift 多选和批量加载，浮窗只显示最后选择的战斗；“返回实时日志”恢复实时。
导入引用原文件，列表移除不删除文件。详见 [日志与贡献口径](trace-import-and-rdps.md)
及 [战斗分析](local-battle-analysis.md)。连携 CD 功能已停用。

## 日志与错误

「运行日志」持续收集 Python logging，保留最近 800 个文本块，可复制、清空显示和打开目录。
清空不删除磁盘文件；启动早期、直接 print、Qt/native 和子进程输出可能只在磁盘记录。

| 路径（相对根目录） | 内容 |
| --- | --- |
| `.dev-gui/settings.json` | GUI、游戏路径、端口和浮窗设置 |
| `.dev-gui/logs/launcher.log` | 启动错误及运行日志 |
| `.dev-gui/logs/launcher-stdio.log` | 无控制台启动时的直接输出及 native 错误 |
| `.dev-gui/logs/battles/` | 按日期归档的抓包 trace 与诊断数据 |

上传选择 `trace_*.log` 并保留 `.log.status.json`；`session_*.ndjson`、`launcher.log` 不能代替 trace。
新日志直接兼容官网 uploader，不必导出转换。旧日志或损坏证明仍可能被拒绝；status 不是完整性 proof。
上传器是独立官网组件，安装与边界见 [运行资源说明](runtime-resources.md)。
