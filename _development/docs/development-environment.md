# 开发环境初始化

Windows x64 项目根目录执行 `Setup-Dev.cmd`，完成后用 `Start-GUI.cmd` 启动。

| 当前环境 | 初始化行为 |
| --- | --- |
| Python 与依赖可导入 | 直接复用 |
| 项目环境缺少依赖 | 安装缺项 |
| 系统环境部分可用 | 建立项目 `.venv` 并补齐 |
| 缺少 Python | 下载并校验官方 CPython 3.14.2 NuGet 包，再建立 `.venv` |

依赖按实际导入检查，已有版本可继续使用。PySide6 自带 Qt/WebEngine。
运行数据由源码附带的精简包离线恢复，恢复包和文件逐项核对 SHA-256，开发规则取当前源码。

```powershell
.\Setup-Dev.cmd -Check                 # 只读检查；缺项返回 2
.\Setup-Dev.cmd                        # 复用或补齐
.\Setup-Dev.cmd -Isolated              # 独立项目环境
.\Setup-Dev.cmd -PythonPath C:/Python314/python.exe -Isolated
```

环境路径限定在项目内。已有环境不兼容时，用 `-EnvironmentPath .venv-other -Isolated` 另建。
失败后保留环境和缓存，可重跑续用。

## 依赖与离线安装

- `environment/requirements-runtime.txt`：运行依赖。
- `environment/requirements-dev.txt`：另加 pytest、packaging。
- `portable/runtime-requirements.txt`：发行依赖锁，构建时逐项核对版本与依赖闭包。
- `environment/constraints-ci.txt`：复用发行依赖锁，并固定测试工具版本。

安装源为官方 PyPI，传递依赖交给 pip。离线首次安装需准备适配 Python/Windows 的完整 wheels 和解释器归档：

```powershell
.\Setup-Dev.cmd -Isolated -PythonSource Download -Offline `
  -PythonArchive "D:/Resources/python.3.14.2.nupkg" `
  -Wheelhouse "D:/Resources/dev-env-wheelhouse"
```

缓存位于 `_development/cache/`；缺文件时报错。

## 持续集成

`.github/workflows/ci.yml` 在 main 推送、PR 和手动触发时运行一个 Windows 任务：

1. 安装 CPython 3.14.2 与约束文件指定的依赖。
2. 从仓库内精简包离线恢复运行数据，执行仓库审计。
3. 执行 `live`、`parser_core`、`uploader_core`，保留测试日志和 JUnit 报告 14 天。

Actions 固定到官方提交。桌面、硬件及外部资源测试沿用各自启用条件；发行 ZIP 在本地构建验证。

## 启动与验证

解释器优先级：`ENDFIELD_GUI_PYTHON` → 便携 Python → 初始化记录 → `.venv` → 系统 Python。
环境选择写入 `.dev-gui/dev-python.txt`；虚拟环境使用自己的依赖，便携包使用随包依赖。

本地日志可直接离线分析，实时抓包另需 Npcap 和游戏安装。资源检查 `--check` 核对清单是否存在；完整验证使用：

```powershell
python -B _development/tools/prepare_resources.py
python -B _development/tools/audit_runtime_data.py
python -B _development/tools/audit_runtime_data.py --exercise
```

`-ResourceArchive` 用于官网外部组件。资源维护见 [运行资源](runtime-resources.md)，回归命令见 [测试分类](../tests/README.md)。
