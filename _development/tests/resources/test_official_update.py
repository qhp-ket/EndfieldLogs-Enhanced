import json

import pytest
from app_test_support.paths import ROOT
from endfield_pcap.capture.registry import MessageRegistry
from parser_core.catalog import dungeons


@pytest.mark.parametrize('name', ['SC_ATTACH_SERVER_SKILL', 'SC_UPDATE_SERVER_SKILL', 'SC_DETACH_SERVER_SKILL'])
def test_server_skill_wrappers_decode_the_registered_wire_message(name):
    registry = MessageRegistry(ROOT / '_internal/data')
    cls = registry.load_message_class(name)
    assert cls is not None
    message = cls(inst_id=2**64-1, generation=7)
    if name == 'SC_DETACH_SERVER_SKILL':
        message.del_inst_ids.append(42)
    else:
        message.skills.add(inst_id=42)
    msg_id = next(key for key, value in registry._maps['sc'].items() if value == name)
    decoded, = registry.decode_messages('sc', {'msgid': msg_id}, message.SerializeToString())
    assert decoded.class_name == name and decoded.message == message


def test_contract_server_text_overrides_table_and_keeps_formatted_description(tmp_path, monkeypatch):
    public = tmp_path / 'data/public'
    tables = tmp_path / 'data/local_tables'
    public.mkdir(parents=True)
    tables.mkdir()
    (tables / 'I18nTextTable_CN.json').write_text(json.dumps({'1': '旧名称', '2': '模板 {value}'}), encoding='utf8')
    (public / 'server_texts.json').write_text(json.dumps(dict(source='SC_SYNC_MULTI_LANG_CONFIG', language='CN', texts={'1': '新词条'})), encoding='utf8')
    (public / 'contract_tags.json').write_text(json.dumps(dict(tags={'9': dict(tagId=9, nameTextId=1, descTextId=2,
        romanNumSuffix='Ⅱ', descriptionTemplate='模板 {value}', formattedDescription='模板 30%')})), encoding='utf8')
    monkeypatch.setattr(dungeons, '_repo_root', lambda: tmp_path)
    dungeons._load_contract_tag_texts.cache_clear()
    dungeons._load_contract_tag_catalog.cache_clear()
    try:
        item = dungeons._load_contract_tag_catalog()[9]
        assert item['name'] == '新词条Ⅱ' and item['description'] == '模板 30%'
        (public / 'server_texts.json').write_text('{"source":"SC_SYNC_MULTI_LANG_CONFIG","language":"EN","texts":{"1":"foreign"}}', encoding='utf8')
        dungeons._load_contract_tag_texts.cache_clear()
        assert dungeons._load_contract_tag_texts()['1'] == '旧名称'
    finally:
        dungeons._load_contract_tag_texts.cache_clear()
        dungeons._load_contract_tag_catalog.cache_clear()


def test_latest_runtime_preserves_minghe_supplement_and_separate_uploader_source():
    manifest = json.loads((ROOT / '_internal/data/resource-manifest.json').read_bytes())
    assert manifest['source_release'] == 'ZMDLogs 3.0.14 (2026-11-05)'
    assert manifest['uploader_source']['source_release'] == 'ZMDLogs 3.0.12 (2026-10-16)'
    assert manifest['supplements'][0]['character_ids'] == ['chr_0037_minghe']
    assert 'data/public/server_texts.json' in {row['path'] for row in manifest['files']}
