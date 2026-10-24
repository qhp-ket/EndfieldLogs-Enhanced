from pathlib import Path
TESTS = Path(__file__).resolve().parents[1]
INTERNAL = TESTS.parents[2]
FIXTURES = TESTS / 'fixtures'
