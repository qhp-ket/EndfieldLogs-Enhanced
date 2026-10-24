# 战斗分析界面组件位置

更新：2026-10-24。两种界面共用本地 canonical 分析结果；下列界面文件不负责修改 rDPS 数学。

## 原生 Qt 界面

| 组件 | 文件（相对仓库根目录） | 常用修改入口 |
| --- | --- | --- |
| 战斗分析窗口、界面风格、顶部数据与筛选项 | `_internal/src/endfield_pcap/gui/battle/detail.py` | `BattleDetailDialog.__init__()`；默认复选框状态、工具栏顺序、标签文字 |
| 详情栏拖动、收起、最大化和还原状态 | `_internal/src/endfield_pcap/gui/battle/panel.py` | `BattleDetailSplitter`；`_normal_sizes` 为初始展开比例 |
| 时间轴、技能块、实际伤害点和鼠标事件 | `_internal/src/endfield_pcap/gui/battle/timeline/view.py` | `BattleTimeline`；`timeHovered` 输出悬浮时间与资源提示 |
| 角色名、技能类型、BUFF 标签、列宽与边框 | `_internal/src/endfield_pcap/gui/battle/timeline/labels.py` | `draw_sticky_labels()`；`ROLE_LABEL_PIXELS=17`、`SKILL_TYPE_LABEL_PIXELS=16`、`BASE_LABEL_PIXELS=13` |
| 事件概况、贡献分配、逐击证据、原始证据、详情右上角按钮 | `_internal/src/endfield_pcap/gui/battle/inspector.py` | `BlockInspector`；`_PanelSizeIcon` 绘制最大化/还原框 |
| 技力曲线 | `_internal/src/endfield_pcap/gui/battle/plots/energy.py` | 曲线绘制与悬浮信息 |
| 敌方失衡曲线 | `_internal/src/endfield_pcap/gui/battle/plots/poise.py` | 曲线绘制与悬浮信息 |
| GUI 通用字体缩放 | `_internal/src/endfield_pcap/gui/shared/typography.py` | `apply_fonts()`；影响范围大于本窗口 |

本次仅提高角色名与技能类型的基础字号。BUFF 名称、层数、持续时间、轴刻度保持原基础字号；它们仍服从已有的全局字体/图形缩放设置。

详情处于收起状态时，第二个 splitter 面板高度为 0，并未 `hide()`，这样仍可拖动分隔线重新打开。检查状态请用 `details_expanded()` / `details_maximized()`，不要用 `isHidden()`。顶部按钮、拖动、详情角落按钮统一通过 splitter 状态同步。

## 仿官网本地界面

文件位于 `_internal/src/endfield_pcap/gui/battle/assets/`：

| 文件 | 内容 |
| --- | --- |
| `index.html` | 页面结构、工具栏、详情按钮、右上角时间显示 |
| `analysis.css` | 颜色、间距、字号、详情面板最大化布局；`.character-name` 与 `.track-cell.expand` 为此次放大的文字 |
| `shared.js` | 默认状态、时间格式、通用提示与格式化 |
| `app.js` | 栏目切换、筛选、`syncDetails()`、详情展开/收起/最大化同步 |
| `timeline.js` | 时间轴行、技能块、BUFF、列宽拖动、右上角鼠标时间 |
| `details.js` | 详情栏目和证据展示、技能构成、敌方数据表 |
| `charts.js` | 技力、失衡、伤害曲线与悬浮提示 |

宿主与 Python 通信位于 `_internal/src/endfield_pcap/gui/battle/web.py`。首次切换时创建 WebEngine，后续复用。切换两种界面不重新解析日志，保留角色、单位、缩放、详情状态等。

## 数据与名称来源

| 文件 | 职责 |
| --- | --- |
| `_internal/src/endfield_pcap/analysis/battle/detail.py` | canonical snapshot 转为时间轴技能/BUFF 块、贡献概况与技能构成 |
| `_internal/src/endfield_pcap/analysis/battle/web_data.py` | Web 界面数据投影、按需证据与悬浮查询 |
| `_internal/src/endfield_pcap/data/skill_names.py` | 角色/技能实际名称 |
| `_internal/src/endfield_pcap/analysis/battle/buffs/labels.py` | BUFF 实名与来源回退 |
| `_internal/src/endfield_pcap/data/skill_frames.py` | 缺失起止时的固定时长回退；默认关闭 |
| `_internal/packages/parser_core/parser_core/` | 解析、贡献计算与质量证据核心；与外观修改分开 |

相关验证：`_development/tests/battle/test_timeline_intervals_and_details.py`、`test_battle_analysis_compact.py`、`test_battle_web_analysis.py`。截图保存在忽略目录 `_development/verification/`，使用合成战斗数据。
