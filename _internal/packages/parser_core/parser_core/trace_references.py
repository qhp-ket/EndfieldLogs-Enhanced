"""Per-volume definitions. References never merge observations or infer identities."""
from parser_core.trace_schema import INSTANCE_FIELDS, OPAQUE_FIELDS


class TraceReferences:
    def __init__(self):
        self.values = {kind: {} for kind in ('entity', 'template')}
        self.indices = {kind: {} for kind in self.values}

    def define(self, value):
        kind, ref = value.get('kind'), value.get('ref')
        if kind not in self.values or type(ref) is not int or ref != len(self.values[kind]) + 1:
            raise ValueError('Invalid or duplicate trace definition')
        text = value.get('id' if kind == 'entity' else 'template')
        if not isinstance(text, str) or not text or text in self.indices[kind]:
            raise ValueError('Invalid or repeated trace definition value')
        if kind == 'entity' and (not text.isascii() or not text.isdecimal()):
            raise ValueError('Invalid entity definition')
        self.values[kind][ref] = text
        self.indices[kind][text] = ref

    def encode(self, value, emit, key=''):
        if key in OPAQUE_FIELDS:
            return value
        kind = 'entity' if key in INSTANCE_FIELDS else 'template' if key in ('skill', 'template', 'weapon_template') else None
        if kind and isinstance(value, str) and value:
            ref = self.indices[kind].get(value)
            if ref is None:
                ref = len(self.values[kind]) + 1
                definition = {'type': 'definition', 'kind': kind, 'ref': ref,
                              'id' if kind == 'entity' else 'template': value}
                self.define(definition)
                emit(definition)
            return {kind + '_ref': ref}
        if isinstance(value, dict):
            return {key: self.encode(child, emit, key) for key, child in value.items()}
        if isinstance(value, list):
            return [self.encode(child, emit) for child in value]
        return value

    def decode(self, value, key=''):
        if key in OPAQUE_FIELDS:
            return value
        if isinstance(value, dict):
            for kind in self.values:
                if set(value) == {kind + '_ref'} and (key in INSTANCE_FIELDS if kind == 'entity' else key in ('skill', 'template', 'weapon_template')):
                    ref = value[kind + '_ref']
                    if type(ref) is not int or ref not in self.values[kind]:
                        raise ValueError('Undefined trace reference')
                    return self.values[kind][ref]
            return {key: self.decode(child, key) for key, child in value.items()}
        if isinstance(value, list):
            return [self.decode(child) for child in value]
        return value
