"""Fit trusted built-in windows to measured content without scaling feedback."""
from __future__ import annotations

import math
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWebChannel import QWebChannel
from endfield_pcap.models import OverlaySourceType

SCALE_SETTING = '_damage_window_scale'


class ContentSizeBridge(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.source = window.entry.source_value
        self.scale_setting = SCALE_SETTING if self.source == 'damage' else '_combo_window_scale'
        self.reference = None
        stored = window.entry.template_settings.get(self.scale_setting)
        self.scale = (float(stored) if window.entry.geometry is not None
                      and isinstance(stored, (int, float)) and math.isfinite(stored)
                      and .01 <= stored <= 100 else None)
        self.resizing = False
        self.pending = None
        self.reset_position = window.entry.geometry is None
        self.default_anchor = self.reset_position
        self.layout_style = window.entry.template_settings.get('display_style', 'circles')
        self.bar_width = (window.width() if self.source == 'combo_skill'
                          and self.layout_style == 'bars' and window.entry.geometry else None)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._apply)
        self.channel = QWebChannel(self)
        self.channel.registerObject('damageContent' if self.source == 'damage' else 'comboContent', self)
        window.webview.page().setWebChannel(self.channel)

    def window_resized(self):
        window = self.window
        if self.resizing or self.reset_position or self.reference is None or window._drag_size is not None:
            return
        width, height = self.reference
        if self.source == 'combo_skill' and self.layout_style == 'bars':
            self.scale = window.height()/height
            self.bar_width = window.width()
        else:
            self.scale = min(window.width()/width, window.height()/height)
        self.default_anchor = False

    def window_moved(self):
        if not self.resizing and not self.reset_position:
            self.default_anchor = False

    @Slot(float, float)
    def fit(self, width, height):
        window = self.window
        # The channel is a sizing capability for this local renderer only.
        from endfield_pcap.overlays.templates import ASSETS
        if (window.entry.source_type != OverlaySourceType.BUILTIN
                or self.source not in ('damage', 'combo_skill')
                or window.entry.source_value != self.source
                or Path(window.webview.url().toLocalFile()).resolve() != (ASSETS / ('damage' if self.source == 'damage' else 'combo') / 'index.html').resolve()
                or not all(math.isfinite(v) and 0 < v <= 32768 for v in (width, height))):
            return
        self.pending = (width, height)
        self.timer.start(0)
        return True

    @Slot(float, float, str)
    def fitLayout(self, width, height, style):
        if (self.source != 'combo_skill' or style not in ('bars', 'circles')
                or style != self.window.entry.template_settings.get('display_style', 'circles')):
            return
        if self.fit(width, height) and style != self.layout_style:
            self.bar_width = None
            self.layout_style = style

    def _apply(self):
        window = self.window
        if window._drag_origin is not None or window._resize_origin is not None:
            self.timer.start(100)
            return
        if self.pending is None:
            return
        width, height = self.pending
        self.pending = None
        if self.scale is None:
            from endfield_pcap.overlays.templates import template_for
            defaults = template_for(window.entry).window
            self.scale = min(window.width()/defaults.get('default_width', window.config.default_width),
                             window.height()/defaults.get('default_height', window.config.default_height))
        self.reference = (width, height)
        screen = window.screen()
        area = screen.availableGeometry() if screen else None
        if area:
            self.scale = min(self.scale, max(window.minimumWidth(), area.width())/width,
                             max(window.minimumHeight(), area.height())/height)
        # Clamp the common scale first; independently clamping dimensions leaves
        # empty space below the table and changes height again on the next open.
        target_width = max(window.minimumWidth(), math.ceil(width*self.scale))
        if self.source == 'combo_skill' and self.layout_style == 'bars' and self.bar_width:
            target_width = max(window.minimumWidth(), self.bar_width)
            if area:
                target_width = min(target_width, max(window.minimumWidth(), area.width()))
        target_height = max(window.minimumHeight(), math.ceil(height*self.scale))
        right = window.x()+window.width()
        self.resizing = True
        try:
            window.resize(target_width, target_height)
            if self.reset_position or self.default_anchor:
                window._move_to_default_position()
                self.reset_position = False
            elif area:
                window.move(max(area.left(), min(right-target_width, area.right()-target_width+1)),
                            max(area.top(), min(window.y(), area.bottom()-target_height+1)))
        finally:
            self.resizing = False
        window._emit_geometry_changed()
