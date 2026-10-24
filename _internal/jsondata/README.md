# GUI 辅助表

`CharacterNameIndex.json`、`ActorImageTable.json`、`Dungeon.json` 分别提供旧角色名称索引、
头像对应关系和关卡辅助映射。当前角色名称还会合并 data 中的角色 manifest。

这些文件属于精简运行数据的一部分，由源码附带的 `data/runtime-data.zip` 离线恢复，
大小与哈希记录在 `data/resource-manifest.json`。完整原件只留本地原始数据目录。
直接来源是清单固定的 ZMDLogs 3.0.12（2026-10-16）发行包。
它们不是个人配置；名称、路径与外部资源的维护边界见 [data 说明](../data/README.md)。
