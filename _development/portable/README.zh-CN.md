# EndfieldLogs 便携包

适用于 Windows 10 / 11 x64。请先完整解压 ZIP 到有写入权限的目录，再双击
`Start-GUI.cmd`。包内附带 Python 3.14、Qt / WebEngine 及程序依赖，无需另装 Python，
无需 pip，也没有将新版 GUI 编译成 EXE。

## 第一次使用

1. 实时抓包需要系统已安装 Npcap。缺少 Npcap 时仍可导入、分析本地 trace 日志。
2. 关闭旧抓包客户端，运行 `Start-GUI.cmd`，按首次向导选择游戏目录。
3. GUI 自动尝试启动抓包一次；缺少前提时在首页提示，准备好后点「启动抓包」，再启动游戏。
   主动停止后不会自动重启；停止后再启动需要重开游戏，不能接续已有会话。
4. 悬浮窗页可开关窗口、设置字体和尺寸，卡片右上角可重置尺寸、字体和位置。
5. 战斗日志页可导入本地 trace，加载后查看分析、发送到伤害浮窗，或返回实时日志。
   战斗分析顶部可在 Qt 和官网风格（本地）两种界面间切换。

在终端执行 `Start-GUI.cmd --check` 可检查依赖和 Npcap；此命令不会开始抓包。
解压路径可以包含空格和中文。不要直接在压缩包预览窗口里运行。

## 日志与上传

个人配置、缓存、日志和历史列表都在解压目录下的 `.dev-gui/`，首次运行自动生成。
本包不包含打包者的个人配置、账号、日志或历史记录。转发给其他人时，请发送原始 ZIP，
不要直接压缩自己已运行过的整个目录。

`Uploader/` 内是未修改的 ZMDLogs 官网版独立 uploader：
`Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe`。
选择 `.dev-gui/logs/battles/` 日期目录中的 `trace_*.log`，并保留配套的
`.log.status.json`。本程序新采集的 trace 可直接交给官网版 uploader，无需转换。
`session_*.ndjson` 与 `launcher.log` 不是可上传战斗 trace；上传仍需官网账号与服务器正常接收。

## 内容与许可

- `launch_gui.py` 与 `_internal/src/`、`_internal/packages/`：可阅读修改的程序源码。
- `_internal/python/`：隔离 Python 运行时，启动器优先使用它。
- `_internal/python_deps/`：运行依赖及原有许可文件；没有打包 pytest 和开发测试组件。
- `_internal/secrets/client_privkey.pem`：与官网发行包一致的抓包运行资源，不是账号凭据。
- `BUILD-MANIFEST.json`：版本、依赖清单和各文件 SHA-256。
- `licenses/` 及依赖的 `*.dist-info/`：保留上游和第三方许可、声明。

本地日志分析不会调用 ZMDLogs 网页分析接口。测试包不含 Npcap 驱动安装器，
不会自动安装系统驱动；实时游戏延迟仍以实际环境为准。
