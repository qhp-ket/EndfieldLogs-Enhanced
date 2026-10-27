"""Native feature resources survive relocation and portable copying."""
from app_test_support.paths import ROOT
import pytest
from endfield_pcap.overlays.templates import ASSETS, read_template
from endfield_pcap.runtime.paths import bundle_root
from app_test_support.runtime.packaging import builder

PACKAGE = ROOT / '_internal/src/endfield_pcap'

@pytest.mark.parametrize('kind,module', [('damage','damage'),('combo','combo_skill'),('uid_mask','uid_mask')])
def test_builtin_feature_local_template_references(kind,module):
    template = read_template(ASSETS / kind / 'template.json')
    assert template.modules[0]['type'] == module
    assert not template.error

def test_portable_copy_preserves_nested_gui_and_overlay_resources(tmp_path):
    staged = tmp_path / 'relocated sources' / 'endfield_pcap'
    builder.copy_tree(PACKAGE, staged)
    for kind in ['damage', 'combo', 'uid_mask']:
        template = read_template(staged / 'overlays/assets' / kind / 'template.json')
        assert template.modules
    assert (staged / 'overlays/native/canvas.py').is_file()
    assert (staged / 'data/assets/skill_names_zh.json').is_file()
    assert not list(staged.rglob('*.pyc'))
    assert not list((staged/'overlays/assets').rglob('*.html'))
    assert not (staged/'gui/battle/assets').exists()

def test_source_runtime_root_is_independent_of_feature_depth():
    assert bundle_root() == PACKAGE.parents[1]
