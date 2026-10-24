"""Parser test categories; individual legacy cases declare their own xfail."""
def pytest_configure(config):
    config.addinivalue_line('markers', 'legacy_expectation: retained old contract, with an explicit blocker and exception')
