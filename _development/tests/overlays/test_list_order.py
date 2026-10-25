"""List drag moves persist configuration without restarting running windows."""
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView
from app_test_support.ui.window import main_window
from endfield_pcap.gui.config import load_app_config


def test_overlay_internal_drag_saves_order_and_keeps_selection_and_windows(main_window):
    window = main_window
    listing = window.overlay_page.overlay_list
    assert listing.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove
    original = list(window.app_config.overlays)
    selected = original[0].id
    listing.setCurrentRow(0)
    hosts = dict(window.overlay_manager._windows)
    assert listing.model().moveRows(QModelIndex(), 0, 1, QModelIndex(), listing.count())
    expected = original[1:] + original[:1]
    assert window.app_config.overlays == expected
    assert window.overlay_page.selected_entry_id() == selected
    assert window.overlay_manager._windows == hosts
    assert [listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(listing.count())] == [e.id for e in expected]
    saved = load_app_config(window.config_path).overlays[:len(expected)]
    assert [e.id for e in saved] == [e.id for e in expected]
    assert [(e.enabled,e.hidden,e.template_settings,e.geometry) for e in saved] == [
        (e.enabled,e.hidden,e.template_settings,e.geometry) for e in expected]
    window._refresh_overlay_views()
    assert window.overlay_page.selected_entry_id() == selected
    assert listing.item(0).data(Qt.ItemDataRole.UserRole) == expected[0].id


def test_home_separates_services_and_vision_navigates_to_overlays(main_window, app):
    window = main_window
    page = window.home_page
    assert page.input_service_btn.parentWidget() != page.vision_status.parentWidget()
    assert not hasattr(page, 'vision_settings_btn')
    window.switchTo(page)
    page.vision_overlays_btn.click()
    app.processEvents()
    assert window.stackedWidget.currentWidget() == window.overlay_page
    assert not window.vision_controller.state.get('enabled', False)
