"""Evidence panel states shared by its splitter, toolbar and corner buttons."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter


class BattleDetailSplitter(QSplitter):
    detailsChanged = Signal(bool, bool)  # expanded, maximized

    def __init__(self, timeline, inspector, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self._normal_sizes = [330, 190]
        self._panel_state = None
        self.addWidget(timeline)
        self.addWidget(inspector)
        self.setStretchFactor(0, 3)
        self.setStretchFactor(1, 1)
        self.setCollapsible(0, True)
        self.setCollapsible(1, True)
        self.splitterMoved.connect(self._sync_panel_state)
        self.setSizes([1, 0])

    def setSizes(self, sizes):  # noqa: N802
        super().setSizes(sizes)
        self._sync_panel_state()

    def _sync_panel_state(self, *args):
        sizes = self.sizes()
        if len(sizes) != 2 or not sum(sizes):
            return
        expanded = sizes[1] > 0
        maximized = expanded and sizes[0] == 0
        if expanded and not maximized:
            self._normal_sizes = sizes
        state = expanded, maximized
        if state != self._panel_state:
            self._panel_state = state
            self.detailsChanged.emit(*state)

    def details_expanded(self):
        return bool(self.sizes()[1])

    def details_maximized(self):
        first, second = self.sizes()
        return first == 0 and second > 0

    def set_details_expanded(self, expanded):
        self.setSizes(self._normal_sizes if expanded else [max(1, sum(self.sizes())), 0])

    def toggle_details_maximized(self):
        self.setSizes(self._normal_sizes if self.details_maximized()
                      else [0, max(1, sum(self.sizes()))])
