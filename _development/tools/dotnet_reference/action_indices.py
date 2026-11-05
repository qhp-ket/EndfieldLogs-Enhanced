"""Generate per-root action lookup fixtures from a hash-checked Python snapshot."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import random
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[3]
                        / '_internal/dotnet/Specs/Fixtures/action-indices.json')
    args = parser.parse_args()
    relative = '_internal/packages/parser_core/parser_core/effects/action_index.py'
    source = args.reference/relative
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if metadata['files'][relative]['sha256'] != digest:
        raise ValueError('Action index source changed')
    spec = importlib.util.spec_from_file_location('fixed_action_index', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def encode(value):
        if type(value) is int: return {'int': str(value)}
        if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list,tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key):encode(item) for key,item in value.items()}
        return value

    cases = []
    def add(root):
        root = json.loads(json.dumps(root))
        cache = {}
        index = module.indexed_root_actions(root, cache)
        expected = dict(actions=index[1], creations=index[2],
                        same_cached=module.indexed_root_actions(root, cache) is index,
                        distinct_container=not isinstance(root,(dict,list))
                            or module.indexed_root_actions(json.loads(json.dumps(root)), cache) is not index)
        cases.append(dict(name=f'action-indices/{len(cases)}',root=root,expected=encode(expected)))

    creation = 'Beyond.Gameplay.Core.CreateBuffAction.Data'
    for value in (None,0,1,True,False,'',[],{}): add(value)
    for index in (None,True,False,0,1,-1,2**128,1.0,'1'):
        for enabled in (None,True,False,0,1,'true'):
            root = {'serverActionIndex':index,'isEnable':enabled,'$type':creation,
                    'children':[{'serverActionIndex':1,'isEnable':True,'$type':creation},
                                {'serverActionIndex':1,'isEnable':False,'$type':'other'}]}
            add(root)
            add({'wrapper':[root,{'serverActionIndex':1,'isEnable':True,'$type':creation}]})
    add({'first':{'serverActionIndex':1,'isEnable':True,'$type':creation},
         'second':{'serverActionIndex':1,'isEnable':True,'$type':creation}})
    rng = random.Random(527701)
    def tree(depth):
        if depth <= 0: return rng.choice([None,True,False,1,'合成'])
        mode = rng.randrange(3)
        if mode == 0: return [tree(depth-1) for _ in range(rng.randrange(4))]
        if mode == 1:
            result = {'serverActionIndex':rng.choice([None,True,1,2,-1,1.0]),
                      '$type':rng.choice([creation,'other',None]), 'child':tree(depth-1)}
            if rng.randrange(2): result['isEnable'] = rng.choice([True,False,1,None])
            return result
        return {'a':tree(depth-1),'b':tree(depth-1)}
    for index in range(128): add(tree(4))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':')),encoding='utf8')
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases),source_head=metadata['head'],
        dependencies={relative:digest}),indent=2),encoding='utf8')
    print('Action index fixtures:',len(cases))


if __name__ == '__main__':
    main()
