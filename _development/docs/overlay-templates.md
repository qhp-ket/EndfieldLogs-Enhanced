# 悬浮窗配置与自定义模板

GUI 使用 Windows 设置风格（Fluent 主窗口、导航、卡片及主题）。模板配置只改变悬浮窗及其配置控件的内容。

## 通用窗口控制

| GUI 控件 | 作用 |
| --- | --- |
| 一键配置中的显隐按钮、全局快捷键 | 有浮窗显示时，只隐藏这些项并记住 ID；没有显示时，恢复记录并清空记录；没有记录则取消全部项的隐藏。始终不改变分析启用状态。 |
| 启用全部、停用全部 | 批量改变每项 `enabled`，不改变单项 `hidden`。已隐藏项启用分析后仍隐藏。 |
| 单窗启用 | 修改该项 `enabled` 并保存。按已启用模板的订阅启停分析；停用时关闭窗口，禁用「显示浮窗」控件并保留其选择。 |
| 显示浮窗、浮窗右上角 × | 开启时 `hidden=false`；关闭时只隐藏桌面画面，保留同一窗口继续绘制、分析和 Windows 10 捕获。隐藏时鼠标自动穿透。× 会关闭「显示浮窗」。与单项启用同排。 |
| 锁定位置 | 禁止鼠标拖动和边缘调整；GUI 输入尺寸仍可用，关闭键仍可用。 |
| 鼠标穿透 | 整个浮窗不接收鼠标；关闭键也隐藏。可通过 GUI 或总快捷键关闭。 |
| 透明度 | 调整整个浮窗的透明度，包括文字。 |
| 窗口尺寸 | 输入宽、高（Qt 逻辑像素）；拖动边缘会更新数值及保存配置，受模板最小尺寸限制。通常窗口比例 = min(当前宽/参考宽, 当前高/参考高)。连携进度条只按高度缩放，宽度独立拉伸。伤害窗与连携窗按当前内容测量参考尺寸。 |
| 位置旁的「重置布局」 | 恢复模板默认位置、100% 字体和窗口比例，伤害窗按当前列及内容取自然尺寸，不改变其他配置。 |
| 字体大小 | 百分比滑条，范围 50%–300%；100% 为窗口自动适配后的字号。该滑条作为文字的独立乘区，不改变头像比例；伤害窗同步调整尺寸以容纳内容。UID 遮挡本身没有文字。GUI 整体字号在设置页另行调整。 |
| 头像大小 | 伤害模板独立的百分比滑条，范围 50%–300%，默认 100%。直径 = 32px × 窗口比例 × 头像比例，行高和窗口尺寸随内容调整；不改变文字比例。 |
| 渲染入口 | 内置模板名、本地模板/HTML 路径或 URL；不是战斗数据源。URL 可以直接编辑。 |

窗口存在条件是 `enabled`，桌面显示条件是 `enabled && !hidden`。隐藏使用桌面透明度零，不销毁窗口或停止绘制；恢复时使用原透明度、位置和尺寸。`overlay_restore_ids` 保存按钮待恢复的集合；删除的 ID 会被清理，恢复时只恢复当前启用项的可见性。手动显示某项后再按按钮，以当前显示集合替换待恢复记录。URL/本地模板入口位于最上方；随后是一键配置，集中启用全部、停用全部及显隐按钮。单项配置依次为启用/显示浮窗同排、名称、模板专属选项、尺寸、字体、位置、透明度、锁定位置/鼠标穿透同排、来源信息。同排的两组选项之间留出独立间距，标签靠近自己的控件。专属选项始终留在对应浮窗的配置内。窄窗口将浮窗列表放在表单上方，宽窗口保留可拖动的左右分栏。

启用项的订阅取并集：多个浮窗共用同一分析时，停用其中一个不会中断其他浮窗。独立 WS 客户端仍是有效消费者：`/ws?analysis=summary` 需要摘要，`/ws` 需要完整分析；两个接口继续包含 BUFF 状态。没有消费者的分析停止计算与刷新，抓包、解密、trace 落盘继续。重新启用时按保留的有序输入补算；BUFF 回放使用原接收时钟，避免从补算时刻重新倒计时。关闭期间较长时，首次补算可能需要等待。UID 遮挡不需要分析；无订阅网页自己的取数逻辑仍由网页决定。连携 CD 的 `combo_snapshot` 由独立视觉服务产生，不依赖抓包服务。输入进程负责录制与状态计数。

悬浮窗列表支持拖拽排序，顺序自动保存；排序不改变启用、显隐、分析订阅或现有窗口。

宿主固定网页 zoom=1，再独立乘上窗口比例和字号或头像滑条。调整尺寸不改写滑条数值，移回原尺寸会恢复，DPI 不额外重复相乘。无默认尺寸声明的普通网页使用宿主默认尺寸作为参考；普通网页的像素字号由宿主按相同比例缩放，图片应在模板样式中消费窗口比例。窗口太小、单独放大字号或头像时内容仍可能放不下。

伤害模板的 `layout.js` 用默认头像、四字角色名、`100.00M`、`100.0%` 及各列表头建立列宽下限，超出下限的内容才额外加宽；表头与数据行共用固定内容宽度，不分摊剩余空间。列宽按 8px 档位取整。团队数据和计时也计入窗口最小所需宽度，列数改变时立即重算。高度按实际行数、字号和头像测量，底栏紧跟最后一行；普通数值更新复用未变化的布局，不重建头像节点。

`overlays/content_size.py` 通过内置伤害页和连携页专用的 Qt WebChannel 接收自然尺寸，保持用户窗口缩放比例并调整原生宽高，同时更新 GUI 尺寸及保存值；自动变宽、变窄时保持右边缘位置，最大尺寸限制在当前屏幕可用区域，容不下时表格内部滚动。`template_settings._damage_window_scale` / `_combo_window_scale` 是内部持久化的窗口比例，不生成表单控件，避免关闭重开时把字体滑条或自动加宽再次算作窗口缩放。手动调整宽高会重新确定该比例；仅列数、内容或独立滑条变化时沿用它。连携样式切换重取自然尺寸；进度条同一样式内保留用户宽度，高度决定窗口比例。其他 Overlay 不使用这一适配逻辑。

跨屏拖动保持拖动开始时的逻辑宽高，DPI 切换过程中的临时尺寸不会保存或用于下一次移动。不同系统缩放下实际像素数仍随屏幕变化，移回原屏后恢复。可输入期望尺寸，或点击「重置布局」恢复模板默认尺寸、位置和字体。

## 模板、样式与数据的职责

- **Qt 宿主**管理启用、关闭、锁定、穿透、透明度、位置、尺寸和字体比例。
- **模板 JSON**声明 HTML 入口、数据订阅、默认/最小尺寸和可选外观设置。GUI 按声明动态生成下拉框、多选框和百分比滑条，包括伤害窗的显示列选项。
- **HTML/CSS/JS**负责布局、装饰、颜色、字号层级、格式化和渲染。JSON 声明一个设置后，模板 JS 也必须消费该设置才能产生视觉效果。
- **数据发布层**提供轻量 canonical `analysis_summary`、完整 `analysis_snapshot` 或独立展示用的 `buff_snapshot`。模板替换当前状态，不累计 raw 事件，不重新实现伤害或 rDPS 算法。

内置伤害模板：`_internal/src/endfield_pcap/overlays/assets/damage/template.json`。伤害条/排序、显示列、背景模式与头像开关及比例由模板声明；`avatar_size_percent.default` 设置默认百分比，`style.css` 的 `--character-avatar-size` 设置基准直径。HTML、CSS 和 JS 决定具体显示效果。连携 CD 提供四圆图标/四行进度条，消费视觉 schema 2。设置及证据边界见 [独立服务](independent-services.md)。

浅色和深色继续保留终末地黄黑装饰。透明背景只移除 Overlay 背景装饰，不使 GUI 透明。

## 导入自定义模板

点「选择本地模板 / HTML」，可选择示例 `_development/examples/overlay-template/template.json`。也可选 HTML：先寻找同名 `xxx.template.json`，再寻找同目录 `template.json`；有声明时按其中 `entry` 打开。没有声明的普通 HTML 自行获取数据。

最小声明示例：

```json
{
  "schema_version": 1,
  "name": "我的浮窗",
  "entry": "index.html",
  "subscriptions": ["analysis_snapshot"],
  "font_mode": "css",
  "window": {"min_width": 240, "min_height": 120, "default_width": 400, "default_height": 200},
  "settings": [
    {
      "key": "accent", "label": "强调色", "type": "select", "default": "red",
      "options": [{"value": "red", "label": "红"}, {"value": "blue", "label": "蓝"}]
    }
  ]
}
```

`entry` 相对 JSON 所在目录；当前 GUI 可用 `subscriptions` 为 `analysis_summary` / `analysis_snapshot` / `combo_snapshot`，无数据需求可用空数组。`settings.type` 支持 `select`、`multiselect` 和 `slider`：多选的 `default` 为字符串数组；百分比滑条声明整数 `min`、`max`、`default`，如 `{"key":"avatar_size_percent","type":"slider","min":50,"max":300,"default":100}`，不需要 `options`。每个实例的选择独立保存在 `template_settings`，不改写模板 JSON。模板设置与通用设置位于同一个表单，标签和控件共用列宽。

本地带声明模板使用进程内桥：

```js
window.addEventListener("endfield-overlay-config", event => {
  const {settings, fontScale, referenceSize} = event.detail;
  // --overlay-font-scale = 窗口比例 × 字号比例；--overlay-window-scale 仅为窗口比例。
  // 消费模板设置并刷新显示。
});
window.addEventListener("endfield-analysis-snapshot", event => {
  state = event.detail; // 整份消息替换，snapshot 可能为 null
  render(state.snapshot);
});
// 延迟安装的监听器可读当前缓存：
// window.endfieldOverlay.config
// window.endfieldOverlay.snapshots.analysis_snapshot
```

订阅伤害的本地模板与内置伤害窗一起切换历史/实时，关闭后重开、页面重新加载都会补发当前完整状态。URL 与没有声明的 HTML 不接收进程内战斗快照，需要网页自己连接 `ws://127.0.0.1:<wsPort>/ws`，消费版本化完整状态；WebSocket 始终保持实时，保留 raw `event_batch` 供诊断。

浏览器 WS 连接还需与服务配置一致的 `access_token`；不要将凭据提交到仓库。
WS 模式的本地模板可从 URL 的 `wsToken` 参数取得凭据并转发为 WS 查询参数 `access_token`，
内置伤害模板支持此方式。进程内模式不需要凭据；宿主不会把凭据自动附给远程 URL 模板。
独立浮窗附着已有服务时，须使用与该服务匹配的配置凭据。未经授权的外站与 `Origin: null` 页面均被拒绝。

OBS 使用「窗口采集」，捕获方式选择 Windows 10（Windows Graphics Capture），按浮窗名称选中 GUI 使用的同一个窗口。无需浏览器来源或额外端口。设置中的 WebSocket 端口继续供实时数据客户端使用。

浮窗使用普通无边框置顶 Qt 窗口，不抢焦点。隐藏时窗口保持原 HWND、位置、尺寸和绘制，桌面透明度为零，Windows 10 捕获仍接收新画面；恢复时还原用户透明度和穿透设置。隐藏捕获使用 Windows Graphics Capture；BitBlt/GDI 不在验证范围内。关闭「启用」会真正关闭窗口，停止 GUI 也会结束窗口捕获。

## UID 遮挡与通用交互

`uid_mask/template.json` 为本地黑色遮挡，无需抓包或 WebSocket。可选矩形/圆角，通用宽高、位置、透明度、锁定及穿透有效。首次默认 220×32，位于主屏完整屏幕左下角；已有保存位置继续使用，可拖到实际游戏 UID 位置。要完全遮挡请使用 100% 透明度和矩形，调整后开启穿透。没有实现对游戏画面的真正模糊。

关闭键为右上角淡色 ×，悬停时显示红色底高亮；点击后同步关闭 GUI「显示浮窗」，鼠标穿透时关闭键隐藏。

`font_mode: "css"` 的模板应使用 `html {font-size:calc(16px * var(--overlay-font-scale,1))}`，所有文字用 `rem`，避免 `vw` 字号或整体 transform。内置数据模板遵循这一约定。未声明 css 模式的普通页面由宿主按 DOM 的原始 computed 字号缩放，包括后续添加的 DOM 文本，重复设置不会累乘；Canvas、图片中的文字及 iframe 内部由网页自身负责。鼠标穿透与拖动由 Qt 管理，网页交互由模板实现。
