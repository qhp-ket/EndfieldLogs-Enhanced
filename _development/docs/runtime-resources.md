# 运行资源

## 精简数据

源码附带 `runtime-data.zip`（约 5.8 MB），恢复后约 17.0 MB。
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
当前数据来自 3.0.14，该版已将上传器并入主程序；本项目的独立 uploader 仍固定为已核验的 3.0.12 原版，下载来源单独记录在资源清单 `uploader_source`，不随解析数据升级而替换。

新录制默认使用 JSONL。在战斗日志页选中一场并「导出官网兼容日志…」，将生成的单场 `.log` 交给官网 uploader；旧 `.log` 保留配套 `.log.status.json` 和完整性文件。
3.0.14 官网 parser/uploader 已通过合成日志的本地读取、载荷和原文档构建检查；该版 uploader 只更新客户端与构建器版本标识，未改变载荷结构。未进行网络上传，登录和排行仍按官网规则处理。

普通回归使用合成数据；资源完整性与便携验证见 [打包流程](portable-packaging.md)。
