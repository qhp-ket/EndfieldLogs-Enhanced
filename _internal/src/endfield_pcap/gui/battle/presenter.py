"""Connect explicit battle display/input requests to application controllers."""
from PySide6.QtCore import QObject, QTimer

from endfield_pcap.application.input_evidence import InputEvidenceController, empty_evidence
from endfield_pcap.application.records import BattleRecordInfo
from endfield_pcap.gui.battle.detail import BattleDetailDialog


class BattleDetailPresenter(QObject):
    @classmethod
    def create(cls, snapshot, label, settings, *, record=None, parent=None):
        info = BattleRecordInfo.from_record(record, label) if record is not None else None
        dialog = BattleDetailDialog(snapshot, label, parent, record_info=info, display_settings=settings.battle_display())
        # Lifetime follows the window, independent of its Qt parent.
        dialog.presenter = cls(dialog, settings, record=record)
        return dialog

    def __init__(self, dialog, settings, *, record=None):
        super().__init__(dialog)
        self.dialog = dialog
        self.input = InputEvidenceController(dialog.snapshot.get('battle') or {}, settings)
        dialog.characterAvatarsChanged.connect(settings.set_character_avatars)
        dialog.avatarPercentChanged.connect(settings.set_avatar_percent)
        dialog.characterLanesChanged.connect(settings.set_character_lanes)
        dialog.tableWidthsChanged.connect(settings.set_table_widths)
        bar = dialog.input_history
        bar.bindingChosen.connect(lambda path: self._change(self.input.bind, path))
        bar.bindingRemoved.connect(lambda: self._change(self.input.unbind))
        bar.visibilityRequested.connect(lambda value: self._change(self.input.set_visible, value))
        bar.settingsRequested.connect(lambda value: self._change(self.input.set_settings, value))
        bar.alignmentRequested.connect(lambda values: self._change(self.input.set_alignment, **values))
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._drain)
        dialog.finished.connect(self.close)
        if record is not None:
            self.set_record(record)
        else:
            self._render_input()

    def set_record(self, record):
        self.dialog.record_info = BattleRecordInfo.from_record(record, self.dialog.record_label)
        self._change(self.input.set_record, record)

    def relocate_record(self, old, new):
        self._change(self.input.relocate, old, new)

    def _change(self, operation, *args, **kwargs):
        operation(*args, **kwargs)
        self._render_input()

    def _drain(self):
        if self.input.drain():
            self._render_input()

    def _render_input(self):
        state = self.input.state
        value = state.evidence
        tooltip = ''
        if state.pending:
            text = '正在后台索引输入证据…'
            self.timer.start()
        else:
            self.timer.stop()
            if state.error is not None:
                text = f'输入日志不可用：{state.error}'
            elif not state.paths or not value.get('paths'):
                text = '未绑定 input log'
            else:
                notes = value['warnings']
                count = sum(value.get('input_counts', {}).values())
                text = (f'已绑定 {state.paths[0].name} · 本场 {count} 条输入记录 / {len(value["actions"])} 条输入意图'
                    + (' · 手动对齐' if value['manual_alignment'] else '')
                    + (' · 战斗时间范围内未录到输入，请核对录制与对齐' if not count else '')
                    + (' · '+notes[0] if notes else ''))
                tooltip = '\n'.join(value['paths'] + [f'本场输入分类：{value.get("input_counts", {})}',
                    f'整个输入文件分类：{value.get("recording_counts", {})}'] + notes)
        self.dialog.input_history.set_state(state, text, tooltip)
        self.dialog.timeline.set_input_evidence(value if state.visible else empty_evidence())

    def close(self, *_):
        self.timer.stop()
        self.input.close()
