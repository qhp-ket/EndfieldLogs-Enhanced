"""Battle windows save explicit preferences with ordinary Qt parents."""
from copy import deepcopy

from PySide6.QtWidgets import QWidget

from app_test_support.scenarios.compact import sample
from endfield_pcap.application.settings import SettingsStore
from endfield_pcap.gui.battle.presenter import BattleDetailPresenter
from endfield_pcap.settings import load_app_config


def test_independent_detail_windows_submit_preferences_without_config_parent(app, tmp_path):
    path = tmp_path/'settings.json'
    config = load_app_config(path)
    config.character_avatar_percent = 130
    config.gui_font_percent = 120
    store = SettingsStore(config, path)
    owner = QWidget()
    snapshot = sample()
    before = deepcopy(snapshot)
    first = BattleDetailPresenter.create(snapshot, '独立分析 A', store, parent=owner)
    second = BattleDetailPresenter.create(snapshot, '独立分析 B', store)
    try:
        assert first.snapshot is second.snapshot is snapshot
        assert first.avatar_size_slider.value() == 130
        assert first.property('gui_font_scale') == 1.2
        first.avatar_check.setChecked(False)
        second.avatar_size_slider.setValue(170)
        actor = snapshot['participants'][0]['character_key']
        first.characterLanesChanged.emit(actor, [])
        second.characterLanesChanged.emit('other-actor', [])
        # A different report saves only the changed character/table.
        first.tableWidthsChanged.emit('skills', [120, 80])
        second.tableWidthsChanged.emit('hits', [100, 200])
        restored = load_app_config(path)
        assert not restored.show_character_avatars
        assert restored.character_avatar_percent == 170
        assert restored.battle_lane_configs == {actor: [], 'other-actor': []}
        assert restored.battle_table_widths == {'skills': [120, 80], 'hits': [100, 200]}
        assert first.snapshot == before
        # Public edit data cannot mutate the timeline's block collection/config.
        options = first.timeline.role_lane_options(actor)
        options['skills'].clear()
        options['lanes'].clear()
        assert first.timeline.role_lane_options(actor)['skills']
    finally:
        first.close()
        second.close()
        owner.close()
        app.processEvents()
