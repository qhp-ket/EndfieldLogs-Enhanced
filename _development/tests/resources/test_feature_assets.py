"""Feature-local resources must survive relocation and portable copying."""
from app_test_support.paths import ROOT
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import pytest
from endfield_pcap.overlays.templates import ASSETS, read_template
from endfield_pcap.runtime.paths import bundle_root
from app_test_support.runtime.packaging import builder

PACKAGE = ROOT / '_internal/src/endfield_pcap'


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'link', 'img'}:
            self.paths.extend(value for key, value in attrs if key in {'src', 'href'} and value)


def assert_local_references(entry):
    parser = References()
    parser.feed(entry.read_text(encoding='utf8'))
    for ref in parser.paths:
        url = urlsplit(ref)
        if url.scheme == 'qrc':
            continue
        assert not url.scheme and not url.netloc, f'Unexpected remote dependency: {ref}'
        assert (entry.parent / unquote(url.path)).is_file(), (entry, ref)


@pytest.mark.parametrize('kind', ['damage', 'buff', 'combo', 'uid_mask'])
def test_builtin_feature_local_template_references(kind):
    template = read_template(ASSETS / kind / 'template.json')
    assert template.entry.parent == ASSETS / kind
    assert_local_references(template.entry)


def test_portable_copy_preserves_nested_gui_and_overlay_resources(tmp_path):
    staged = tmp_path / 'relocated sources' / 'endfield_pcap'
    builder.copy_tree(PACKAGE, staged)
    for kind in ['damage', 'buff', 'combo', 'uid_mask']:
        template = read_template(staged / 'overlays/assets' / kind / 'template.json')
        assert_local_references(template.entry)
    assert_local_references(staged / 'gui/battle/assets/index.html')
    assert (staged / 'overlays/assets/shared/host_bridge.js').is_file()
    assert (staged / 'data/assets/skill_names_zh.json').is_file()
    assert not list(staged.rglob('*.pyc'))


def test_source_runtime_root_is_independent_of_feature_depth():
    assert bundle_root() == PACKAGE.parents[1]
