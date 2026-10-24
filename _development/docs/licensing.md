# 许可与再分发

## 本开发版代码

本开发版的新增和修改代码，以及包含 GPLv3 GUI 依赖的组合程序，采用 **GPL-3.0-only**。
根目录 `LICENSE` 为 GNU GPL 第 3 版全文，不是附加的非商业许可证。
Copyright (c) 2026 EndfieldLogs contributors。

上游 Endfield Logs 代码继续保留 MIT 授权及版权：
Copyright (c) 2026 Endfield Logs contributors。
原文保存在源码的 `_development/portable/licenses/EndfieldLogs-MIT.txt`；便携包中位于 `licenses/EndfieldLogs-MIT.txt`。
MIT 原始部分可以继续按 MIT 使用；组合程序及本开发版修改按 GPLv3 的分发要求处理。
这不会撤销已发布版本已授予的 MIT 权利。

实际依赖 PySide6-Fluent-Widgets 1.11.3 的安装元数据标注 GPLv3，源码入口为
[PyQt-Fluent-Widgets 的 PySide6 分支](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6)。
其他依赖继续采用各自的许可；根目录 GPLv3 不把第三方依赖重新许可。

本项目选择 GPLv3 仍允许商业使用，不额外增加禁止商用或强制产品界面署名条款。

## 源码仓库的资源说明

仓库资源的来源和许可集中记录在 `THIRD_PARTY_NOTICES.md`；
数据版本与哈希由 `_internal/data/resource-manifest.json` 及派生规则中的来源字段记录。
有明确许可的保留许可与版权声明；未附明确许可的数据只说明来源，不声称由 GPLv3 重新授权。

## 参考原文

- [GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)：第 4–6 条分发要求、第 9 条版本选择。
- [GNU 许可证列表中的 Expat/MIT](https://www.gnu.org/licenses/license-list.html#Expat)：与 GPL 兼容。
- [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html)：对应源码的取得与交付。

具体来源见根目录 `THIRD_PARTY_NOTICES.md`；发行包交付要求见源码中的 `_development/docs/portable-packaging.md`。
