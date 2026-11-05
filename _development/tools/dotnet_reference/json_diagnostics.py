"""Pin Python JSON parse diagnostics used by keyword packet evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import random
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[3]
                        / '_internal/dotnet/Specs/Fixtures/json-diagnostics.json')
    args = parser.parse_args()
    inputs = ['', ' ', '{', '[', '{}[]', 'null true', '{bad}', '{"x" 1}', '{"x":}',
              '{"x":1,}', '[1,]', '{"x":1.}', '{"x":1e+}', '{"x":-}', '"\\u1"',
              '"\\uZZZZ"', '"\\q"', '"abc', '"abc\\', '"a\nb"', '\ufeff{}']
    for token in ('1.', '1e', '1E+', '1E-', '-', '+1', '01', '-01', 'NaNx', 'Infinityx',
                  'None', 'True', 'False', 'nul', 'tru', 'fals', '١', '\u00a0', '"\\u12x4"'):
        inputs.extend([token, '[1,' + token + ']', '{"x":' + token + '}'])
    for prefix in ('', ' ', '\r\n', '\n\n  '):
        for token in ('{', '[1,  ]', '{"x":1,  }', '{"x"\n1}', '"x\u0000y"'):
            inputs.append(prefix + token)
    for literal in ('"中文"', '"🟨"', '"\\ud800"', '"\\udc00"', '"a\\nb"'):
        inputs.extend(['[' + literal + ', ]', '{' + literal + ':1, }', literal + ' x'])
    inputs.extend(['{}', '[]', '{"x":-0.0}', '[NaN,Infinity,-Infinity]'])
    rng = random.Random(202610272)
    valid = json.dumps({'a': [1, 2, '中文🟨'], 'b': {'c': True}, 'd': -1.25e-10}, ensure_ascii=False)
    for _ in range(400):
        position = rng.randrange(len(valid) + 1)
        inputs.append(valid[:position] + rng.choice(['', '\x01', ',', ':', ' ', '\\', '"', '}']) + valid[position + rng.randrange(2):])
    cases = []
    for index, text in enumerate(inputs):
        try:
            json.loads(text)
            expected = None
        except ValueError as error:
            expected = str(error)
        cases.append(dict(name='json-diagnostic/' + str(index), input=text, diagnostic=True, expected=expected))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    decoder = Path(json.decoder.__file__)
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases), python=sys.version,
        decoder_sha256=hashlib.sha256(decoder.read_bytes()).hexdigest()), indent=2), encoding='utf8')
    print('JSON diagnostic fixtures:', len(cases))


if __name__ == '__main__':
    main()
