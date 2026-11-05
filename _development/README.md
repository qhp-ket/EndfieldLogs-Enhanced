# C# 开发指南

本目录维护 C#／WPF 客户端的构建、资源与验证工具。Python／Qt 产品源码在 `main/python-qt` 分支维护，不在本分支保留副本。

- [开发环境](docs/development-environment.md)：SDK、资源及启动命令。
- [架构与验证范围](docs/csharp-migration.md)：各模块职责、差分基准及尚未完成的实机验收。
- [运行资源](docs/runtime-resources.md)、[原生皮肤](docs/overlay-templates.md)。
- [JSONL 协议](docs/trace-jsonl.md)、[简报质量契约](docs/snapshot-quality-contract.md)。
- [打包](docs/portable-packaging.md)、[许可](docs/licensing.md)、[测试](tests/README.md)。

`_internal/dotnet/Specs/` 保存 C# 契约测试和固定差分夹具；`tools/dotnet_reference/` 用于从显式指定、哈希校验的 Python 参考生成差分输入。它们是开发工具，不随本体运行，也不要求在本分支安装 Qt。

验证结果、性能记录、临时程序、缓存和候选包不入库。不要用旧测量结果代表已经变化的源码。
