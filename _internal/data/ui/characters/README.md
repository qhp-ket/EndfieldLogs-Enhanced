# 圆形角色头像

来自 [AKEData 数据站](https://data.akedata.wiki/) 的 `charroundicon` 图片，
路径规则核对自 [AKEDatabase 图标生成器](https://github.com/NagiYume/AKEDatabase/blob/main/plugin/js/misc-character-icon-generator.js)。
游戏图片素材权利归原权利人，项目代码许可不重新授权这些图片。

`manifest.json` 按角色 ID 记录图片路径、原始来源和 MD5/SHA-256、生成图片 SHA-256。
男女管理员按不同 ID 保留；如新增流派使用不同 ID，仅在 `aliases` 中添加明确的角色对应关系，不按名称猜测。
现有名称表的通用管理员 `chr_9000_endmin` 不指明性别，使用占位图；不擅自映射到男或女管理员。
`placeholder.png` 为本项目绘制的中性人像；公共状态、敌人及非角色实体不显示干员头像。

所有头像为至多 128×128 的透明 PNG，GUI 与网页共用，不需要联网。
重建：`python -B _development/tools/build_character_avatars.py`。
大图及索引缓存位于被忽略的 `_development/cache/character-avatars/`，不随发行包分发。
