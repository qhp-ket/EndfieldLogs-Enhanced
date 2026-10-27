"""Fit trusted built-in windows to measured content without scaling feedback."""
from __future__ import annotations

import math
from pathlib import Path
from PySide6.QtCore import QObject, QTimer
from endfield_pcap.models import OverlaySourceType

SCALE_SETTING = '_damage_window_scale'


class ContentFitter(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.source = window.entry.source_value
        self.scale_setting = {'damage': SCALE_SETTING, 'combo_skill': '_combo_window_scale'}.get(self.source, '_native_window_scale')
        self.reference = None
        stored = window.entry.template_settings.get(self.scale_setting)
        self.scale = (float(stored) if window.entry.geometry is not None
                      and isinstance(stored, (int, float)) and math.isfinite(stored)
                      and .01 <= stored <= 100 else None)
        self.resizing = False
        self.pending = None
        self.reset_position = window.entry.geometry is None
        self.default_anchor = self.reset_position
        self.layout_style = 'bars' if window.canvas.bars else 'circles'
        self.bar_width = (window.width() if self.layout_style == 'bars' and window.entry.geometry else None)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._apply)
    def window_resized(self):
        window = self.window
        if self.resizing or self.reset_position or self.reference is None or window._drag_size is not None:
            return
        width, height = self.reference
        if self.window.canvas.bars:
            self.scale = window.height()/height
            self.bar_width = window.width()
        else:
            self.scale = min(window.width()/width, window.height()/height)
        self.default_anchor = False
        self.pending = None
        self.timer.stop()

    def window_moved(self):
        if not self.resizing and not self.reset_position:
            self.default_anchor = False

    def fit(self, width, height, style='circles'):
        if not all(math.isfinite(v) and 0 < v <= 32768 for v in (width, height)):
            return
        style_changed = self.window.canvas.bars != (self.layout_style == 'bars')
        if not self.reset_position and not style_changed and self.reference == (width,height):
            return
        if style_changed:
            self.bar_width = None
        self.layout_style = 'bars' if self.window.canvas.bars else 'circles'
        self.pending = (width, height)
        if self.reference is None:
            self.reference = self.pending
        self.timer.start(0)

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
        if self.window.canvas.bars and self.bar_width:
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
