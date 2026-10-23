# EndfieldLogs

《明日方舟：终末地》的第三方战斗日志客户端，基于 ZMDLogs / Endfield Logs 源码开发。
提供 Python + PySide6（Qt）GUI、实时伤害浮窗、本地 trace 导入和战斗分析。
此项目是独立开发版，项目中的“官网版”指 ZMDLogs 的发行版。

## 使用便携包

完整解压发行 ZIP，双击 `Start-GUI.cmd`。便携包包含 Python、Qt / WebEngine 和运行依赖，
无需另装 Python 或 Qt。个人配置、日志和历史列表写入 `.dev-gui/`。
实时抓包另需安装 Npcap，并按首页提示选择自己的游戏安装目录；程序不附带游戏 DLL。
启动时 CMD 短暂出现后退出，运行期间只显示 GUI 和 Overlay；`--check` 保持控制台检查。
GUI 打开后自动尝试启动抓包一次，首页同一按钮启动/停止；主动停止后不会自行重启。
停止后再启动无法接续正在运行的游戏会话，需要重开游戏。运行输出在左侧「运行日志」查看，
同时保留磁盘日志；缺少 Npcap、密钥或游戏目录不影响历史分析。详见 [GUI 启动说明](_development/docs/gui-launch.md)。

**新采集的 `trace_*.log` 连同 `.log.status.json` 兼容 ZMDLogs 官网版 uploader，无需导出转换版。**
便携包 `Uploader/` 内放的是未修改的官网版独立程序，不是本项目自制 uploader。
位置、日志选择及上传前提见 [运行资源说明](_development/docs/runtime-resources.md)。

## 从源码开发

当前验证环境是 Windows x64、CPython 3.14.2、PySide6 及 Qt WebEngine。
源码仓库只保留开发必要内容：运行时、依赖、上游原始数据、密钥、官网 uploader、
真实战斗、个人配置、实施记录和发行 ZIP 均不提交。

1. 执行 `Setup-Dev.cmd`：已有依赖能导入就复用，缺什么才安装，不锁版本或主动升级；
   缺少的上游运行数据从固定官网发行 ZIP 恢复并校验，开发版规则不会被覆盖。
   没有 Python 时会准备项目内环境；详见 [开发环境说明](_development/docs/development-environment.md)。
2. 按 [运行资源说明](_development/docs/runtime-resources.md) 从可信的 ZMDLogs 完整发行包
   取得 `client_privkey.pem`，放入 `_internal/secrets/`。不要生成随机密钥替代抓包密钥。
3. 本地分析使用恢复后的运行数据，来源、用途、校验与维护见
   [data 说明](_internal/data/README.md) 和 [jsondata 说明](_internal/jsondata/README.md)。
4. 双击 `Start-GUI.cmd`，或执行 `Start-GUI.cmd --check` 检查启动前提。

缺少抓包密钥时会提示，仍可打开 GUI 和分析本地日志。
普通解析与界面测试不需要这份真实密钥；依赖官网密钥的测试单独运行。

## 测试

使用已选择的环境解释器；新建 venv 时，下方 `python` 对应 `.venv/Scripts/python.exe`。

```powershell
python -B _development/run_tests.py live
python -B _development/run_tests.py parser_core
python -B _development/run_tests.py uploader_core
```

默认应用测试跳过 `requires_capture_key` 集成测试。准备好官网抓包密钥后，单独执行：

```powershell
python -B _development/run_tests.py capture-key
```

也可通过 `--capture-key-path` 指定密钥文件。显式选择该测试后，文件缺失或不匹配会报错，
不会以跳过代替成功。测试只校验发行资源，不抓包、不登录、不上传。

普通回归的 6 份 `.log` 均为合成样本，按精确白名单保留；真实战斗原件不提交。
样本生成方式和证据边界见 [fixture 说明](_internal/packages/parser_core/tests/fixtures/README.md)。

## 目录与贡献

- `_internal/src/`：应用源码、Qt GUI、Overlay 和本地 Web 分析资产。
- `_internal/packages/`：`parser_core`、`uploader_core` 及其测试。
- `_internal/data/`、`_internal/jsondata/`：运行数据；Git 只保留清单、开发版覆盖规则与说明。
- `_development/`：当前测试、工具、使用文档；历史实施记录、实验和验证输出留在本地。
- `.dev-gui/`、`_releases/`、`Uploader/`：本地状态、便携发行、可选官网 uploader，均忽略。

更多功能文档见 [_development/README.md](_development/README.md)。
提交时保留源码和测试，排除个人日志、配置、密钥及安装后的依赖。
`.gitattributes` 定义源码 LF、Windows 启动脚本 CRLF；协议样本和校验敏感资源保留原始字节。

## 版本与打包

版本唯一来源是 `_internal/src/endfield_pcap/_version.py`，GUI 和构建器共用。
开发版本使用 `0.1.0-dev.1`，正式版使用 `0.1.0` 等 SemVer，不在版本里加日期或前导 `v`。

```powershell
python -B _development/tools/release.py version                 # 查看版本与包名
python -B _development/tools/release.py version 0.1.0-dev.2     # 下次发布前修改
python -B _development/tools/release.py build                   # 回归、构建、ZIP、解压启动校验
```

输出到 `_releases/EndfieldLogs-<版本>-windows-x64.zip`，附 SHA-256 和逐文件构建清单。
同版本不覆盖；不自动上传发行附件或修改远程仓库。完整流程见 [打包说明](_development/docs/portable-packaging.md)。

## 许可与来源

项目代码沿用上游 **MIT**，见 [LICENSE](LICENSE)。保留上游版权和许可声明，
项目来源及外部资源边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
MIT 允许商业使用；本项目没有附加禁止商用条款。转载和分发时请保留项目来源与修改说明；
其中强制要求以 MIT 原文为准，不另设产品界面署名条件。
游戏数据、图片、第三方软件和外部抓包密钥不因与程序一起存放而自动适用本项目 MIT。
