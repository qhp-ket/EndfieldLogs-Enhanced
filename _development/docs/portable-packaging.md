# 版本、构建与 ZIP 验证

版本唯一来源为 `_internal/src/endfield_pcap/_version.py`。
GUI、包名和构建清单都读取这里。开发版按 `0.1.0-dev.1` 递增，正式版如 `0.1.0`，
不加前导 v 或日期；Git 标签如需使用 `v0.1.0`。核心库与协议标识不随 GUI 版本改写。

```powershell
python -B _development/tools/release.py version
python -B _development/tools/release.py version 0.1.0-dev.2
```

改版本、测试、提交源码后构建，便于清单记录源 commit。
产物固定为 `_releases/Endfield-Logs-Enhanced-<版本>-windows-x64.zip`，解压顶层目录同名。
同版本目录或 ZIP 已存在则拒绝覆盖。

源码开发依赖不锁版本。便携构建目前使用已验证的 Windows x64 CPython 3.14；
收集当前解释器和依赖并记录实际版本，不复制整个用户 site-packages。

```powershell
.\Setup-Dev.cmd
python -B _development/tools/prepare_resources.py --with-capture-key
python -B _development/tools/release.py build
```

资源脚本校验固定官网 3.0.12 ZIP 的 SHA-256，保护开发版覆盖规则。
可以 `--archive PATH --offline` 使用本地 ZIP。
官网 uploader 从通过 SHA-256 校验的官方 ZIP 直接提取，不使用本地 uploader 的运行状态，
程序、依赖和数据均保持原字节。构建拒绝未知私钥和账号状态。

build 依次执行应用、parser_core、uploader_core 回归，校验资源、建立干净 staging、
生成 ZIP/CRC/`.zip.sha256`，最后解压到新的中文和空格路径并验证。
日志和截图写入忽略的 `_development/verification/`，不进入包或 Git。

`BUILD-MANIFEST.json` 记录应用版本、UTC 构建时间、源 commit、工作区是否有未提交修改（`source_dirty`）、
Python/依赖实际版本、各文件大小和 SHA-256。
主程序 ZIP 包括隔离 Python、Qt/WebEngine、程序/数据、许可及使用说明，不包含 uploader；
不包括个人配置、真实日志、测试、开发环境和历史资料。
本开发版组合程序采用 GPL-3.0-only，构建会附上 GPL 全文、上游 MIT 及许可交付说明；
源码许可及入库资源来源见 [许可与再分发](licensing.md)。
发行时按实际依赖许可保留版权、许可、修改说明及源码取得材料；按 GPLv3 第 6 条等适用条款，
提供对应版本的完整源码和构建/安装材料，确保接收者能够取得。
本项目源码、依赖版本清单和许可文本不能代替编译依赖要求提供的对应源码。
构建清单记录版本与文件哈希，新增依赖或更新版本时同步核对这些交付材料。

先检查源码 diff，并按相对路径、大小及 SHA-256 比较上一份包的清单，再决定验证范围：

- 仅文档变化：检查内容、链接及包内文件差异，不重复全套测试。
- 打包器、启动脚本或依赖变化：运行 `app-resources` 及全新目录解压启动验证。
- 解析、服务或界面变化：运行对应分类；跨模块重构或公共核心变化再扩大全套回归。

同一源码已完成相应回归时用 `build --skip-tests`，仍执行 ZIP 与解压验证。
手工检查 staging 可用 `build --stage-only`，之后执行：

```powershell
python -B _development/tools/build_portable.py --zip-stage "_releases/Endfield-Logs-Enhanced-0.1.0-dev.1-windows-x64"
python -B _development/tools/release.py verify "_releases/Endfield-Logs-Enhanced-0.1.0-dev.1-windows-x64.zip"
```

解压验证使用包内 Python，清除外部 Python 配置和系统 Python PATH，
运行 CMD --check、GUI、伤害浮窗、合成 trace、本地 Web 分析和独立分析进程。
使用隔离配置，不登录、不上传、不抓包；每次使用新目录，允许重复验证。
脚本不推送 Git、不创建远程 Release、不安装驱动。Npcap 和游戏由使用者准备。

## 运行数据边界

开发环境和发行版共用 schema 2 的精简资源清单，约 16.9 MB。
构建器只收集清单成员；本地原始数据、测试证据、审计材料和源码恢复 ZIP 均不进入运行包。
缺少运行数据时先执行 `prepare_resources.py`；普通准备从源码附带的约 5.8 MB 包离线恢复。
重新提取见 [data 说明](../../_internal/data/README.md)。旧发行 ZIP 不会自动重建或覆盖。

## 依赖裁剪与解压后体积

`portable_dependencies.py` 明确列出应用使用的 Qt Python 模块、插件和浏览器资源，
再读取 PE 普通导入及延迟导入，收齐 wheel 内的 DLL 依赖。
保留 Windows/offscreen 平台、图片插件、TLS、软件 OpenGL，以及简繁中文和英文浏览器语言资源。
不带 Designer/QML 开发工具、未使用的绑定、调试资源、开发头文件、类型存根和帮助文档。
新增 Qt 模块时应更新清单；应用导入检查会检测遗漏。

`portable_uploader.py` 只提取官方 ZIP 中的 uploader 子目录；ZIP 验证会将每个文件与官方原件逐字节比较。

验收以所有文件大小之和为主要指标，不靠外套压缩包、首次启动解压或下载减少标称体积。
构建清单记录依赖裁剪策略和未压缩文件体积。重新解压验证包括隔离启动、GUI、Overlay、
两种战斗分析界面及工作进程；`verify_uploader_resources.py` 逐文件验证 uploader，
并用未修改的官网 parser/uploader 源码对六份合成日志比较完整 payload 与上传文档。

## Uploader 独立发行

主程序包始终独立于 uploader：不收集本地 `Uploader/`，也不要求它存在。
只使用本地分析、抓包和 Overlay 的用户下载主程序包即可。

官网 uploader 使用自己的上游版本号，当前产物固定为
`_releases/EndfieldLogsUploader-3.0.12-windows-x64.zip`，不随主程序版本重复生成。
它包含自己的运行依赖，解压后可独立运行；需要放进主程序目录时，只复制整个 `Uploader/`。
主程序与 uploader 的清单、SHA-256 文件和验证结果各自独立。

```powershell
python -B _development/tools/release.py build --component uploader
python -B _development/tools/release.py verify _releases/EndfieldLogsUploader-3.0.12-windows-x64.zip
```

`build` 默认 `--component application`，上传器为可选组件；`build-uploader` 保留为兼容别名。
上传器构建运行 uploader_core 回归；ZIP 验证检查清单、官方 EXE 和所有原始资源字节。
维护者准备好本地官网源码后，还可执行完整上传 payload 等价检查：

```powershell
python -B _development/tools/verify_uploader_resources.py --stage _releases/EndfieldLogsUploader-3.0.12-windows-x64 --runtime-root _releases/EndfieldLogs-<主程序版本>-windows-x64 --output _development/verification/uploader-check
```

独立 uploader 包无需携带主程序 Python；上述验证借用主程序 staging 的隔离运行时。
