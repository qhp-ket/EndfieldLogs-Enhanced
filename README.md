# EndfieldLogs

《明日方舟：终末地》的第三方战斗日志客户端，基于 ZMDLogs / Endfield Logs 源码开发。
提供 Python + PySide6（Qt）GUI、实时伤害浮窗、本地 trace 导入和战斗分析。
此项目是独立开发版，项目中的“官网版”指 ZMDLogs 的发行版。
相关项目：[ZMDLogs 官网](https://zmdlogs.com/)、[AKEData 网站](https://www.akedata.wiki/)、
[AKEData Git 仓库](https://github.com/NagiYume/AKEDatabase)。

目前未实现 i18n，界面及维护文档以中文为主。

## 功能与实现链路

本程序不向游戏进程注入代码，不对游戏进程做 Hook、读写内存或修改游戏文件，即不含针对游戏进程的运行时侵入。
实时数据来自 Npcap 被动抓包；登录解码会在本程序自己的进程内加载游戏目录的 `GameAssembly.dll`，
调用其导出函数，再通过 RSA／会话密钥处理捕获数据。它不向游戏通信链路插入代理，游戏 DLL 也不随包分发。

| 功能 | 实现链路 | 主要代码入口（`_internal/src/endfield_pcap/` 下） |
| --- | --- | --- |
| 采集与日志 | Npcap → TCP 重组 → 登录/会话解码 → protobuf 事件 → TraceBridge → 同一份 trace 落盘及分析输入 | `capture/`、`crypto/`、`service/session/`、`trace/bridge.py` |
| 实时伤害与贡献 | trace 增量更新 → canonical 状态及 rDPS 分配 → 轻量团队/角色摘要 → Qt 桥 → HTML 浮窗 | `analysis/live/`、`service/runtime/analysis.py`、`overlays/`；计算在 `parser_core` |
| 完整实时接口 | 按消费者需求启动独立工作进程 → 同一核心生成完整报告 → WebSocket 完整快照；摘要流独立发布 | `analysis/live/`、`service/runtime/websocket.py` |
| 历史记录 | 引用原文件 → 分场索引 → 选中后后台解析 → canonical 完整报告；批量加载仅显示最后选择 | `history/`、`gui/pages/history/` |
| 战斗分析 | 完整报告 → 技能/BUFF/敌方/技力等界面投影 → 原生 Qt 或本地 WebEngine 时间轴与详情 | `analysis/battle/`、`gui/battle/` |
| BUFF 浮窗 | trace 生命周期与层数 → 当前状态 → 独立展示快照及倒计时；显示估算不参与 rDPS 判定 | `analysis/buffs/`、`overlays/assets/buff/` |
| 浮窗与 OBS | 模板订阅 → Qt/WebEngine 渲染 → Windows 10 窗口采集；显隐与分析启用分开 | `overlays/manager.py`、`overlays/window.py` |
| 官网上传 | 原始 `trace_*.log` 与配套 status → 独立官网 uploader → 官网解析及上传；本体不代替官网处理 | `trace/`、独立 `Uploader/` |
| 数据与环境 | 源码附带精简数据包 → 清单校验恢复；便携包自带 Python、Qt 和所需依赖 | `runtime/`、`data/`、`_development/tools/` |

增量分析允许迟到证据修正及异常重放；轻量摘要与完整报告共用计算口径，不跳过归因证据。
连携 CD 功能已停用，代码保留。更多入口见 [源码导航](_internal/src/README.md)，
接口细节见 [实时摘要接口](_development/docs/live-summary-publisher.md)。
本地 WebSocket 的网页连接需要访问凭据，可在「设置 → 服务连接」复制地址；GUI 内置数据桥不受影响。
不带 Origin 的原生本地客户端保留兼容接入，因此这项防护阻止未授权网页读取，不隔离本机程序。

## 使用便携包

完整解压发行 ZIP，双击 `Start-GUI.cmd`。便携包包含 Python、Qt / WebEngine 和运行依赖，
无需另装 Python 或 Qt。个人配置、日志和历史列表写入 `.dev-gui/`。
实时抓包另需安装 [Npcap（官方下载安装页）](https://npcap.com/#download)，
并在「设置 → 游戏路径」选择 `Endfield.exe` 或游戏目录；以后也可在这里重新选择。程序不附带游戏 DLL。
启动时 CMD 短暂出现后退出，运行期间只显示 GUI 和 Overlay；`--check` 保持控制台检查。
GUI 打开后自动尝试启动抓包一次，首页同一按钮启动/停止；主动停止后不会自行重启。
停止后再启动无法接续正在运行的游戏会话，需要重开游戏。运行输出在左侧「运行日志」查看，
同时保留磁盘日志；缺少 Npcap、密钥或游戏目录不影响历史分析。详见 [GUI 启动说明](_development/docs/gui-launch.md)。

**新采集的 `trace_*.log` 连同 `.log.status.json` 兼容 ZMDLogs 官网版 uploader，无需导出转换版。**
官网原版 uploader 单独打包，主程序包不含它；只使用本地分析与 Overlay 时无需下载。
uploader 包自带依赖，可在任意目录独立运行；所有文件从校验过的官网包原样提取。
位置、日志选择及上传前提见 [运行资源说明](_development/docs/runtime-resources.md)。

## 从源码开发

当前验证环境是 Windows x64、CPython 3.14.2、PySide6 及 Qt WebEngine。
源码仓库只保留开发必要内容及提取后的运行数据：Python 运行时、依赖、上游原始数据、密钥、官网 uploader、
真实战斗、个人配置、实施记录和发行 ZIP 均不提交。

1. 执行 `Setup-Dev.cmd`：已有依赖能导入就复用，缺什么才安装，不锁版本或主动升级；
   从源码附带的精简数据包离线恢复运行数据并校验，开发版规则不会被覆盖；不下载完整原始数据。
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

- `_internal/src/`：按功能分类的应用源码、Qt GUI、Overlay 和本地 Web 分析资产，见 [源码导航](_internal/src/README.md)。
- `_internal/packages/`：`parser_core`、`uploader_core` 及其测试。
- `_internal/data/`、`_internal/jsondata/`：提取后的运行数据；Git 保留约 5.8 MB 的恢复包及清单、开发版规则与说明，运行数据共约 16.9 MB。
- `_development/`：当前测试、工具、使用文档；`raw-resources/` 原始数据、历史实施记录、实验和验证输出留在本地。
- `.dev-gui/`、`_releases/`、`Uploader/`：本地状态、便携发行、可选官网 uploader，均忽略。

更多功能文档见 [_development/README.md](_development/README.md)。
提交时保留源码和测试，排除个人日志、配置、密钥及安装后的依赖。
`.gitattributes` 定义源码 LF、Windows 启动脚本 CRLF；协议样本和校验敏感资源保留原始字节。

## 版本与打包

版本唯一来源是 `_internal/src/endfield_pcap/_version.py`，GUI 和构建器共用。
开发版本使用 `0.1.0-dev.2` 等，正式版使用 `0.1.0` 等 SemVer，不在版本里加日期或前导 `v`。

```powershell
python -B _development/tools/release.py version                 # 查看版本与包名
python -B _development/tools/release.py version 0.1.0-dev.5     # 发布前设置版本
python -B _development/tools/release.py build                   # 回归、构建、ZIP、解压启动校验
python -B _development/tools/release.py build --component uploader # 可选：单独构建官网上传器
```

输出到 `_releases/EndfieldLogs-<版本>-windows-x64.zip`，附 SHA-256 和逐文件构建清单。
同版本不覆盖；不自动上传发行附件或修改远程仓库。完整流程见 [打包说明](_development/docs/portable-packaging.md)。
重打包先比较源码及包内文件差异，再按变化选择测试；只改文档无需重复全套回归。
同一源码已通过相应回归时使用 `build --skip-tests`，仍校验 ZIP 清单和解压启动。

## 许可与来源

本开发版的新增和修改代码，以及包含 GPLv3 GUI 依赖的组合程序，采用 **GPL-3.0-only**，见 [LICENSE](LICENSE)。
上游 MIT 代码仍保留其版权声明及许可；各依赖继续按各自许可证授权。
GPLv3 允许商业使用，分发程序需履行对应源码、许可和修改说明等义务，不另加禁止商用条件。
来源及边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，具体交付要求见 [许可与再分发](_development/docs/licensing.md)。
仓库内第三方资源有明确许可的保留许可，未附明确许可的注明来源；数据来源包括 AKEData 与固定版本的 ZMDLogs 发行包，不由本项目 GPLv3 重新授权。
