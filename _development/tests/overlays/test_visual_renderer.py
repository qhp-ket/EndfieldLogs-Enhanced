"""Renderer protocol checks independent of the retired capture CD algorithm."""
import subprocess
from app_test_support.paths import TESTS


def test_combo_visual_renderer_replaces_and_isolates_streams():
    result=subprocess.run(['node',str(TESTS/'overlays/combo_snapshot.test.cjs')],
                          text=True,capture_output=True,encoding='utf8',timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
