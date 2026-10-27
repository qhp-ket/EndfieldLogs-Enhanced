"""Declarative skins derive subscriptions; migration preserves valid entries."""
from dataclasses import replace
import json
from pathlib import Path
import pytest
from PySide6.QtGui import QImage, QColor
from app_test_support.ui.window import entry
from endfield_pcap.models import OverlaySourceType, OverlayGeometry
from endfield_pcap.overlays.templates import read_template, template_for, template_values, with_template_value
from endfield_pcap.overlays.manager import OverlayManager
from endfield_pcap.gui.config import default_overlay_entries, load_app_config, save_app_config, _overlay_entry_to_dict


def skin(tmp_path, **changes):
    data=dict(schema_version=2,name='组合皮肤',modules=[dict(type='damage'),dict(type='combo_skill'),dict(type='uid_mask')],
        layout=dict(direction='vertical'),theme=dict(background='transparent',foreground='#ffffff',spacing=12,padding=4))
    data.update(changes)
    path=tmp_path/'skin.json';path.write_text(json.dumps(data),encoding='utf8')
    return entry(source_type=OverlaySourceType.FILE,source_value=str(path)),data


@pytest.mark.parametrize('direction',['horizontal','vertical'])
def test_composed_skin_layout_fixed_subscriptions_and_local_image(tmp_path,app,direction):
    image=QImage(16,16,QImage.Format.Format_ARGB32);image.fill(QColor('#203040'))
    image.save(str(tmp_path/'background.png'))
    current,data=skin(tmp_path,layout={'direction':direction},theme={'image':'background.png','border_width':1,'radius':8})
    assert template_for(current).subscriptions==('analysis_summary','combo_snapshot')
    demand=[];manager=OverlayManager(1,use_in_process_snapshots=True,on_analysis_requirement=demand.append)
    try:
        manager.apply_entry(replace(current,enabled=True));app.processEvents()
        window=manager._windows[current.id]
        assert len(window.canvas.modules)==3
        rects=[r for r,_ in window.canvas._rects]
        if direction=='horizontal': assert rects[0].right()<rects[1].left()<rects[2].left()
        else: assert rects[0].bottom()<rects[1].top()<rects[2].top()
        assert demand[-1]==frozenset({'analysis_summary','combo_snapshot'})
        assert not window.grab().isNull()
    finally:
        manager.close_all();app.processEvents()


@pytest.mark.parametrize('changes',[
    {'schema_version':1}, {'entry':'index.html'}, {'subscriptions':['analysis_snapshot']},
    {'modules':[{'type':'buff'}]}, {'modules':[{'type':'input'}]}, {'modules':[{'type':'url'}]},
    {'modules':[{'type':'damage','script':'print(1)'}]}, {'layout':{'direction':'grid'}},
    {'theme':{'image':'https://example.invalid/a.png'}}, {'theme':{'image':'../private.png'}},
    {'theme':{'spacing':float('inf')}}, {'theme':{'background':'url(private)'}},
    {'modules':[{'type':'damage','setting_bindings':{'bar_mode':'missing'}}]},
    {'window':{'default_width':False}}, {'modules':[]},
    {'modules':[{'type':'damage','settings':{'columns':7}}]},
    {'modules':[{'type':'damage','settings':{'avatar_size_percent':True}}]},
    {'modules':[{'type':'combo_skill','settings':{'display_style':'html'}}]},
    {'modules':[{'type':'damage','setting_bindings':{'columns':'bad'}}],
     'settings':[{'key':'bad','type':'slider','min':0,'max':10,'default':1}]},
])
def test_invalid_or_executable_skin_fields_are_rejected(tmp_path,changes):
    current,_=skin(tmp_path,**changes)
    with pytest.raises((ValueError,KeyError,TypeError)):
        read_template(Path(current.source_value))
    assert template_for(current).error


def test_declarations_and_module_bindings_normalize_and_isolate_instances(tmp_path,app):
    current,_=skin(tmp_path,modules=[dict(type='damage',setting_bindings={'avatar_size_percent':'size'})],layout={'direction':'single'},
        settings=[dict(key='size',type='slider',min=50,max=300,default=100)])
    original=template_for(current)
    for value,expected in [(175,175),(0,50),(999,300),('bad',100),(True,100)]:
        assert template_values(with_template_value(current,'size',value))=={'size':expected}
    first=template_for(current);first.modules.clear()
    assert template_for(current).modules==original.modules
    manager=OverlayManager(1,use_in_process_snapshots=True)
    try:
        manager.apply_entry(replace(current,enabled=True))
        manager.apply_entry(replace(with_template_value(current,'size',175),id='second',enabled=True))
        assert manager._windows[current.id].canvas.modules[0].settings['avatar_size_percent']==100
        assert manager._windows['second'].canvas.modules[0].settings['avatar_size_percent']==175
    finally:
        manager.close_all();app.processEvents()


def test_migration_filters_before_parsing_preserves_order_geometry_and_user_files(tmp_path):
    valid,_=skin(tmp_path)
    invalid=tmp_path/'old.json';invalid.write_text(json.dumps(dict(schema_version=1,entry='old.html')),encoding='utf8')
    html=tmp_path/'old.html';html.write_text('personal template',encoding='utf8')
    builtins=[replace(e,geometry=OverlayGeometry(20+i,30,450,200),font_scale=1.4,hidden=True,
                      locked=True,click_through=True,template_settings={'custom':'saved'}) for i,e in enumerate(default_overlay_entries())]
    rows=[_overlay_entry_to_dict(e) for e in [builtins[2],builtins[0],valid,builtins[1]]]
    rows += [dict(id='url',source_type='url',source_value='https://example.invalid'),
        dict(id='html',source_type='file',source_value=str(html)),
        dict(id='old',source_type='file',source_value=str(invalid)),
        dict(id='buff',source_type='builtin',source_value='buff'),dict(id='input',source_type='builtin',source_value='input')]
    path=tmp_path/'settings.json'
    path.write_text(json.dumps(dict(overlays=rows,battle_analysis_view='web')),encoding='utf8')
    config=load_app_config(path)
    assert [e.id for e in config.overlays]==[builtins[2].id,builtins[0].id,valid.id,builtins[1].id]
    assert config.overlay_migration_count==5
    fields=lambda e:(e.geometry,e.hidden,e.locked,e.click_through,e.font_scale,e.template_settings)
    assert [fields(e) for e in config.overlays if e.source_type==OverlaySourceType.BUILTIN]==[fields(e) for e in [builtins[2],builtins[0],builtins[1]]]
    save_app_config(config,path)
    assert load_app_config(path).overlay_migration_count==0
    assert 'battle_analysis_view' not in json.loads(path.read_text(encoding='utf8'))
    assert html.read_text(encoding='utf8')=='personal template' and invalid.is_file()


def test_industrial_skin_persists_and_uses_existing_content_geometry(tmp_path, app):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    from endfield_pcap.overlays.native.damage import DamageModule
    from endfield_pcap.gui.config import AppConfig, default_service_config
    current = with_template_value(entry(), 'theme', 'endfield')
    path = tmp_path/'settings.json'
    config = AppConfig(service=default_service_config())
    config.overlays = [current]
    save_app_config(config, path)
    restored = load_app_config(path).overlays[0]
    assert restored.overlay_theme == 'endfield'
    assert template_values(restored)['theme'] == 'endfield'
    module = DamageModule()
    module.apply_config({'theme':'light'}, {})
    original = module.measure()
    module.apply_config({'theme':'endfield'}, {})
    layout = module.measure()
    assert original.data['rows'] == layout.data['rows']
    assert original.data['status'] == layout.data['status']
    assert layout.data['strong_font'].bold()
    assert layout.data['stat_font'].family() == 'Consolas'
    image = QImage(round(layout.size.width()), round(layout.size.height()), QImage.Format.Format_ARGB32)
    image.fill(QColor('#f0f0ec'))
    painter = QPainter(image)
    module.paint(painter, QRectF(0, 0, image.width(), image.height()), layout, 1.)
    painter.end()
    assert image.pixelColor(4, 10).name() == '#101111'
    footer = image.pixelColor(image.width()-8, image.height()-5)
    assert footer.red() > 180 and footer.green() > 170 and footer.blue() < 30
    assert image.pixelColor(4, round(layout.data['header'])+10).name() == '#f0f0ec'
    # Imported v2 skins use the same preset, without a browser or extra images.
    imported, _ = skin(tmp_path, modules=[{'type':'damage','settings':{'theme':'endfield'}}],
                       layout={'direction':'single'})
    assert not template_for(imported).error
