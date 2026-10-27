"""Compact wrapping control groups and non-modal settings popups."""
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget, QHBoxLayout, QMenu, QWidgetAction
from qfluentwidgets import FlowLayout, ComboBox
from endfield_pcap.data.skill_names import character_name


class WrapLayout(FlowLayout):
    def __init__(self, parent=None):
        super().__init__(parent, needAni=False, isTight=True)
        self.setContentsMargins(0, 0, 0, 0)
        self.setHorizontalSpacing(6)
        self.setVerticalSpacing(6)


def group(parent, *widgets):
    box = QWidget(parent)
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    for widget in widgets:
        layout.addWidget(widget)
    return box


def popup(button, content):
    menu = QMenu(button)
    action = QWidgetAction(menu)
    action.setDefaultWidget(content)
    menu.addAction(action)
    button.clicked.connect(lambda: menu.popup(button.mapToGlobal(QPoint(0, button.height()))))
    return menu


def character_selector(snapshot, parent):
    combo = ComboBox(parent)
    combo.setMaximumWidth(200)
    combo.addItem('全部角色', userData='')
    for participant in snapshot.get('participants') or []:
        key = str(participant['character_key'])
        combo.addItem(character_name(key, participant.get('character_name', '')), userData=key)
    return combo
