# 悬浮窗与模板

## 窗口控制

悬浮窗列表支持拖拽排序，顺序保存在便携配置中。每项模板选项与通用窗口选项放在同一表单。

| 控件 | 行为 |
| --- | --- |
| 启用 | 保存 `enabled`，按模板订阅启动功能；停用时关闭窗口 |
| 显示浮窗 / 右上角 × | 保存 `hidden`，控制桌面可见性；隐藏期间继续绘制和分析 |
| 一键显隐 / 快捷键 | 隐藏当前显示项并记录 ID；再次点击恢复记录。没有记录且全部隐藏时显示全部已启用项 |
| 启用全部 / 停用全部 | 批量设置 `enabled`，保留各项显隐选择 |
| 锁定位置 | 锁定拖动与边缘缩放；仍可在 GUI 修改几何尺寸 |
| 鼠标穿透 | 整窗穿透并隐藏关闭键；通过 GUI 或快捷键恢复 |
| 透明度 | 同时调整背景和文字透明度 |
| 重置布局 | 恢复默认位置、100% 字体及窗口比例；伤害窗按当前内容测量尺寸 |

窗口存在条件为 `enabled`，桌面显示条件为 `enabled && !hidden`。
`overlay_restore_ids` 保存一键显隐的待恢复集合；手动显示后，下次隐藏以当前显示集合替换记录。

启用项的订阅取并集，多个窗口共用一次分析。无消费者时释放相应计算；恢复订阅后按有序输入补算。
UID 为本地遮挡，连携由独立视觉服务提供 `combo_snapshot`。WS 消费者也计入订阅，接口见 [实时摘要](live-summary-publisher.md)。

## 尺寸、字体与头像

宽高使用 Qt 逻辑像素，拖动边缘后自动保存。网页 zoom 固定为 1，显示比例分开计算：

- 窗口比例：通常取 `min(宽 / 参考宽, 高 / 参考高)`；连携进度条只取高度比例，宽度独立拉伸。
- 字体：窗口比例 × 字体百分比，滑条范围 50%–300%。
- 头像：基准直径 × 窗口比例 × 头像百分比，滑条范围 50%–300%，默认 100%。伤害头像基准为 32px。

内置模板使用 `font_mode: "css"`，文字以 `rem` 配合 `--overlay-font-scale`，图片使用 `--overlay-window-scale`。
普通网页由宿主按 DOM 初始 computed 字号缩放；Canvas、图片内文字和 iframe 由模板处理。

伤害窗的 `damage/layout.js` 按以下规则测量：

- 列宽下限容纳默认头像、四字名称、`100.00M`、`100.0%` 和表头，按 8px 档位取整；内容超限时加宽。
- 团队数据和计时计入最小宽度；列数改变立即重算，表头与数据行共用列宽。
- 高度匹配实际行数、字号与头像，底栏紧跟表格；数值刷新复用布局及头像节点。

`overlays/content_size.py` 通过 Qt WebChannel 接收伤害/连携页的自然尺寸，更新原生窗口、GUI 数值和配置。
自动调整保持右边缘，最大尺寸取当前屏幕可用区域，超出部分在表格内滚动。

`template_settings._damage_window_scale` / `_combo_window_scale` 保存窗口比例：手动缩放时更新，列数、内容及独立滑条变化时复用。
连携切换样式后重测尺寸；进度条样式内保留用户宽度。跨屏移动保持拖动开始时的逻辑宽高，DPI 临时尺寸仅用于显示。

默认头像百分比见 `damage/template.json` 的 `avatar_size_percent.default`，基准直径见 `damage/style.css` 的 `--character-avatar-size`。

## 模板声明

内置模板位于 `_internal/src/endfield_pcap/overlays/assets/<类型>/`。
Qt 宿主管理窗口，JSON 声明订阅和设置，HTML/CSS/JS 消费设置并绘制快照。

「选择本地模板 / HTML」支持 JSON 或 HTML；选择 HTML 时依次查找同名 `xxx.template.json`、同目录 `template.json`。
可参考 `_development/examples/overlay-template/`：

```json
{
  "schema_version": 1,
  "name": "我的浮窗",
  "entry": "index.html",
  "subscriptions": ["analysis_summary"],
  "font_mode": "css",
  "window": {"min_width": 240, "min_height": 120, "default_width": 400, "default_height": 200},
  "settings": [
    {"key": "avatar_size_percent", "label": "头像大小", "type": "slider", "min": 50, "max": 300, "default": 100}
  ]
}
```

| 字段 | 约定 |
| --- | --- |
| `entry` | 相对 JSON 所在目录 |
| `subscriptions` | `analysis_summary`、`analysis_snapshot`、`combo_snapshot`；本地静态内容用空数组 |
| `settings.type` | `select`、`multiselect`、`slider` |
| `settings.default` | 多选为字符串数组；滑条为 `min` / `max` 范围内整数 |
| `template_settings` | 每个窗口实例保存自己的设置 |

本地声明模板通过进程内桥接收配置和整份状态；页面重载后补发当前状态：

```js
window.addEventListener("endfield-overlay-config", event => {
  const {settings, fontScale, referenceSize} = event.detail;
});
window.addEventListener("endfield-analysis-snapshot", event => {
  render(event.detail.snapshot); // null 表示清空
});
// 延迟安装的监听器可读取当前缓存：
// window.endfieldOverlay.config
// window.endfieldOverlay.snapshots.analysis_snapshot
```

伤害模板跟随 GUI 的历史/实时选择。URL 和无声明 HTML 自行连接实时 WS，浏览器需携带服务的 `access_token`。
WS 模式本地模板可将 URL 的 `wsToken` 转为该参数；远程 URL 的凭据由用户配置。认证规则见 [实时摘要](live-summary-publisher.md)。

## OBS 与 UID

OBS 添加「窗口采集」，捕获方式选 Windows 10（Windows Graphics Capture），按浮窗名称选择同一个 Qt 窗口。
桌面隐藏使用零透明度，保持 HWND、几何与绘制；恢复时还原透明度和穿透设置。停用该项或退出 GUI 后窗口结束。

`uid_mask/template.json` 提供矩形/圆角黑色遮挡，默认 220×32、主屏左下角。拖到游戏 UID 位置后，使用矩形、100% 透明度及鼠标穿透。
