"""Fixed uploader proof compatibility for C# trace export, using synthetic bytes only."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args()
    metadata=json.loads(args.manifest.read_text(encoding='utf8'))
    relative='_internal/packages/uploader_core/uploader_core/log_integrity.py'
    path=args.reference/relative
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=metadata['files'][relative]['sha256']: raise ValueError('Fixed uploader reference changed')
    spec=importlib.util.spec_from_file_location('fixed_integrity',path)
    reference=importlib.util.module_from_spec(spec); spec.loader.exec_module(reference)
    timestamp='2026-10-29T12:34:56+08:00'
    cases=[]
    def add(name,kind,config,expected):
        cases.append(dict(name=name,kind=kind,config_json=json.dumps(config,ensure_ascii=True),expected=expected))
    samples=[b'',b'a',b'a\n',b'a\r\nb\rc\n',b'\x00\xff\n\x80','中文😀\n末行'.encode(),b'\xef\xbb\xbf[00:00:01.000] HP_V2 #1 hit=1\n']
    rng=random.Random(20261029)
    samples += [rng.randbytes(index*31) for index in range(16)]
    for index,data in enumerate(samples):
        for meta in [{},{'nested':{'中文':[1,0.1,True,None],'😀':{'a':'\n'}},'scope':'full_trace_snapshot'}]:
            proof=reference.build_raw_log_proof(data,file_name='导出.log',exported_at=timestamp,meta=meta)
            add('build', 'build',dict(data=data.hex(),file_name='导出.log',exported_at=timestamp,meta=meta),proof)
            add('verified', 'verify',dict(data=data.hex(),proof=proof),reference.verify_raw_log_proof(data,proof))
            for key,value in [('version','wrong'),('source','wrong'),('byte_size',-1),('line_count',-1),('sha256','wrong'),('chain_sha256','wrong'),('seal_algorithm','wrong'),('local_seal','wrong'),('meta',{'tampered':True})]:
                bad=copy.deepcopy(proof); bad[key]=value
                add('tamper-'+key,'verify',dict(data=data.hex(),proof=bad),reference.verify_raw_log_proof(data,bad))
    raw='[00:00:01.000] HP_V2 #1 hit=12\n中文\n'
    proof=reference.build_raw_log_proof(raw.encode(),file_name='source.log',exported_at=timestamp)
    texts=[raw,raw+reference.RAW_LOG_PROOF_BEGIN_PREFIX+'0\n'+json.dumps(proof)+'\n'+reference.RAW_LOG_PROOF_END+'\n']
    for suffix in ['', '\n', '\r\n']:
        content=raw.rstrip('\n')+suffix
        local=reference.build_raw_log_proof(content.encode(),exported_at=timestamp)
        sep=not content.endswith('\n')
        texts.append(content+('\n' if sep else '')+reference.RAW_LOG_PROOF_BEGIN_PREFIX+str(int(sep))+'\n'+json.dumps(local)+'\n'+reference.RAW_LOG_PROOF_END+'\n')
    for marker in [reference.RAW_LOG_PROOF_BEGIN_PREFIX, reference.RAW_LOG_PROOF_BEGIN_PREFIX+'0\n', reference.RAW_LOG_PROOF_BEGIN_PREFIX+'2\n{}\n'+reference.RAW_LOG_PROOF_END,
                   reference.RAW_LOG_PROOF_BEGIN_PREFIX+'0\n{bad\n'+reference.RAW_LOG_PROOF_END,
                   reference.RAW_LOG_LOADOUT_BEGIN_PREFIX+'0\n{}\n'+reference.RAW_LOG_LOADOUT_END,
                   reference.RAW_LOG_LOADOUT_BEGIN_PREFIX+'1\n{}\n'+reference.RAW_LOG_LOADOUT_END,
                   reference.RAW_LOG_LOADOUT_BEGIN_PREFIX+'0\r\n{}\n'+reference.RAW_LOG_LOADOUT_END]:
        texts.append(raw+marker)
    with tempfile.TemporaryDirectory() as temporary:
        source=Path(temporary)/'source.log'; sidecar=Path(str(source)+'.integrity.json')
        for text in texts:
            for side in [None,proof]:
                source.write_bytes(text.encode('utf8')); sidecar.unlink(missing_ok=True)
                if side is not None: sidecar.write_text(json.dumps(side),encoding='utf8')
                expected=reference.load_raw_log_integrity(str(source))
                if expected['proof_source']=='sidecar': expected['proof_path']='$sidecar'
                add('embedded-and-sidecar','inspect',dict(text=text,sidecar=side),expected)
    fixtures=Path(__file__).resolve().parents[3]/'_internal/dotnet/Specs/Fixtures'
    output=fixtures/'raw-log-proofs.json'
    output.write_text(json.dumps(cases,ensure_ascii=True,separators=(',',':')),encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'],cases=len(cases),dependencies={relative:digest}),indent=2),encoding='utf8')
    print('Raw log proofs:',len(cases))


if __name__=='__main__':main()
