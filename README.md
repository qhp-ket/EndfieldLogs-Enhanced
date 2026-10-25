# Endfield Logs - Enhanced

《明日方舟：终末地》的第三方战斗日志客户端，基于 ZMDLogs / Endfield Logs 源码开发。
提供实时伤害浮窗、图像识别连携 CD、输入记录及本地战斗分析，界面和文档使用中文。
本文中的「官网版」指 ZMDLogs 发行版。

相关项目：[ZMDLogs 官网](https://zmdlogs.com/)、[AKEData 网站](https://www.akedata.wiki/)、[AKEData 仓库](https://github.com/NagiYume/AKEDatabase)。

## 功能与实现链路

程序不含针对游戏进程的运行时侵入：注入、Hook、读写内存或修改游戏文件。
采集使用 Npcap 被动抓包，解码在本程序进程内调用本机游戏 `GameAssembly.dll` 导出函数；游戏 DLL 由用户安装提供。

以下代码路径相对 `_internal/src/endfield_pcap/`：

| 功能 | 实现链路 | 代码入口 |
| --- | --- | --- |
| 采集与日志 | Npcap → TCP 重组 → 会话解码 → protobuf → TraceBridge 落盘及分析 | `capture/`、`crypto/`、`service/session/`、`trace/` |
| 实时伤害/贡献 | trace 增量更新 → canonical/rDPS → 轻量摘要 → Qt 桥 → 浮窗 | `analysis/live/`、`service/runtime/`、`overlays/` |
| 完整实时接口 | 按订阅启动独立进程 → 同一核心完整报告 → WebSocket | `analysis/live/`、`service/runtime/websocket.py` |
| 历史与战斗分析 | 文件引用 → 分场索引 → 后台完整分析 → Qt/WebEngine 时间轴 | `history/`、`analysis/battle/`、`gui/battle/` |
| 浮窗与 OBS | 模板订阅 → Qt/WebEngine 窗口 → Windows Graphics Capture | `overlays/manager.py`、`overlays/window.py` |
| 连携 CD | 游戏 HWND → WGC → HUD 像素 → 跨帧状态 → 浮窗 | `vision/`、`gui/independent/` |
| 输入记录 | 独立进程 → Raw Input/兼容采集、SDL3 → JSONL → 每场绑定 → 时间轴 | `inputlog/`、`gui/services.py`、`gui/battle/input_history.py` |
| 官网上传 | 原始 trace/status → 独立官网 uploader → 官网解析上传 | `trace/`、独立 `Uploader/` |
| 数据与环境 | 精简数据包 → 清单校验恢复；便携包携带 Python、Qt 和依赖 | `runtime/`、`data/`、`_development/tools/` |

摘要和完整报告共用 `parser_core` 计算口径，支持迟到证据修正及异常重放。
连携和输入服务独立于 Npcap；抓包可为连携补充姓名和头像。详细接口见 [实时摘要](_development/docs/live-summary-publisher.md) 和 [独立服务](_development/docs/independent-services.md)。

## 使用便携包

1. 完整解压本体 ZIP，双击 `Start-GUI.cmd`；CMD 在 GUI 显示后退出。
2. 在「设置 → 游戏路径」选择 `Endfield.exe` 或游戏目录。
3. 实时抓包另需 [Npcap 官方安装程序](https://npcap.com/#download)。点首页「启动抓包」后进入游戏。
4. 历史分析可直接在「战斗日志」导入本地 trace。

抓包和输入记录默认关闭，可在设置中分别开启随启动运行。
**停止抓包后再启动，需要重开游戏。** 配置、日志和历史列表位于 `.dev-gui/`，运行输出见「运行日志」。

常用控制：

- **GUI**：`Ctrl+Shift+O` 或首页按钮隐藏/恢复到托盘，后台服务继续运行。
- **浮窗**：`Ctrl+O` 一键显隐；列表支持拖拽排序并保存。「启用」控制功能，「显示浮窗」控制桌面可见性。
- **伤害浮窗**：随尺寸缩放，字体和头像另有独立比例滑条，列数变化自动调整窗口宽度。
- **连携 CD**：在悬浮窗页启用，提供圆形/进度条样式；就绪变绿，不可读时延续可信状态。
- **OBS**：添加窗口采集，方式选 Windows 10（WGC）；隐藏浮窗期间仍可捕获。
- **更新**：设置的「关于」检查正式 Release 版本和发布日期，前往发布页手动下载；支持忽略版本。

窗口和头像选项见 [悬浮窗模板](_development/docs/overlay-templates.md)，启动排查见 [GUI 说明](_development/docs/gui-launch.md)。

### 输入记录与上传

输入仅采集游戏前台操作，普通权限下由记录子进程申请管理员授权。
文件与 trace 放在同一日期目录：独立录制为 `input_*.input.jsonl`，抓包时为配套 `trace_*.input.jsonl`。

战斗分析可自动发现配套文件，也可每场「绑定 input log」，再勾选「显示输入」。选择覆盖本场时间的文件，以毫秒级系统时间对齐到战斗范围。
输入用于展示操作意图，技能释放与贡献计算采用 trace 证据。

**`trace_*.log` 连同 `.log.status.json` 可直接用于 ZMDLogs 官网版 uploader。**
官网 uploader 独立打包，文件从校验过的官方 ZIP 原样提取；输入文件仅用于本地分析。
布局及上传前提见 [运行资源](_development/docs/runtime-resources.md)。

## 从源码开发

验证平台为 Windows x64、CPython 3.14.2、PySide6/Qt WebEngine。

```powershell
.\Setup-Dev.cmd              # 复用可用环境、补齐依赖、离线恢复精简数据
.\Start-GUI.cmd --check      # 检查启动条件
.\Start-GUI.cmd
```

初始化细节见 [开发环境](_development/docs/development-environment.md)。

| 目录 | 内容 |
| --- | --- |
| `_internal/src/` | 按功能组织的应用源码，见 [源码导航](_internal/src/README.md) |
| `_internal/packages/` | parser_core、uploader_core 及测试 |
| `_internal/data/`、`jsondata/` | 精简运行数据、来源清单与规则，见 [数据维护](_internal/data/README.md) |
| `_development/` | 当前维护的测试、工具、中文文档，见 [开发导航](_development/README.md) |

Git 采用源码白名单，个人状态、真实日志、原始数据、安装环境及发行产物留在本地。
`.gitattributes` 指定源码 LF、Windows 启动脚本 CRLF，校验敏感资源保留原字节。

## 测试与打包

使用项目选择的 Python 环境：

```powershell
python -B _development/run_tests.py live
python -B _development/run_tests.py parser_core
python -B _development/run_tests.py uploader_core
```

测试分类和按改动选择范围见 [测试说明](_development/tests/README.md)；公开回归使用合成日志。

版本来源为 `endfield_pcap/_version.py`，使用 SemVer，如 `0.1.0-dev.1`、`0.1.0`。

```powershell
python -B _development/tools/release.py version
python -B _development/tools/release.py build
python -B _development/tools/release.py build --component uploader
```

产物写入 `_releases/`，附 SHA-256 和逐文件清单。
同一源码已通过对应测试时使用 `build --skip-tests`，保留 ZIP 与解压验证。完整流程见 [打包说明](_development/docs/portable-packaging.md)。

## 许可与来源

本项目新增/修改代码及组合 GUI 程序采用 **GPL-3.0-only**，见 [LICENSE](LICENSE)；上游 MIT 版权和许可原文保留，各依赖按各自许可授权。
第三方数据、图片和名称的权利归各自权利人，来源及版本记录见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
分发时的源码和许可交付要求见 [许可说明](_development/docs/licensing.md)。
