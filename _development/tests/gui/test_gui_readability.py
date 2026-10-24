"""Real geometry/font scaling, independent of combat calculations and overlays."""
from PySide6.QtCore import QPointF, QPoint, Qt
from PySide6.QtGui import QWheelEvent, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyleOptionViewItem
from qfluentwidgets import CaptionLabel, Theme, setTheme
import endfield_pcap.gui.config as gui_config
from endfield_pcap.gui.battle.detail import BattleDetailDialog
from app_test_support.ui.window import main_window
from app_test_support.ui.qt import snapshot_message, EVIDENCE


def pixels(widget):
    f = widget.font()
    return f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF()


def test_graphic_zoom_changes_block_height_font_and_markers_not_only_time_axis(app):
    dialog = BattleDetailDialog(snapshot_message()['snapshot'], '图形缩放测试')
    try:
        dialog.show(); QTest.qWait(100)
        def block():
            return next(i for i in dialog.timeline.scene().items() if hasattr(i, 'block') and i.block.lane == 'skill')
        old_height, old_scale = block().rect().height(), block().scale
        time_zoom = dialog.zoom_slider.value()
        dialog.graphics_zoom_slider.setValue(180)
        assert block().rect().height() > old_height*1.7
        assert block().scale > old_scale*1.7
        assert dialog.zoom_slider.value() == time_zoom
        assert dialog.timeline.hit_markers == 6
        wheel = QWheelEvent(QPointF(400, 100), QPointF(400, 100), QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
        app.sendEvent(dialog.timeline.viewport(), wheel)
        assert dialog.graphics_zoom_slider.value() == 190
        dialog.grab().save(str(EVIDENCE / 'battle-graphics-zoom.png'))
    finally:
        dialog.close(); app.processEvents()


def test_font_size_persists_scales_dynamic_details_without_compounding(main_window, app):
    window = main_window
    window._show_history_detail(snapshot_message()['snapshot'], '可调字号战斗分析')
    dialog = window._history_detail_dialog
    QTest.qWait(100)
    before = pixels(dialog.event_detail)
    overlay_fonts = [e.font_scale for e in window.app_config.overlays]
    window.settings_page.gui_font_slider.setValue(160)
    QTest.qWait(100)
    assert pixels(dialog.event_detail) > before*1.25
    size = pixels(dialog.event_detail)
    for _ in range(4):
        window.gui_typography.apply()
        app.processEvents()
    assert pixels(dialog.event_detail) == size
    assert window.app_config.gui_font_percent == 160
    assert gui_config.load_app_config(window.config_path).gui_font_percent == 160
    assert [e.font_scale for e in window.app_config.overlays] == overlay_fonts
    dynamic = CaptionLabel('后来创建的文字', dialog)
    dynamic.show(); QTest.qWait(60)
    assert pixels(dynamic) == round(dynamic.property('_gui_base_font').pixelSize()*1.6)
    dynamic.hide()
    option = QStyleOptionViewItem()
    dialog.skill_table.itemDelegate().initStyleOption(option, dialog.skill_table.model().index(0, 0))
    assert option.font == dialog.skill_table.font()
    assert dialog.skill_table.verticalHeader().defaultSectionSize() > QFontMetrics(option.font).height()
    setTheme(Theme.LIGHT); QTest.qWait(60)
    setTheme(Theme.DARK); QTest.qWait(60)
    assert pixels(dialog.event_detail) == size
    dialog.grab().save(str(EVIDENCE / 'battle-global-font-160.png'))
    window._show_history_detail(snapshot_message()['snapshot'], '新打开窗口继承字号')
    QTest.qWait(80)
    assert pixels(window._history_detail_dialog.event_detail) == size


def test_large_global_font_pages_scroll_and_windows_stay_on_screen(main_window, app):
    window = main_window
    window.settings_page.gui_font_slider.setValue(180)
    window._show_history_detail(snapshot_message()['snapshot'], '大字号仍在屏幕内')
    dialog = window._history_detail_dialog
    QTest.qWait(140)
    assert dialog.screen().availableGeometry().contains(dialog.frameGeometry())
    assert dialog.body_scroll.widget().height() >= dialog.body_scroll.viewport().height()
    window.switchTo(window.settings_page)
    QTest.qWait(80)
    assert window.settings_page.verticalScrollBar().maximum() > 0
    window.grab().save(str(EVIDENCE / 'gui-global-font-180.png'))
