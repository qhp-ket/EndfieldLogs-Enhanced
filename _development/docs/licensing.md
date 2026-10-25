# 许可与再分发

## 代码许可

本项目新增/修改代码及包含 GPLv3 GUI 依赖的组合程序采用 **GPL-3.0-only**，根目录 `LICENSE` 为完整文本。
Copyright (c) 2026 EndfieldLogs contributors。

上游代码保留 MIT 授权及 `Copyright (c) 2026 Endfield Logs contributors`：
源码原文位于 `_development/portable/licenses/EndfieldLogs-MIT.txt`，便携包位于 `licenses/EndfieldLogs-MIT.txt`。
分发组合程序遵守 GPLv3，同时保留上游 MIT 声明。GPLv3 允许商业使用。

GUI 使用的 PySide6-Fluent-Widgets 1.11.3 标注 GPLv3，来源为 [PySide6 分支](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6)。
其他依赖按各自许可授权。

## 资源与发行交付

第三方资源的权利归各自权利人，来源及许可集中见根目录 `THIRD_PARTY_NOTICES.md`。
数据版本和哈希保存在 `resource-manifest.json` 及派生规则的来源字段中。

发行时提供适用许可要求的对应源码、构建和安装材料，保留版权、许可及修改说明；流程见 [打包说明](portable-packaging.md)。

## 参考

- [GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)：第 4–6 条分发要求、第 9 条版本选择。
- [GNU Expat/MIT 说明](https://www.gnu.org/licenses/license-list.html#Expat)：与 GPL 兼容。
- [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html)：对应源码的取得与交付。
