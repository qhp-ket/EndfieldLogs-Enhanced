"""The differential comparator preserves evidence types and reports exact changes."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

path = Path(__file__).resolve().parents[2]/'tools/compare_parser_reference.py'
spec = spec_from_file_location('parser_reference_comparison', path)
comparison = module_from_spec(spec)
spec.loader.exec_module(comparison)


def test_scalar_types_and_signed_zero_are_distinct():
    values = [None, False, 0, 0., -0., '0']
    encoded = [comparison.canonical(value) for value in values]
    assert all(comparison.first_difference(left, right) is not None
               for index, left in enumerate(encoded) for right in encoded[index+1:])


def test_mapping_keys_and_evidence_order_are_preserved():
    assert comparison.canonical({1: 'a'}) != comparison.canonical({'1': 'a'})
    assert comparison.canonical({'b': 2, 'a': 1}) == comparison.canonical({'a': 1, 'b': 2})
    assert comparison.canonical([1, 2]) != comparison.canonical([2, 1])
    assert comparison.canonical((1, 2)) != comparison.canonical([1, 2])


def test_nested_evidence_change_has_an_exact_diagnostic_path():
    before = {'hits': [{'source': 'a', 'value': 100}]}
    after = {'hits': [{'source': 'b', 'value': 100}]}
    assert comparison.first_difference(before, after) == '$/hits/0/source (value)'
    assert comparison.first_difference(before, before) is None


def test_error_contract_is_captured_without_losing_exception_identity():
    def invalid():
        raise ValueError('invalid_fixture')
    assert comparison.outcome(invalid) == {'error': 'ValueError', 'message': 'invalid_fixture'}
