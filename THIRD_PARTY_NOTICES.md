# 来源、署名与外部资源

本开发版基于 ZMDLogs / Endfield Logs 的客户端和核心解析代码修改。
保留上游 `Copyright (c) 2026 Endfield Logs contributors` 及 MIT 许可文本。

上游项目：

- ZMDLogs：<https://github.com/deepdarkssj/ZMDLogs>
- Endfield Logs 公开源码套件：<https://github.com/medps16000/endfield-suite-open>
- ZMDLogs 完整发行包：<https://zmdlogs.com/>

开发版修改由本项目贡献者维护。代码许可见根目录 `LICENSE`；上游 MIT 原文副本保留在
`_development/portable/licenses/EndfieldLogs-MIT.txt`，便于打包时带上原有声明。
建议下游注明基于本开发版修改及修改范围；这是一项署名建议，不改变 MIT 的授权条件。

## 游戏数据与界面素材

运行需要 `_internal/data/`、`_internal/jsondata/` 等外部资源。源码仓库保留提取后的运行数据包、
校验清单、开发版覆盖规则及来源说明；普通开发从该数据包离线恢复。
完整上游原件仅用于本地维护提取规则，由固定发行 ZIP 校验恢复，不提交源码仓库。
本项目的 MIT 不代替这些资源自身的许可，不宣称拥有游戏素材的权利。

`_development/portable/licenses/Upstream-THIRD_PARTY_NOTICES.md` 是上游声明的原文副本，
其中关于其公开源码树不含游戏资源的描述针对上游。便携构建同时附带本说明和上游声明。

游戏名称、角色、图像及商标属于各自权利人。AKEData 等外部数据库按各自来源和条款处理，
资源范围及维护见 `_internal/data/README.md`。

## Python、Qt 及其他依赖

Python、PySide6 / Qt、Fluent Widgets、WebEngine 和其他依赖保持各自的许可。
它们安装在本地忽略目录，便携包保留分发文件及其许可；根目录 MIT 不重新许可这些依赖。

## 抓包密钥与独立 uploader

抓包密钥和官网 uploader 来自完整官网发行包，均不提交本源码仓库。
其来源和准备方法见 `_development/docs/runtime-resources.md`。
密钥的公开分发状态不等同于本项目拥有它的版权或对所有私钥的分发授权。
