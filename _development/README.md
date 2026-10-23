# 开发指南

- [环境准备](docs/development-environment.md)：零环境、部分环境、完整环境的复用与安装。
- [外部资源](docs/runtime-resources.md)：运行数据、抓包密钥、官网 uploader 与上传兼容。
- [GUI 启动](docs/gui-launch.md)、[浮窗模板](docs/overlay-templates.md)。
- [本地战斗分析](docs/local-battle-analysis.md)、[trace 导入与贡献口径](docs/trace-import-and-rdps.md)。
- [界面组件位置](docs/battle-analysis-components.md)：控件、字号、时间轴和网页资产。
- [实时摘要接口](docs/live-summary-publisher.md)、[质量契约](docs/snapshot-quality-contract.md)。
- [版本与打包](docs/portable-packaging.md)。

`tests/` 为应用回归，核心回归位于 `_internal/packages/*/tests/`。
`tools/` 只入库当前维护工具；下载、缓存、性能实验、历史实施记录与验证产物留在本地。

```powershell
python -B _development/run_tests.py live
python -B _development/run_tests.py parser_core
python -B _development/run_tests.py uploader_core
```

普通回归使用合成数据。依赖真实官网密钥的测试单独执行 `capture-key`；
缺少官网源码副本的可选兼容检查明确跳过。测试不会登录、上传或抓包。
