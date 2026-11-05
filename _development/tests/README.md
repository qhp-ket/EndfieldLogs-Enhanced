# 测试与验证

本分支的产品测试位于 `_internal/dotnet/Specs/`；命令行差分入口位于 `Tools/`，桌面专项检查位于 `Desktop/Verification/`。旧 Python／Qt 应用测试随其源码在 `main/python-qt` 分支维护。

```powershell
& _internal/dotnet/Verify.ps1
& _internal/dotnet/Verify.ps1 -Suite history-index,live-engine -Group history-storage,history-analysis,live-engine
python -B -m unittest discover -s _development/tests/resources -p "test_*.py"
```

`Verify.ps1` 按 NuGet 锁文件恢复，构建当前源码，并执行选中的契约组和固定差分。`-SkipBuild` 只接受当前源码与产物的有效构建回执；不要用旧回执跳过变化后的构建。`resources/` 是打包清单、资源缓存及基准身份工具的标准库单元测试，无需 PySide6 或 pytest。

无窗口导航检查可单独运行：

```powershell
dotnet _internal/dotnet/Desktop/bin/Debug/net10.0-windows10.0.19041.0/EndfieldLogs-Enhanced.dll --check-navigation _development/verification/navigation.json
```

便携包根目录的 EXE 支持 `--check-portable-layout <输出.json>`，验证相对目录、自包含运行库和原生依赖加载；此入口不打开窗口、采集画面或注册输入钩子。

`--check-product-startup <输出.json>` 从同一个产品初始化入口创建真实主窗口和服务组合，使用隔离配置检查导航、收起侧栏、深浅色、放大字号、配置保存及退出清理。窗口不激活、不接收输入；诊断明确关闭抓包、录制、浮窗、更新请求和全局快捷键，20 秒内结束。便携验收应从包根 EXE 执行，并核对结果中的进程、CoreCLR、WPF 和 Desktop 路径均位于包内。它不代替真实游戏、物理输入或 OBS 验收。

`--check-overlay-lifetime <输出.json>` 短时创建桌面透明、不激活且穿透输入的原生浮窗，检查全部停用时释放绘图工厂、重新启用时恢复快照，以及关闭后隐藏仍保留窗口。它不捕获画面、不注入输入，也不测量性能或内存达标情况；仅在允许启动窗口时运行。

`--probe-product`、`--probe-overlays` 及性能基准会创建实际窗口，部分还会捕获自有窗口；只在允许使用桌面时手动运行。它们不由普通 CI 执行。真实游戏、OBS、多屏 DPI、UAC、手柄和长期资源稳定性须另外验收，不能由无窗口测试替代。

`benchmark_dotnet_interface.py` 的配对页面窗口不激活、穿透输入并位于普通窗口底层，通过控件接口操作；不会测试真实键盘焦点。脚本在启动前拒绝没有输入保护的旧 Desktop 程序；集成主窗口及实时回放需使用各自的专用工具。历史列表按实际界面的最新记录在前排序，在计时后的独立检查中核对 20 个停靠点的 DPI、页面客户区、实际裁切视口、可见记录、行高、字体及双行文本；物理尺寸和字体只允许 1 像素舍入差异，不匹配时保留诊断并拒绝生成性能汇总。有界负载串行运行，避免与构建及其他测量并发；遮挡状态下的绘制结果不能直接作为可见更新性能结论。

配对输入可添加 `"history_display": {"viewport_dip": [720, 448], "row_min_height_dip": 64}`，在测试窗口中统一列表视口、最小行高及 1200×800 DIP 页面客户区；产品默认布局不变。自然行高超过所设下限时仍保留，并检查文字垂直裁切。布局设置在滚动计时之前完成，显示条件仍须通过上述实际检查；该模式的汇总不比较初次绑定耗时，原始绑定数据仅供诊断。

CI 在本分支 push、PR 及手动触发时运行 C# 契约／固定差分、无窗口导航、仓库审计和打包工具测试，并始终上传验证日志。官网实际上传不属于测试步骤。
