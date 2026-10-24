"""Retain the logged interval underneath a fixed display-duration fallback."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen
from endfield_pcap.analysis.battle.time import format_time


def draw_skill_reference(view, block, y, scale, x_at, color):
    reference = block.frame_reference
    if not view._show_skill_frames or not reference or reference.get('end_ms') is None:
        return
    scene = view.scene()
    # A solid underline retains the original logged interval. It does not
    # extend/shorten in response to the static configuration's duration.
    measured = scene.addLine(x_at(block.start_ms), y+27*scale,
        x_at(block.end_ms), y+27*scale, QPen(QColor(color), 2.5))
    measured.setToolTip('日志区间：'+format_time(block.start_ms, view._time_unit)
                        +'–'+format_time(block.end_ms, view._time_unit))
    measured.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    view.reference_blocks += 1
    # Configuration damage windows remain relative evidence in the inspector.
    # Projecting them onto this first-hit anchor would imply a known phase and
    # effective clock, neither of which follows from the existing trace.
