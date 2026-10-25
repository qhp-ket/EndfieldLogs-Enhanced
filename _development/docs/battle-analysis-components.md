# 战斗分析组件位置

界面读取共享 canonical 结果。以下路径相对 `_internal/src/endfield_pcap/`。

## 原生 Qt

| 组件 | 文件 | 修改入口 |
| --- | --- | --- |
| 窗口、风格、顶部数据与筛选 | `gui/battle/detail.py` | `BattleDetailDialog.__init__()` |
| 详情拖动、收起、最大化 | `gui/battle/panel.py` | `BattleDetailSplitter`、`_normal_sizes` |
| 时间轴、技能块、命中、鼠标 | `gui/battle/timeline/view.py` | `BattleTimeline`、`timeHovered` |
| 标签、头像、列宽 | `gui/battle/timeline/labels.py` | `draw_sticky_labels()`、`fit_label_columns()` |
| 详情栏目与角落按钮 | `gui/battle/inspector.py` | `BlockInspector`、`_PanelSizeIcon` |
| 技力 / 失衡曲线 | `gui/battle/plots/energy.py`、`poise.py` | 绘制与悬浮查询 |
| 通用字体 | `gui/shared/typography.py` | `apply_fonts()` |
| 头像解析 / Qt 缓存 | `data/avatars.py`、`gui/shared/avatars.py` | 角色 ID、版本、尺寸和 DPI |

基础字号位于 `labels.py`：`ROLE_LABEL_PIXELS=17`、`SKILL_TYPE_LABEL_PIXELS=16`、`BASE_LABEL_PIXELS=13`。
头像比例和基准尺寸见 [本地分析](local-battle-analysis.md)。

详情收起时 splitter 第二面板高度为 0，保留拖动入口；用 `details_expanded()` / `details_maximized()` 查询状态。
顶部按钮、分隔线及角落按钮统一读取 splitter 状态。

`fit_label_columns()` 在打开战斗、改变字体或头像时测量左侧文字/头像列，普通重绘保留手动列宽。
技能构成表随字体和头像变化重测姓名、分类列。

## 本地网页

资源位于 `gui/battle/assets/`：

| 文件 | 职责 |
| --- | --- |
| `index.html` | 结构、工具栏、详情按钮和时间显示 |
| `analysis.css` | 颜色、间距、字号、最大化布局 |
| `shared.js` | 状态、时间格式及通用提示 |
| `app.js` | 栏目、筛选、`syncDetails()` |
| `timeline.js` | 时间轴、技能/BUFF、列宽和鼠标时间 |
| `details.js` | 事件、贡献证据、技能构成、敌方数据 |
| `charts.js` | 技力、失衡及伤害曲线 |

`gui/battle/web.py` 提供宿主桥，首次切换创建 WebEngine，后续复用报告和界面状态。

## 数据投影

| 文件 | 职责 |
| --- | --- |
| `analysis/battle/detail.py` | 时间轴块、贡献概况、技能构成 |
| `analysis/battle/web_data.py` | 网页投影及按需证据 |
| `data/skill_names.py` | 角色/技能名称 |
| `analysis/battle/buffs/labels.py` | BUFF 名称与来源回退 |
| `data/skill_frames.py` | 固定时长回退，默认关闭 |
| `_internal/packages/parser_core/`（相对仓库根） | 解析、贡献与质量核心 |

测试入口为 `app-battle`，主要用例：`test_timeline_intervals_and_details.py`、`test_battle_analysis_compact.py`、`test_battle_web_analysis.py`。
