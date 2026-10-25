# 版本与便携打包

版本来源为 `_internal/src/endfield_pcap/_version.py`，GUI、包名和清单共用。
应用按 SemVer：开发版 `0.1.0-dev.1`，正式版 `0.1.0`；对应 Git 标签可加 `v`。

```powershell
python -B _development/tools/release.py version
python -B _development/tools/release.py version 0.1.0-dev.2
```

## 构建流程

修改版本、选择测试、提交源码后构建，清单记录该 commit。
Windows x64 构建使用当前 CPython 3.14 和实际安装的依赖，按使用范围及 PE 依赖闭包收集。
`portable/runtime-requirements.txt` 固定发行依赖闭包；构建前核对包集合与精确版本，依赖升级需同步锁文件并验证。

```powershell
.\Setup-Dev.cmd
python -B _development/tools/prepare_resources.py
python -B _development/tools/release.py build                        # 默认本体
python -B _development/tools/release.py build --component uploader   # 官网上传器
```

`build` 执行对应回归、资源校验、干净 staging、ZIP/CRC/SHA-256 和新路径解压验证。
已测试的同一份源码使用 `build --skip-tests`。同版本目录或 ZIP 已存在时，先核对并归档产物。
正式构建要求干净工作区；开发暂存使用 `build --stage-only --allow-dirty`，带未提交改动的 staging 仅供本地检查。

| 产物 | 内容 |
| --- | --- |
| `Endfield-Logs-Enhanced-<版本>-windows-x64.zip` | 本体源码、精简数据、隔离 Python、Qt/WebEngine、SDL3、依赖、许可和使用说明 |
| `EndfieldLogsUploader-3.0.12-windows-x64.zip` | 校验过的官方 ZIP 内 uploader 目录及原始运行依赖 |
| `*.zip.sha256` | 整包校验值 |
| `BUILD-MANIFEST.json` | 版本、UTC 时间、源 commit、`source_dirty`、依赖版本及逐文件大小/SHA-256 |

输出目录为 `_releases/`。本体和 uploader 独立发行，uploader 使用上游版本号。
官方 ZIP 可通过资源工具的 `--archive PATH --offline` 提供。

## 按差异验证

先看源码 diff，再按相对路径、大小和 SHA-256 比较上一份包：

| 改动 | 验证范围 |
| --- | --- |
| 文档、许可、排版 | 内容、链接及包内差异 |
| 打包器、启动脚本、依赖 | `app-resources` 与全新目录解压启动 |
| 解析、服务、界面 | 对应测试分类 |
| 跨模块重构、公共核心、依赖整体升级 | 全套回归 |

手工检查 staging 时：

```powershell
python -B _development/tools/release.py build --stage-only --skip-tests
python -B _development/tools/build_portable.py --zip-stage "_releases/Endfield-Logs-Enhanced-<版本>-windows-x64"
python -B _development/tools/release.py verify "_releases/Endfield-Logs-Enhanced-<版本>-windows-x64.zip"
```

本体验证使用包内 Python，清除外部 Python 配置和系统 Python PATH。
中文空格新目录中检查 CMD、GUI、浮窗、合成 trace、两种战斗分析及独立工作进程，输出写入 `_development/verification/`。
GUI 首次运行后整体移动目录，再检查启动、已保存设置和包内资源路径。验包完整性检查在 `python -O` 下同样执行。
Uploader 验证将 3261 个原始文件与官方 ZIP 逐字节比较。

维护者有本地官网源码时，可额外对六份合成日志比较完整上传 payload：

```powershell
python -B _development/tools/verify_uploader_resources.py `
  --stage _releases/EndfieldLogsUploader-3.0.12-windows-x64 `
  --runtime-root _releases/Endfield-Logs-Enhanced-<版本>-windows-x64 `
  --output _development/verification/uploader-check
```

## 资源、依赖与许可

- 解析数据约 16.9 MB，构建器只收集 schema 2 清单成员；更新流程见 [data 说明](../../_internal/data/README.md)。
- `portable_dependencies.py` 列明 Qt 模块、插件和资源，沿 PE 普通/延迟导入补齐 DLL；新增模块同步修改清单。
- 保留 Windows/offscreen 平台、图片、TLS、软件 OpenGL、Multimedia/FFmpeg 及简繁中文/英文浏览器资源。
- 包体以解压后的文件大小总和计量，个人配置、日志、测试及开发缓存由构建边界排除。
- 发行携带 GPLv3、上游 MIT、依赖许可与版本清单；对应源码及构建材料按 [许可说明](licensing.md) 交付。

构建、Git 推送和 GitHub Release 发布分别执行；驱动由使用者安装。
