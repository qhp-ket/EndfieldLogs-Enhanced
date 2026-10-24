# 源码开发需要的运行资源

源码附带提取后的 `runtime-data.zip`，约 5.8 MB，运行数据共约 16.9 MB。
`Setup-Dev.cmd` 或 `python -B _development/tools/prepare_resources.py` 会离线恢复并校验，
不再为普通开发环境下载约 390 MB 的上游原始数据。开发版规则保留在源码中；
已有资源不匹配会报错，不直接覆盖。便携版包含已解压的同一份运行数据。

完整输入仅供维护提取规则，保存在 Git 忽略的 `_development/raw-resources/_internal/`，
程序不会从这里回退读取。显式添加 `--raw` 才准备完整输入；
`--archive PATH --offline` 可指定固定官网 ZIP。
`--with-uploader` 和 `--with-capture-key` 仍是独立的显式选项。
提取规则、重建与等价验证见 [data 说明](../../_internal/data/README.md)。

## 抓包私钥

程序使用 `_internal/secrets/client_privkey.pem` 从捕获的登录响应中解出会话密钥，
随后解密游戏通信。它不是日志文件的二次加密密钥，也不是个人账号凭据。
Git 忽略实际 PEM，仅提交 `_internal/secrets/README.md`。

准备方法：从可信的 ZMDLogs 官网下载完整客户端 ZIP，解压后取得
`EndfieldLogsClient/_internal/secrets/client_privkey.pem`，复制到本项目同名位置。
不要把密钥正文贴到提交、问题报告或配置示例中；不要用自行生成的密钥替代。

也可显式执行 `python -B _development/tools/prepare_resources.py --with-capture-key`，
从同一固定、校验过的 ZIP 提取到忽略目录；普通数据准备不会获取密钥。

当前便携构建核对的是官网 3.0.12（2026-10-16）发行包中的这一份资源，SHA-256 为：

```text
b83257fadefe901f708386da11ffcde0eb0dee6450a6b56fc1b85e197cab1b56
```

上游更换密钥后需另行验证再更新构建约束，不能直接放宽为任意 PEM。
启动器在文件缺少时提示，服务初始化时读取 RSA 私钥。后续包使用会话密钥解密。
仅持有 PEM 不代表拥有完整抓包或可读取任意账号通信。

实时抓包还需要系统 Npcap，以及用户自己的游戏安装目录和 `GameAssembly.dll`。
本仓库不分发游戏 DLL。离线 trace 解析和打开 GUI 均不要求 PEM；启动实时服务前需准备好。

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

普通回归使用合成数据，不读取真实私钥。打包器的普通测试使用测试专用 RSA 密钥，
仅在测试中替换允许的哈希，不改变实际打包器对白名单密钥的要求。

只有 `requires_capture_key` 集成测试读取真实官网 PEM。默认跳过，显式运行：

```powershell
python -B _development/run_tests.py capture-key
python -B _development/run_tests.py capture-key --capture-key-path "D:\Resources\client_privkey.pem"
```

显式运行后，文件缺失或哈希不匹配均报告失败，便于区分“尚未准备资源”和“验证通过”。
这项测试证明发行资源符合构建约束，不证明当前游戏网络一定可成功解密，也不执行上传。

已有便携 ZIP 保持原内容不变；它已经包含所需运行资源。上述说明主要面向源码克隆和重新打包。
