# ZMDLogs 官网版独立 Uploader

适用于 Windows 10 / 11 x64。完整解压后运行：

`Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe`

本包自带官网程序的运行依赖，无需安装 Python，也无需先安装 EndfieldLogs 主程序。
不要只复制一个 EXE。程序、依赖和数据均从校验过的官网包原样提取，保持原始字节。

主程序与 uploader 分别发行，版本独立。只使用本地分析或 Overlay 时无需下载本包。
需要上传时，可在任意目录运行此程序，选择主程序日志目录中的 `trace_*.log`，
并保留配套的 `.log.status.json`。这些日志兼容官网 uploader，无需格式转换。

如需放在主程序目录内，将本包中的整个 `Uploader/` 文件夹复制到主程序根目录即可。
个人配置和账号状态不在本包内；上传需要官网账号与服务可用。

官网：https://zmdlogs.com/

`BUILD-MANIFEST.json` 包含本包版本、文件大小及 SHA-256；`licenses/` 保留许可说明。
