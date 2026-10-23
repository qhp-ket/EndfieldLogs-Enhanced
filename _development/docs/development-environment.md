# 开发环境初始化

在 Windows x64 项目根目录执行 `Setup-Dev.cmd`，完成后仍用 `Start-GUI.cmd` 启动。

- 已有完整环境：依赖能够实际导入就直接复用，不比较版本，不执行 pip。
- 项目环境缺少依赖：只安装无法导入的包，不主动升级已有依赖。
- 没有可用 Python：下载官方 Python 到项目缓存，建立 `.venv` 并安装缺少的依赖。

系统只有部分依赖且没有完整项目环境时，会建立独立 `.venv`，不更改全局或用户级包。
PySide6 发行物自带 Qt 和 WebEngine，无需另装 Qt SDK 或 Node 服务。
脚本会为源码克隆恢复缺少的上游运行数据，校验固定官网 ZIP 和逐文件 SHA-256；
已有完整资源不重复下载，不覆盖开发版规则。脚本不安装 Npcap，不改系统 PATH、注册表、
游戏目录或抓包私钥。上游大文件不提交 Git。

```powershell
.\Setup-Dev.cmd -Check                 # 只读检查；缺项返回退出码 2
.\Setup-Dev.cmd                        # 自动复用或补齐
.\Setup-Dev.cmd -Isolated              # 即使旧工作区可用，也建立独立项目环境
.\Setup-Dev.cmd -PythonPath C:/Python314/python.exe -Isolated
```

只保留 Windows x64 平台检查；已有 Python 和依赖通过实际导入判断，不比较版本。
没有解释器时默认下载已验证的 CPython 3.14.2 NuGet 包，
其 SHA-256 用于校验下载文件，不限制已有解释器。

已有 `.venv` 不兼容时不会被覆盖，可指定 `-EnvironmentPath .venv-other -Isolated`。
环境路径须在项目内；`.venv*`、下载缓存和环境选择记录均由 Git 忽略。
失败时保留环境和缓存，重跑同一命令即可继续。

## 依赖清单与离线安装

`_development/environment/requirements-runtime.txt` 列出运行依赖，
`requirements-dev.txt` 另加 pytest、packaging。两份清单均不锁版本。
`_development/portable/runtime-requirements.txt` 是已有便携包的构建记录，不作为开发安装限制。
初始化根据实际导入结果安装缺项；包的传递依赖由 pip 处理，不额外执行版本匹配检查。

默认从官方 PyPI 安装。离线时可提供适合目标 Python/Windows 的 wheels：

```powershell
.\Setup-Dev.cmd -Isolated -PythonSource Download -Offline `
  -PythonArchive "D:/Resources/python.3.14.2.nupkg" `
  -Wheelhouse "D:/Resources/dev-env-wheelhouse"
```

已有完整环境不需要 wheel 目录或网络。离线首次安装需要备齐包及传递依赖，
缺文件时明确报错，不把未安装报告成成功。缓存位于 `_development/cache/`。

## 启动与资源

`Start-GUI.cmd` 优先级：显式 `ENDFIELD_GUI_PYTHON`、便携包内 Python、
初始化记录的项目环境、默认 `.venv`、系统 Python。
环境选择只写入 `.dev-gui/dev-python.txt`，不改已有 GUI 设置。
虚拟环境不混入 `_internal/python_deps`；旧源码环境和便携包保留原有依赖使用方式。

缺少抓包私钥时 GUI 提示后仍可进行离线分析；实时服务另需私钥、Npcap 和自己的游戏安装。
详见 [运行资源说明](runtime-resources.md)。环境检查只报告资源清单是否存在，
离线资源恢复可用 `-ResourceArchive "D:/Resources/EndfieldLogsClient_3.0.12_20261016.zip"`，
单独准备数据用 `python -B _development/tools/prepare_resources.py`。
完整资源验证另执行：

```powershell
python -B _development/tools/audit_runtime_data.py
python -B _development/tools/audit_runtime_data.py --exercise
```

## 回归

```powershell
.venv/Scripts/python.exe -B _development/run_tests.py live
.venv/Scripts/python.exe -B _development/run_tests.py parser_core
.venv/Scripts/python.exe -B _development/run_tests.py uploader_core
```

复用现有环境时改用对应解释器。普通回归使用公开合成样本；真实密钥、官网基准和实际游戏采集各有独立入口。
