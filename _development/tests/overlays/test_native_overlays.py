"""Real native canvases: data, sizing, pixels, hover and window lifecycle."""
from copy import deepcopy
from dataclasses import replace
from itertools import combinations
import json
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtTest import QTest
from app_test_support.ui.window import entry, main_window
from app_test_support.ui.qt import EVIDENCE, snapshot_message
from endfield_pcap.models import OverlayGeometry
from endfield_pcap.overlays.manager import OverlayManager
from endfield_pcap.overlays.templates import with_template_value
from endfield_pcap.gui.config import load_app_config


def damage(seq=1, **changes):
    snapshot = dict(battle=dict(total_damage=1000,total_dps=100,duration_ms=10000),
        participants=[dict(character_key='chr_0004_pelica',character_name='很长的角色名称 · 佩丽卡',
            total_damage=800,total_rd=200,crit_rate=.25),
            dict(character_key='chr_0003_endminf',character_name='管理员',total_damage=200,total_rd=800,crit_rate=None)],
        quality_summary=dict(status='provisional',rdps=dict(status='provisional',reasons=['missing'])) )
    return dict(type='analysis_summary',schema_version=1,stream_id='native',sequence=seq,snapshot=snapshot,**changes)


def combo(seq=1, stream='visual'):
    slots=[dict(slot=i,status=status,character_key='chr_0004_pelica' if i==0 else None,
                display_name='佩丽卡' if i==0 else f'位置 {i+1}',progress=.5 if i==0 else 1. if i==1 else None,
                estimated_remaining_ms=3500 if i==0 else None,held=i==0)
           for i,status in enumerate(('cooldown','ready','dead','empty'))]
    return dict(type='combo_snapshot',schema_version=2,stream_id=stream,sequence=seq,
                snapshot=dict(status='识别中',slots=slots))


@pytest.fixture
def hosts(app):
    manager=OverlayManager(1,use_in_process_snapshots=True)
    yield manager
    manager.close_all()
    app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def show(hosts, app, source='damage', **settings):
    current=entry(enabled=True,source_value=source,template_settings=settings)
    hosts.apply_entry(current);app.processEvents()
    return hosts._windows[current.id]


def test_summary_history_reset_order_and_new_instances(hosts,app):
    window=show(hosts,app)
    first=damage();original=deepcopy(first)
    hosts.apply_analysis_summary(first);app.processEvents()
    module=window.canvas.modules[0]
    assert module.message['snapshot']['battle']['total_damage']==1000
    first['snapshot']['battle']['total_damage']=99999
    assert module.message['snapshot']['battle']['total_damage']==1000
    hosts.apply_analysis_summary(damage(0))
    assert module.gate.sequence==1
    revision=window.canvas.layout_revision
    hosts.apply_analysis_summary(damage(2))
    assert window.canvas.layout_revision==revision
    hosts.show_history(dict(battle={'total_damage':500}), '合成战斗')
    assert module.message['source']==dict(mode='history',label='合成战斗')
    hosts.apply_analysis_summary(damage(3))
    assert module.message['snapshot']['battle']['total_damage']==500
    hosts.return_live()
    assert module.message['snapshot']==original['snapshot']
    hosts.apply_entry(entry(id='second',enabled=True))
    assert hosts._windows['second'].canvas.modules[0].message['snapshot']==original['snapshot']
    hosts.apply_analysis_summary(dict(damage(0, source={'mode':'live'}),stream_id='new',snapshot=None))
    assert module.message['snapshot'] is None
    hosts.apply_analysis_summary(damage(100))
    assert module.message['snapshot'] is None


@pytest.mark.parametrize('theme',['light','dark','transparent','endfield'])
def test_damage_columns_sort_avatars_hover_and_pixels(hosts,app,theme):
    window=show(hosts,app,theme=theme)
    hosts.apply_analysis_summary(damage());app.processEvents()
    before=deepcopy(window.canvas.modules[0].message)
    for count in range(5):
        for selected in combinations(['damage','damage_rate','rdamage','rdamage_rate'],count):
            window.apply_entry(with_template_value(window.entry,'columns',list(selected)));app.processEvents()
            layout=window.canvas._rects[0][1]
            assert len(layout.data['columns'])==count and len(layout.data['rows'])==2
            assert all(rect.right()<=layout.size.width()+.1 for rect,_ in layout.hits)
            assert not window.grab().isNull()
    window.apply_entry(with_template_value(window.entry,'bar_mode','rdps'));app.processEvents()
    layout=window.canvas._rects[0][1]
    assert layout.data['rows'][0]['player']['total_rd']==800
    assert window.canvas.modules[0].message==before
    window.apply_entry(with_template_value(window.entry,'columns',['damage','rdamage']));app.processEvents()
    layout=window.canvas._rects[0][1]
    hit=next((rect,tip) for rect,tip in layout.hits if 'rDMG：' in tip)
    assert '800.00' in hit[1]
    assert 'rDMG' in window.canvas.tooltip(hit[0].center()*window.canvas.scale)
    avatar=layout.data['avatar']
    window.apply_entry(replace(window.entry,font_scale=1.5));app.processEvents()
    assert window.canvas._rects[0][1].data['avatar']==avatar
    window.apply_entry(with_template_value(window.entry,'avatar_size_percent',150));app.processEvents()
    assert window.canvas._rects[0][1].data['avatar']==avatar*1.5
    window.apply_entry(with_template_value(window.entry,'show_character_avatars','off'));app.processEvents()
    assert window.canvas._rects[0][1].data['avatar']==0
    assert window.grab().save(str(EVIDENCE/f'native-damage-{theme}.png'))
    if theme=='transparent':
        assert window.canvas.grab().toImage().pixelColor(5,5).alpha()<255


def test_unknown_large_values_empty_rows_and_no_full_report_retention(hosts,app):
    window=show(hosts,app)
    message=snapshot_message()
    message['snapshot']['timeline_events']=[dict(secret='not needed')]
    window.apply_analysis_snapshot(message);app.processEvents()
    assert 'timeline_events' not in window.canvas.modules[0].message['snapshot']
    message=damage(2)
    message['snapshot']['participants'][0]['total_rd']=None
    message['snapshot']['participants'][0]['total_damage']=1e12
    hosts.apply_analysis_summary(message);app.processEvents()
    layout=window.canvas._rects[0][1]
    row=next(row for row in layout.data['rows'] if row['player']['total_rd'] is None)
    assert 'M' in row['cells'][0][0]
    assert row['cells'][2][0]=='—'
    width=window.width();height=window.height()
    hosts.apply_analysis_summary(dict(damage(3),snapshot=None));app.processEvents()
    assert not window.canvas._rects[0][1].data['rows']
    assert window.height()<=height
    assert window.width()<=width
    assert window.height()>=window.minimumHeight()


@pytest.mark.parametrize('theme',['light','dark','transparent','endfield'])
def test_combo_four_slots_styles_state_colors_and_width(hosts,app,theme):
    window=show(hosts,app,'combo_skill',theme=theme)
    hosts.apply_combo_snapshot(combo());app.processEvents()
    circular=window.size()
    layout=window.canvas._rects[0][1]
    assert [s['status'] for s in layout.data['slots']]==['cooldown','ready','dead','empty']
    assert layout.data['status']=='沿用上次状态'
    assert 'CD 就绪' in layout.data['slots'][1]['tip']
    assert '沿用上次识别' in layout.data['slots'][0]['tip']
    window.apply_entry(with_template_value(window.entry,'display_style','bars'));app.processEvents()
    assert window.height()>circular.height() and window.size()!=circular
    before_height=window.height();before_scale=window.canvas.scale
    window.resize(window.width()+120,window.height());app.processEvents()
    assert window.height()==before_height
    assert window.canvas.scale==pytest.approx(before_scale)
    width=window.width()
    window.resize(width,round(window.height()*1.2));app.processEvents()
    assert window.canvas.scale>before_scale and window.width()==width
    assert window.grab().save(str(EVIDENCE/f'native-combo-bars-{theme}.png'))
    window.apply_entry(with_template_value(window.entry,'display_style','circles'));app.processEvents()
    assert not window.canvas.bars
    assert window.grab().save(str(EVIDENCE/f'native-combo-circles-{theme}.png'))
    old=deepcopy(window.canvas.modules[0].snapshot)
    hosts.apply_combo_snapshot(combo(0))
    assert window.canvas.modules[0].snapshot==old
    reset=combo(0,'new');reset['snapshot']['slots']=[]
    hosts.apply_combo_snapshot(reset)
    assert all(s['status']=='unknown' for s in window.canvas._rects[0][1].data['slots'])
    hosts.apply_combo_snapshot(combo(999))
    assert window.canvas.modules[0].snapshot['slots']==[]


@pytest.mark.parametrize('shape',['rectangle','rounded'])
def test_uid_black_cover_and_close_button(hosts,app,shape):
    window=show(hosts,app,'uid_mask',shape=shape)
    window.resize(220,40);app.processEvents()
    image=window.canvas.grab().toImage()
    assert image.pixelColor(image.width()//2,image.height()//2).name()=='#000000'
    assert window.canvas.uid_only and window.content_size is None
    before=window.close_button.grab().toImage()
    window.close_button._hovered=True;window.close_button.update()
    assert window.close_button.grab().toImage()!=before
    window.close_button.click();app.processEvents()
    assert window.isVisible() and window.windowOpacity()==0
    assert hosts._entries[window.entry.id].hidden


def test_hidden_canvas_keeps_painting_without_recreation(hosts,app):
    window=show(hosts,app)
    hwnd=int(window.winId())
    saved=hosts._entries[window.entry.id]
    hosts.apply_entry(replace(saved,hidden=True))
    hosts.apply_analysis_summary(damage());app.processEvents()
    window.canvas.grab()
    assert window.canvas.paint_revision==window.canvas.layout_revision
    assert window.isVisible() and window.windowOpacity()==0 and int(window.winId())==hwnd
    hosts.apply_entry(replace(hosts._entries[saved.id],hidden=False))
    assert window.desktop_visible and int(window.winId())==hwnd


def test_gui_combo_setting_persists_and_damage_multi_instance_is_independent(main_window,app):
    window=main_window
    current=entry(id='combo',enabled=True,source_value='combo_skill')
    window.app_config.overlays.append(current);window.overlay_manager.apply_entry(current)
    window._refresh_overlay_views()
    page=window.overlay_page
    page.overlay_list.setCurrentRow(next(i for i in range(page.overlay_list.count()) if page.overlay_list.item(i).data(Qt.ItemDataRole.UserRole)=='combo'))
    page=window.overlay_page
    page.setting_widgets['display_style'].setCurrentIndex(1);app.processEvents()
    host=window.overlay_manager._windows['combo']
    assert host.canvas.bars
    assert next(e for e in load_app_config(window.config_path).overlays if e.id=='combo').template_settings['display_style']=='bars'
    window.overlay_manager.apply_entry(entry(id='a',enabled=True,bar_mode='dps'))
    window.overlay_manager.apply_entry(with_template_value(entry(id='b',enabled=True),'bar_mode','rdps'))
    assert window.overlay_manager._windows['a'].canvas.modules[0].settings['bar_mode']=='dps'
    assert window.overlay_manager._windows['b'].canvas.modules[0].settings['bar_mode']=='rdps'


def test_damage_defaults_to_rdmg_and_keeps_explicit_dmg_choice(hosts, app):
    from endfield_pcap.gui.config import _overlay_entry_from_dict, _overlay_entry_to_dict
    from endfield_pcap.overlays.native.damage import DamageModule
    from endfield_pcap.overlays.templates import template_for

    window=show(hosts,app)
    hosts.apply_analysis_summary(damage());app.processEvents()
    layout=window.canvas._rects[0][1]
    assert layout.data['metric']=='total_rd'
    assert [row['player']['total_rd'] for row in layout.data['rows']]==[800,200]
    setting=next(s for s in template_for(window.entry).settings if s['key']=='bar_mode')
    assert setting['default']=='rdps'
    payload=_overlay_entry_to_dict(window.entry)
    payload.pop('bar_mode')
    assert _overlay_entry_from_dict(payload).bar_mode=='rdps'
    # A composed skin without a mode declaration follows the same default.
    module=DamageModule();module.receive(damage())
    assert module.measure().data['metric']=='total_rd'
    window.apply_entry(with_template_value(window.entry,'bar_mode','dps'))
    layout=window.canvas._rects[0][1]
    assert layout.data['metric']=='total_damage'
    assert [row['player']['total_damage'] for row in layout.data['rows']]==[800,200]
    assert _overlay_entry_from_dict(_overlay_entry_to_dict(window.entry)).bar_mode=='dps'


@pytest.mark.parametrize('theme',['light','dark','transparent','endfield'])
@pytest.mark.parametrize('style',['circles','bars'])
@pytest.mark.parametrize('avatars',['on','off'])
def test_combo_ready_has_green_background_across_entire_slot(app, theme, style, avatars):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from endfield_pcap.overlays.native.combo import ComboModule

    module=ComboModule()
    module.apply_config(dict(theme=theme,display_style=style,show_character_avatars=avatars),{})
    message=combo();module.receive(message)
    layout=module.measure()
    def render():
        image=QImage(round(layout.size.width()),round(layout.size.height()),QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter=QPainter(image)
        module.paint(painter,QRectF(0,0,layout.size.width(),layout.size.height()),layout,1)
        painter.end()
        return image
    ready=render()
    area=layout.hits[1][0]
    # Points in both upper and lower quarters, away from the ring/bar/text.
    for fraction in (.25,.75):
        pixel=ready.pixelColor(round(area.left()+7),round(area.top()+area.height()*fraction))
        assert pixel.green()>pixel.red()+20 and pixel.green()>pixel.blue()+20
        assert pixel.alpha()>=110
    # A successful cooldown observation must immediately remove the ready fill.
    message=combo(2);message['snapshot']['slots'][1]['status']='cooldown'
    module.receive(message);layout=module.measure()
    cooldown=render()
    assert cooldown.pixelColor(round(area.left()+7),round(area.top()+area.height()*.75)).alpha()==0
    message=combo(3);message['snapshot']['slots'][1]['held']=True
    module.receive(message);layout=module.measure()
    assert render().copy(area.toRect())==ready.copy(area.toRect())
