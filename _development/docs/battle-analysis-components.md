# 战斗分析组件位置

界面读取共享 canonical 结果。以下路径相对 `_internal/src/endfield_pcap/`。

## 原生 Qt

| 组件 | 文件 | 修改入口 |
| --- | --- | --- |
| 窗口、顶部数据与筛选 | `gui/battle/detail.py` | `BattleDetailDialog.__init__()` |
| 显式设置与输入流程连接 | `gui/battle/presenter.py` | `BattleDetailPresenter.create()`；传入快照、记录、设置所有者及窗口 parent |
| 设置保存 | `application/settings.py`、`settings/` | `SettingsStore`、显示设置投影、配置兼容与原子存储 |
| 输入绑定、请求与晚到结果失效 | `application/input_evidence.py` | `InputEvidenceController`；独立结果队列，所属线程提交 |
| 输入编辑控件 | `gui/battle/input_history.py` | `InputHistoryBar` 的具体操作信号及显示状态 |
| 时间轴及技能构成页面 | `gui/battle/pages.py` | `TimelinePage`、`SkillCompositionPage`；控件与表格刷新归页面所有 |
| 换行工具栏、显示与输入弹出面板 | `gui/battle/controls.py` | `WrapLayout`、`popup()` |
| 按需角色统计与完整质量字段 | `gui/battle/summary.py` | `BattleSummaryDialog` |
| 表格排序、便携列宽与行样式 | `gui/battle/tables.py` | `EvidenceItem`、`remember_columns(dialog, view, initial_widths, submit)`；拖动防抖及关闭提交 |
| 详情拖动、收起、最大化 | `gui/battle/panel.py` | `BattleDetailSplitter`、`_normal_sizes` |
| 视口、缩放、鼠标与刷新协调 | `gui/battle/timeline/view.py` | `BattleTimeline`、`timeHovered` |
| 角色轨道布局、技能块与证据标记 | `gui/battle/timeline/layout.py`、`items.py` | `layout_role_tracks()`、`draw_block_items()` |
| 标签、头像、列宽 | `gui/battle/timeline/labels.py` | `draw_sticky_labels()`、`fit_label_columns()` |
| 角色轨道配置 | `gui/battle/lane_settings.py`、`analysis/battle/lane_config.py` | `BattleTimeline.role_lane_options()` 提供编辑数据，齿轮入口、归组与“其他”兜底；按角色提交 `battle_lane_configs` |
| 详情栏目与角落按钮 | `gui/battle/inspector.py` | `BlockInspector`、`_PanelSizeIcon` |
| 伤害 / 技力 / 失衡曲线 | `gui/battle/plots/damage.py`、`energy.py`、`poise.py` | 绘制与悬浮查询；`gui/battle/style.py` 共用配色与线宽 |
| 通用字体 | `gui/shared/typography.py` | `apply_fonts()` |
| 头像解析 / Qt 缓存 | `data/avatars.py`、`gui/shared/avatars.py` | 角色 ID、版本、尺寸和 DPI |

基础字号位于 `labels.py`：`ROLE_LABEL_PIXELS=17`、`SKILL_TYPE_LABEL_PIXELS=16`、`BASE_LABEL_PIXELS=13`。
头像比例和基准尺寸见 [本地分析](local-battle-analysis.md)。

详情收起时 splitter 第二面板高度为 0，保留拖动入口；用 `details_expanded()` / `details_maximized()` 查询状态。
顶部按钮、分隔线及角落按钮统一读取 splitter 状态。

`fit_label_columns()` 在打开战斗、改变字体或头像时测量左侧文字/头像列，普通重绘保留手动列宽。
技能构成表随字体和头像变化重测姓名、分类列。

原生伤害曲线支持累计 DMG、DPS、rDMG、rDPS，在“显示设置”切换。按一秒分桶，DPS 为累计伤害除以桶终点秒数，末桶使用实际战斗时长。rD 曲线仅汇总已有逐击分配，并标明缺失证据。筛选、缩放和曲线均以战斗时间范围为界。

## 数据投影

| 文件 | 职责 |
| --- | --- |
| `analysis/battle/detail.py` | 时间轴块、贡献概况、技能构成 |
| `data/skill_names.py` | 角色/技能名称 |
| `analysis/battle/buffs/labels.py` | BUFF 名称与来源回退 |
| `data/skill_frames.py` | 固定时长回退，默认关闭 |
| `_internal/packages/parser_core/`（相对仓库根） | 解析、贡献与质量核心 |

测试入口为 `app-battle`，主要用例：`test_timeline_intervals_and_details.py`、`test_battle_analysis_compact.py`、`test_native_damage_and_style.py`、`test_detail_presenter.py`。输入证据的请求失效与绑定测试在 `app-independent`。
