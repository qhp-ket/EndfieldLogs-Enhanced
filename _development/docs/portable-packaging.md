# 版本、构建与 ZIP 验证

版本唯一来源为 `_internal/src/endfield_pcap/_version.py`。
GUI、包名和构建清单都读取这里。开发版按 `0.1.0-dev.1` 递增，正式版如 `0.1.0`，
不加前导 v 或日期；Git 标签如需使用 `v0.1.0`。核心库与协议标识不随 GUI 版本改写。

```powershell
python -B _development/tools/release.py version
python -B _development/tools/release.py version 0.1.0-dev.2
```

改版本、测试、提交源码后构建，便于清单记录源 commit。
产物固定为 `_releases/EndfieldLogs-<版本>-windows-x64.zip`，解压顶层目录同名。
同版本目录或 ZIP 已存在则拒绝覆盖。

源码开发依赖不锁版本。便携构建目前使用已验证的 Windows x64 CPython 3.14；
收集当前解释器和依赖并记录实际版本，不复制整个用户 site-packages。

```powershell
.\Setup-Dev.cmd
python -B _development/tools/prepare_resources.py --with-uploader --with-capture-key
python -B _development/tools/release.py build
```

资源脚本校验固定官网 3.0.12 ZIP 的 SHA-256，保护开发版覆盖规则。
可以 `--archive PATH --offline` 使用本地 ZIP。
官网 uploader 保持原版；抓包密钥只放本地忽略目录，构建拒绝未知私钥和账号状态。

build 依次执行应用、parser_core、uploader_core 回归，校验资源、建立干净 staging、
生成 ZIP/CRC/`.zip.sha256`，最后解压到新的中文和空格路径并验证。
日志和截图写入忽略的 `_development/verification/`，不进入包或 Git。

`BUILD-MANIFEST.json` 记录应用版本、UTC 构建时间、源 commit（未提交时为空）、
Python/依赖实际版本、各文件大小和 SHA-256。
ZIP 包括隔离 Python、Qt/WebEngine、程序/数据、官网 uploader、许可及使用说明；
不包括个人配置、真实日志、测试、开发环境和历史资料。

同一源码已完成回归时可用 `build --skip-tests`。
手工检查 staging 可用 `build --stage-only`，之后执行：

```powershell
python -B _development/tools/build_portable.py --zip-stage "_releases/EndfieldLogs-0.1.0-dev.1-windows-x64"
python -B _development/tools/release.py verify "_releases/EndfieldLogs-0.1.0-dev.1-windows-x64.zip"
```

解压验证使用包内 Python，清除外部 Python 配置和系统 Python PATH，
运行 CMD --check、GUI、伤害浮窗、合成 trace、本地 Web 分析和独立分析进程。
使用隔离配置，不登录、不上传、不抓包；每次使用新目录，允许重复验证。
脚本不推送 Git、不创建远程 Release、不安装驱动。Npcap 和游戏由使用者准备。
