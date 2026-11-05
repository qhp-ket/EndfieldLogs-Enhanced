"""Generate settings/skin contracts from the fixed c9f01b7 application reference."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from dataclasses import replace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--dependency-root', type=Path)
    args = parser.parse_args()
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith('_internal/src/endfield_pcap/') and (relative.endswith('.py') or relative.endswith('/template.json')):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed application reference changed: ' + relative)
            dependencies[relative] = digest
    sys.path.insert(0, str(args.reference / '_internal/src'))
    if args.dependency_root:
        sys.path.append(str(args.dependency_root.resolve()))
    import endfield_pcap.settings.codec as codec
    import endfield_pcap.overlays.templates as skins
    from endfield_pcap.models import OverlayEntry, OverlaySourceType
    root = Path(r'C:\Endfield配置\应用')
    working = Path(r'C:\Endfield配置\工作目录')
    original_defaults = codec.default_service_config
    def defaults():
        return replace(original_defaults(), ws_browser_token='a'*43, log_dir=root/'.dev-gui/logs/battles',
            debug_dir=root/'.dev-gui/debug', rsa_key_txt=root/'_internal/secrets/client_privkey.pem',
            name_index_path=root/'_internal/jsondata/CharacterNameIndex.json')
    codec.default_service_config = defaults
    codec._distribution_root = lambda: root
    # Project the reference process cwd to a stable virtual working root after executing it unchanged.
    reference_working = str(Path.cwd())
    def project(value):
        if isinstance(value, str):
            return value.replace(reference_working + '\\', str(working) + '\\')
        if isinstance(value, list):
            return [project(item) for item in value]
        if isinstance(value, dict):
            return {project(key): project(item) for key,item in value.items()}
        return value
    codec._legacy_config_paths = lambda: []
    codec.read_settings = lambda _: copy.deepcopy(current_payload)
    codec.write_settings = lambda _, payload: saved.update(payload)
    config_cases = []
    current_payload = {}
    saved = {}
    target = Path(__file__).resolve()
    def add(name, payload):
        nonlocal current_payload, saved
        current_payload = payload
        config = codec.load_app_config(target)
        saved = {}
        codec.save_app_config(config, target)
        explicit = {str(item['id']) for item in payload.get('overlays', []) if isinstance(item, dict) and item.get('id')}
        identifiers = {}
        for index, item in enumerate(saved['overlays']):
            if item['id'] not in explicit:
                identifiers[item['id']] = '$generated-' + str(index)
                item['id'] = identifiers[item['id']]
        saved['overlay_restore_ids'] = [identifiers.get(value, value) for value in saved['overlay_restore_ids']]
        token = payload.get('service', {}).get('ws_browser_token')
        import re
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
            saved['service']['ws_browser_token'] = '$generated'
        config_cases.append(dict(name=name, config_json=json.dumps(payload, ensure_ascii=True),
            expected=dict(payload=project(saved), migration_count=config.overlay_migration_count)))
    add('defaults', {})
    for field in ['theme_mode', 'gui_font_percent', 'character_avatar_percent', 'toggle_overlays_hotkey', 'toggle_gui_hotkey',
                  'start_capture_on_launch', 'check_updates_on_start', 'show_character_avatars', 'start_input_recording_on_launch',
                  'ignored_update_version', 'input_settings', 'vision_settings', 'input_log_bindings']:
        for value in [None, False, True, 0, 1, -1, 0.5, 79, 500, '', ' ', ' DARK ', '120', '１_２０', [], {}, {'key': [1, '中文']}]:
            add(field, {field: value})
    for field in ['ws_port', 'ws_browser_token', 'log_dir', 'dll_dir', 'debug_enabled', 'merge_multi_phase_enemy_battles', 'game_exe', 'log_level', 'npcap_device']:
        for value in [None, False, True, 0, -1, 65535, 65536, '２９_３２５', '3.5', 'a'*43, 'x'*129, '', ' ', r'C:\外部\custom', [], {}]:
            add('service-'+field, dict(service={field:value}))
    builtins = [dict(id='damage-id', source_type='builtin', source_value='damage'),
                dict(id='combo-id', source_type='builtin', source_value='combo_skill'),
                dict(id='uid-id', source_type='builtin', source_value='uid_mask')]
    for field in ['opacity', 'scale', 'font_scale', 'enabled', 'hidden', 'locked', 'click_through', 'visible_columns', 'overlay_theme', 'bar_mode', 'template_settings']:
        for value in [None, False, True, 0, -1, 4, .25, '1.75', [], ['rdamage', 'damage', 'rdamage', 'bad'], {}, {'_native_window_scale':1.25}]:
            entries = copy.deepcopy(builtins); entries[0][field] = value
            add('overlay-'+field, dict(overlays=entries))
    for value in ['url','file','builtin',None]:
        for source in ['https://example.test/a', 'old.html', 'buff', 'input', 'DAMAGE', 'combo_skill', 'uid_mask', '']:
            add('overlay-migration', dict(overlays=[dict(id='old', source_type=value, source_value=source)]))
    add('geometry', dict(overlays=[dict(builtins[0], geometry=dict(x=-900, y='１２', width=0, height=True))]))
    add('legacy-hidden', dict(overlays=builtins, overlays_visible=False))
    add('restore-filter', dict(overlays=builtins, overlay_restore_ids=['combo-id','bogus','combo-id',1]))
    add('lane-normalization', dict(battle_lane_configs={'chr': [dict(skills=['a','b','a',None]), dict(id='track-0',skills=['c']),dict(id='other',name='选择',skills=['b','c'])], 'empty': [], 'bad': None},
        battle_table_widths={'skills':[0,True,'123.4',2500,-5,None], 'unknown':[100]}))
    old = Path(r'C:\Endfield配置\旧目录')
    for portable in [False, True]:
        for two_anchors in [False, True]:
            service = dict(rsa_key_txt=str(old/'_internal/secrets/client_privkey.pem'), log_dir=str(old/'logs'), dll_dir=r'C:\游戏\Endfield')
            if two_anchors: service['name_index_path'] = str(old/'_internal/jsondata/CharacterNameIndex.json')
            key = json.dumps([str(old/'logs/trace.log'),0,'time'], ensure_ascii=False)
            add('portable-anchors', dict(service=service, path_base='application' if portable else '', imported_trace_files=[str(old/'logs/trace.log'),str(old/'logs/TRACE.log'),None,'\0bad'], hidden_history_records=[key,'invalid'], input_log_bindings={key:dict(path='unchanged')}))
    add('relative-portable', dict(path_base='application', service=dict(log_dir='logs', rsa_key_txt='_internal/secrets/client_privkey.pem'), imported_trace_files=['logs/a.log','logs/A.log']))

    skin_cases = []
    native = {name: json.loads((skins.ASSETS / skins.BUILTIN_DIRECTORIES.get(name,name) / 'template.json').read_text(encoding='utf8')) for name in ['damage','combo_skill','uid_mask']}
    # read_template handles filesystem and caching; a fixed temporary file provides the actual Python validator.
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        filename = Path(temporary)/'skin.json'
        def skin_add(name, data, settings=None, change=None):
            filename.write_text(json.dumps(data, ensure_ascii=True), encoding='utf8')
            entry = OverlayEntry(id='skin-instance', name='skin', source_type=OverlaySourceType.BUILTIN, source_value='damage',
                enabled=True, locked=False, click_through=False, template_settings=settings or {})
            config = dict(data=data, settings=settings or {}, change=change)
            try:
                skin = skins.read_template(filename)
                if change is not None:
                    # Avoid template_for's builtin default; only the value resolver depends on entry.
                    values = skins.template_values(replace(entry, template_settings={**skins.template_values(entry,skin), change['key']:change['value']}),skin)
                else:
                    values = skins.template_values(entry,skin)
                module_settings = []
                for module in skin.modules:
                    resolved = {**values, **module.get('settings', {})}
                    resolved.update({key: values[target] for key,target in module.get('setting_bindings',{}).items()})
                    resolved['_font_scale'] = entry.font_scale
                    module_settings.append(dict(type=module['type'],settings=resolved))
                expected = dict(valid=True, name=skin.name, subscriptions=list(skin.subscriptions), settings=skin.settings, window=skin.window, modules=skin.modules, layout=skin.layout, theme=skin.theme, values=values,module_settings=module_settings)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                expected = dict(valid=False)
            skin_cases.append(dict(name=name, config_json=json.dumps(config,ensure_ascii=True), expected=expected))
        for name, data in native.items():
            skin_add('builtin-'+name,data)
            for key in ['bar_mode','theme','columns','avatar_size_percent','show_character_avatars','display_style','shape']:
                for value in [None,True,0,49,350,'bad','endfield','off',['rdamage','damage','rdamage']]:
                    skin_add('values-'+name,data,{key:value})
        good = native['damage']
        for key,value in [('schema_version',1),('schema_version',2.0),('schema_version',True),('url','https://example.test'),('modules',[]),('modules',[{'type':'buff'}]),('layout',{'direction':'invalid'}),('theme',{'radius':True}),('theme',{'radius':129}),('theme',{'background':'red'}),('window',{'min_width':True}),('window',{'unknown':1}),('settings',{})]:
            data=copy.deepcopy(good); data[key]=value; skin_add('invalid-or-coercion',data)
        for field, value in [('default',True),('min',49),('max',301),('type','select'),('legacy_field','bar_mode')]:
            data=copy.deepcopy(good); data['settings'][1][field]=value; skin_add('slider-contract',data)
        for module in [{'type':'damage','settings':{'columns':['wrong']}}, {'type':'damage','settings':{'theme':'endfield'}}, {'type':'damage','setting_bindings':{'columns':'bar_mode'}}, {'type':'damage','setting_bindings':{'theme':'missing'}}, {'type':'damage','subscriptions':['full_report']}]:
            data=copy.deepcopy(good); data['modules']=[module]; skin_add('module-contract',data)
        data=copy.deepcopy(good); data['modules'] += [{'type':'combo_skill'},{'type':'uid_mask'}]; data['layout']={'direction':'vertical'}
        skin_add('composition',data)
        skin_add('composition-needs-direction',{**data,'layout':{}})
        data=copy.deepcopy(good)
        data['settings'].append(dict(key='custom_theme',type='select',default='endfield',options=[dict(value='endfield'),dict(value='dark')]))
        data['modules']=[dict(type='damage',settings=dict(theme='transparent'),setting_bindings=dict(theme='custom_theme'))]
        skin_add('explicit-binding-overrides-module-constant',data,dict(custom_theme='dark',theme='light'))
        for key,value in [('theme','endfield'),('columns',['rdamage','damage']),('avatar_size_percent',999)]: skin_add('change',good,change=dict(key=key,value=value))
    fixtures=Path(__file__).resolve().parents[3]/'_internal/dotnet/Specs/Fixtures'
    for name,cases in [('app-settings',config_cases),('native-skins',skin_cases)]:
        output=fixtures/(name+'.json')
        output.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':')),encoding='utf8')
        output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'],cases=len(cases),dependencies=dependencies,
            application_root=str(root),working_directory_projection=str(working)),indent=2),encoding='utf8')
        print(name,len(cases))


if __name__ == '__main__':
    main()
