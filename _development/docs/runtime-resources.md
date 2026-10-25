# 运行资源

## 精简数据

源码附带 `runtime-data.zip`（约 5.8 MB），恢复后约 16.9 MB。
`Setup-Dev.cmd` 或 `prepare_resources.py` 离线恢复并校验，开发规则取当前源码；已有资源不匹配时人工核对。
便携版直接携带恢复后的数据。

完整输入用于维护提取规则，位于本地 `_development/raw-resources/_internal/`。
资源工具加 `--raw` 准备完整输入，`--archive PATH --offline` 指定固定官网 ZIP。
提取与升级见 [数据维护](../../_internal/data/README.md)。

实时抓包另需系统 Npcap 和用户游戏目录中的 `GameAssembly.dll`。

## 官网 uploader

上传器是独立可选组件，保持官网原版。资源工具支持：

```powershell
python -B _development/tools/prepare_resources.py --with-uploader
```

也可从校验过的官网包复制完整目录及依赖：

```text
Uploader/EndfieldLogsUploader/
  EndfieldLogsUploader.exe
  _internal/
```

可在任意目录独立运行。Uploader 使用上游版本号单独打包，构建时从官方 ZIP 原样提取。

上传选择 `.dev-gui/logs/battles/YYYYMMDD/trace_*.log`，保留 `.log.status.json` 和完整性文件。
本程序采集的 trace/status 直接兼容官网自动归档入口，登录、解析和排行按官网规则处理。

普通回归使用合成数据；资源完整性与便携验证见 [打包流程](portable-packaging.md)。
