# 原生悬浮窗与皮肤

三类浮窗使用 PySide6 Widgets / QPainter。每窗一个内容画布，模块使用普通 Python 对象测量、绘制和命中查询。

## 窗口控制

列表顺序、位置、尺寸、字号、锁定、穿透、透明度及独立皮肤设置保存在便携配置中。
启用项创建窗口并合并必要订阅；停用项释放窗口。右上角 × 控制桌面显示，一键显隐与快捷键保存并恢复当前集合。
隐藏到托盘控制 GUI；浮窗显隐由浮窗入口控制。

## 数据与尺寸

| 模块 | 数据 | 设置 |
| --- | --- | --- |
| `damage` | `analysis_summary`；历史使用报告表格投影 | `bar_mode`（`dps` / `rdps`）、`columns`、`theme`、头像开关与比例 |
| `combo_skill` | 独立视觉服务的 `combo_snapshot` | `display_style`（`circles` / `bars`）、`theme`、头像开关与比例 |
| `uid_mask` | 本地设置 | `shape`（`rectangle` / `rounded`） |

多个窗口共用分析，独立浮窗使用 Python WebSocket 客户端连接本地服务并自动重连。

宽高使用 Qt 逻辑像素。文字、列宽、头像和实际行数决定自然尺寸。布局与头像缓存复用，数据或设置变化时更新绘制。

- 窗口比例取宽高相对自然尺寸的较小值；连携横条按高度缩放，宽度独立拉伸。
- 字体与头像分别支持 50%–300%；伤害头像基准为 40px。
- 内容变化保持右边缘，尺寸受当前屏幕可用区域限制；跨屏拖动保持原始逻辑尺寸。
- 重置布局恢复默认位置、字号和窗口比例。

窗口比例保存在 `template_settings` 的 `_damage_window_scale`、`_combo_window_scale` 或 `_native_window_scale`。
合成负载基准可运行 `python -B _development/tools/benchmark_native_overlays.py --output _development/verification/overlays.json`，记录固定三窗口的进程树内存、CPU 和画布时延。

## JSON 皮肤

点击「导入原生皮肤」选择 v2 JSON。完整示例见 [overlay-template](../examples/overlay-template/template.json)。

```json
{
  "schema_version": 2,
  "name": "伤害与连携",
  "modules": [
    {"type": "damage", "settings": {"bar_mode": "rdps"}},
    {"type": "combo_skill", "settings": {"display_style": "bars"}}
  ],
  "layout": {"direction": "vertical"},
  "theme": {"background": "#20252d", "spacing": 8, "padding": 4}
}
```

| 字段 | 约定 |
| --- | --- |
| `window` | `min_width`、`min_height`、`default_width`、`default_height`，逻辑像素整数 |
| `layout.direction` | 单模块 `single`；组合使用 `horizontal` 或 `vertical` |
| `theme` | `font_family`、背景/前景/次要色 `background` / `foreground` / `muted`、强调/就绪/边框色 `accent` / `ready` / `border`、`radius`、`spacing`、`padding`、`border_width`、`image` |
| 颜色 | `#RRGGBB`、`#AARRGGBB`、`transparent` |
| `theme.image` | 皮肤目录内的相对 PNG、JPEG、BMP 或 WebP |
| `settings` | `select`、`multiselect` 或整数 `slider`；GUI 自动生成控件 |
| `modules[].setting_bindings` | 模块设置名映射到已声明的 `settings[].key` |

模块 `theme` 预设为 `light`、`dark`、`transparent` 或 `endfield`。
内置伤害与连携浮窗的「背景模式 → 终末地」使用浅色面板、黑色抬头和静态黄斜纹；伤害浮窗保留黄斜纹状态栏和等宽数字。
导入皮肤也可在模块 `settings` 中设置 `"theme": "endfield"`，配色仍可通过顶层 `theme` 参数调整。
`columns` 可选 `damage`、`damage_rate`、`rdamage`、`rdamage_rate`。
`show_character_avatars` 为 `on` / `off`；`avatar_size_percent` 为 50–300 整数。
同名设置直接应用，也可通过绑定为各模块分配独立设置。模块注册表汇总订阅，每个窗口独立保存配置。

## OBS 与迁移

OBS 添加「窗口采集」，捕获方式选择 Windows 10（Windows Graphics Capture），按浮窗名称选择 Qt 窗口。
桌面隐藏使用零透明度，保持 HWND、几何与绘制；停用或退出程序会结束窗口。
UID 默认为主屏左下角 220×32 黑色矩形，可调整形状、尺寸、位置和穿透。

旧配置保留三类内置浮窗和 v2 皮肤的 ID、顺序及窗口设置。网页模板、URL、BUFF 和最近输入浮窗条目移除并提示一次；用户模板文件和日志留在原目录。
