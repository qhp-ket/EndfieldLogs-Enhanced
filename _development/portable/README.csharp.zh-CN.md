# Endfield Logs - Enhanced · C#／WPF 候选包

适用于 Windows 10 2004 或更新版本的 x64 系统。完整解压到可写目录，双击 `EndfieldLogs-Enhanced.exe`。包内携带 .NET 和 WPF 运行时。

本包用于迁移验收；真实游戏、管理员录制、实物手柄、OBS、多显示器 DPI 和长期资源稳定性仍需验证。完整结果见源码仓库的迁移说明。

已知限制：独立浮窗私有内存仍超过 Qt 对照容差，WGC 反复重启后的句柄增长仍待外部环境隔离。历史列表已通过相同可见内容的处理耗时对照，这不等于物理屏幕呈现验收。WGC 合成窗口、持续识别和桌面隐藏后的浮窗捕获已验证，真实游戏及 OBS 表现仍待验收。使用候选包时请保留原版及原始日志。

## 开始使用

1. 安装 [Npcap](https://npcap.com/#download)，安装时勾选 **Install Npcap in WinPcap API-compatible Mode**。
2. 在设置中选择 `Endfield.exe` 或游戏目录，首页点「启动抓包」后再启动游戏。停止后重新抓包需要重开游戏。
3. 悬浮窗页添加伤害统计、连携 CD 或 UID 遮挡，分别设置字号、锁定、穿透和桌面显隐。拖动窗口调整位置，拖动边缘等比例缩放；宽高比自动随当前内容适配，设置页可重置布局。
4. 战斗日志页导入 trace 后加载分析；「返回实时」恢复当前实时统计。

伤害浮窗默认显示并按 rDMG 排序。连携识别独立于抓包，可在首页或浮窗页打开识别设置，预览并校准四槽区域；就绪时角色背景变绿。输入记录在首页启用后随伤害记录启停，设置中可调整输入解释规则。

战斗分析保留累计 rDMG 等曲线、角色合轨、BUFF、输入、技力、失衡和四栏证据详情。角色名称格的设置入口可调整轨道；自定义配置未分配的技能进入「其他」。

配置与日志位于 `.dev-gui/`。移动安装目录时完整保留此目录；向他人分发使用原始 ZIP。
隐藏主界面使用 `Ctrl+Shift+O`，切换浮窗使用 `Ctrl+O`，后台服务继续运行。

## 目录与界面

主界面沿用左侧导航：首页、悬浮窗、战斗日志、运行日志、设置。左上角按钮可收起／展开导航栏；主题和字号仍在设置中调整，支持深色模式。

```text
EndfieldLogs-Enhanced.exe   启动入口
README.zh-CN.md            使用说明
BUILD-MANIFEST.json        文件校验清单
_internal/
  app/                    本体及第三方托管程序集
  dotnet/
    host/fxr/<版本>/      .NET 启动组件
    shared/
      Microsoft.NETCore.App/<版本>/         .NET 基础运行库
      Microsoft.WindowsDesktop.App/<版本>/  WPF／桌面框架及其语言资源
  native/
    input/                SDL3 输入组件
    webp/                 WebP 解码组件及 VC 运行库
  data/、jsondata/         解析与界面资源
  secrets/                批准的运行资源
  source/SOURCE.zip       对应源码
licenses/                 许可与第三方声明
```

请完整移动或解压整个目录，不要单独复制 EXE；无需安装 .NET 运行时。

## 官网兼容与来源

GUI 启动默认未记录。首页「伤害日志」中启动抓包后，用「开始／停止记录」或默认快捷键 `Ctrl+I` 控制保存；自动抓包不会自动记录。每次开始创建独立的 session、trace 文件组，停止会写完缓冲、刷新并关闭文件，抓包与实时分析继续运行。伤害浮窗常驻显示红点／灰点及「记录中／未记录」文字。

输入记录作为启用选项，随伤害记录同步启停，保存为同一日期目录中的配套 `trace_*.input.jsonl`。设置中可修改快捷键，进入输入框会显示录入提示。

新录制默认使用 JSONL，实时分析、历史分析及连续分卷直接消费结构化事件。配置中的显式 `service.trace_format: "legacy"` 继续有效，旧日志仍可读取。在战斗日志页选中一场，通过「导出官网兼容日志…」生成旧格式日志；多选时仅导出最后选中的那场，保留完整证据及必要上下文，不混入其他场次。不直接把 JSONL 交给官网 uploader。

保留原始 trace 及其配套状态文件，通过独立的官网 uploader 解析和上传；JSONL 分卷须一起保留。输入记录供本地分析使用。

源码仓库：[qhp-ket/EndfieldLogs-Enhanced](https://github.com/qhp-ket/EndfieldLogs-Enhanced)。
`_internal/source/SOURCE.zip` 提供本包对应的 C# 源码和构建说明；`BUILD-MANIFEST.json` 记录来源状态、依赖、资源及逐文件 SHA-256。
许可与第三方声明见 `licenses/`。
