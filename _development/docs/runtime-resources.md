# 源码开发需要的运行资源

源码附带提取后的 `runtime-data.zip`，约 5.8 MB，运行数据共约 16.9 MB。
`Setup-Dev.cmd` 或 `python -B _development/tools/prepare_resources.py` 会离线恢复并校验。
普通开发环境仅使用精简运行数据。开发版规则保留在源码中；
已有资源不匹配会报错，不直接覆盖。便携版包含已解压的同一份运行数据。

完整输入仅供维护提取规则，保存在 Git 忽略的 `_development/raw-resources/_internal/`，
程序不会从这里回退读取。显式添加 `--raw` 才准备完整输入；
`--archive PATH --offline` 可指定固定官网 ZIP。
提取规则、重建与等价验证见 [data 说明](../../_internal/data/README.md)。

实时抓包需要系统 Npcap，以及用户自己的游戏安装目录和 `GameAssembly.dll`。
本仓库不分发游戏 DLL；离线 trace 解析无需加载游戏 DLL。

## 独立官网 uploader

`Uploader/` 是完整的独立官网程序，Git 整体忽略。它不是 GUI 启动或本地日志分析的前提。
其中程序保持官网原版，不统一改名或修改其内部实现。也可显式运行
`python -B _development/tools/prepare_resources.py --with-uploader` 获取固定版本。
需要上传时，从可信的完整官网发行包取得整个 uploader 目录及其 `_internal` 依赖，按下列布局放置：

```text
Uploader/
└─ EndfieldLogsUploader/
   ├─ EndfieldLogsUploader.exe
   └─ _internal/
```

不要仅复制单个 EXE。也可在别处运行官网 uploader，无需复制到开发目录。
主程序便携包不收集 `Uploader/`，构建主程序无需准备该目录。
独立 uploader 构建直接从通过哈希校验的官网 ZIP 提取，无需先准备本地 `Uploader/`；
它按官网版本单独发行，不随主程序版本重复打包。

上传选择 `.dev-gui/logs/battles/` 日期子目录中的 `trace_*.log`，并保留配套的
`.log.status.json`。`launcher.log` 和 `session_*.ndjson` 不能代替 trace。

**本程序新采集的 trace/status 可直接由官网版 uploader 识别，无需转换或导出 upload 版。**
这不绕过官网登录、日志完整性门禁及后端校验；上传解析/排行仍以官网实现为准。

## 测试边界

普通回归使用合成数据，验证解析结果、资源完整性和打包边界，不执行真实抓包或上传。
便携 ZIP 包含所需运行资源；构建与解压验证见 [打包说明](portable-packaging.md)。
