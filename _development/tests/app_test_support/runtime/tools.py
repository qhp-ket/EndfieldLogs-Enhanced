from app_test_support.paths import ROOT
import importlib.util

def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / '_development/tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
