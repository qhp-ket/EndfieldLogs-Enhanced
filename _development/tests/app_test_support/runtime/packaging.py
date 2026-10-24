from app_test_support.paths import ROOT
import importlib.util

spec = importlib.util.spec_from_file_location('portable_builder', ROOT / '_development/tools/build_portable.py')

builder = importlib.util.module_from_spec(spec)
