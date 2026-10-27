"""Tray access and disposable GUI caches; background services keep running."""
from __future__ import annotations
import weakref
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QStyle


class GuiLifecycle:
    def _init_gui_lifecycle(self):
        self._gui_hotkey_registered=False
        self._registered_gui_hotkey=''
        self._hidden_gui_windows=[]
        icon=self.windowIcon()
        if icon.isNull(): icon=self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray_icon=QSystemTrayIcon(icon,self)
        self.tray_icon.setToolTip(self.windowTitle())
        menu=QMenu(self)
        show=QAction('显示主界面',menu);show.triggered.connect(self._restore_gui)
        hide=QAction('隐藏主界面',menu);hide.triggered.connect(self._hide_gui)
        quit_action=QAction('退出程序',menu);quit_action.triggered.connect(self.close)
        for action in (show,hide,quit_action): menu.addAction(action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable(): self.tray_icon.show()
        self.home_page.hide_gui_btn.clicked.connect(self._hide_gui)

    def _tray_activated(self,reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_gui()

    def _toggle_gui_visibility(self):
        if any(window.isVisible() and not window.isMinimized() for window in self._gui_windows()): self._hide_gui()
        else: self._restore_gui()

    def _gui_windows(self):
        # Overlay windows have an independent lifecycle and visibility control.
        def belongs(window):
            while window is not None:
                if self.overlay_manager.owns_window(window): return False
                if window is self: return True
                window=window.parentWidget()
            return False
        return [window for window in QApplication.topLevelWidgets()
                if belongs(window)
                and window.windowType() not in (Qt.WindowType.Popup,Qt.WindowType.ToolTip)]

    def _hide_gui(self):
        for window in self._gui_windows():
            if window is not self and window.isVisible():
                self._hidden_gui_windows.append((weakref.ref(window),window.windowState()))
                window.hide()
        self._release_history_caches()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()
            self.hide()
        else:
            self.showMinimized()  # Keep a way back when no notification area exists.

    def _restore_gui(self):
        if self._closing: return
        self.showNormal()
        windows,self._hidden_gui_windows=self._hidden_gui_windows,[]
        for reference,state in windows:
            window=reference()
            if window is not None:
                try:
                    window.setWindowState(state)
                    window.show()
                except RuntimeError:
                    pass  # A hidden dialog may have been deleted meanwhile.
        self.raise_()
        self.activateWindow()
        self._update_service_status()
        self.home_page.status_card.set_squad_members(self.current_squad)
        self._drain_independent_services()

    def _release_history_caches(self):
        self.history_controller.release_cache()

    def _update_gui_poll_interval(self):
        self._gui_hidden=not self.isVisible() or self.isMinimized()
        timer=getattr(self,'queue_timer',None)
        if timer is not None:
            # Hidden GUI still drains at the visual service's maximum 20 Hz.
            timer.setInterval(50 if self._gui_hidden else 33)

    def hideEvent(self,event):
        super().hideEvent(event)
        self._update_gui_poll_interval()

    def changeEvent(self,event):
        super().changeEvent(event)
        self._update_gui_poll_interval()
