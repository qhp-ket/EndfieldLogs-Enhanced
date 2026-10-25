const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element {
  constructor(){this.children=[];this.style={setProperty(){}};this.dataset={};this.attrs={};this.textContent='';this.classList={toggle(){}};}
  append(...nodes){this.children.push(...nodes);}
  getAttribute(key){return this.attrs[key];}
  set src(value){this.attrs.src=value;}
}
const refs=new Map(),listeners=new Map();
const window={addEventListener:(name,fn)=>listeners.set(name,fn),endfieldOverlay:{config:{},snapshots:{}}};
const document={body:new Element(),documentElement:new Element(),createElement:()=>new Element(),
  getElementById:id=>{if(!refs.has(id))refs.set(id,new Element());return refs.get(id);}};
const source=fs.readFileSync(path.join(__dirname,'../../../_internal/src/endfield_pcap/overlays/assets/combo/app.js'),'utf8');
vm.runInNewContext(source,{window,document,console});
const send=message=>listeners.get('endfield-combo-snapshot')({detail:message});
const payload=(sequence=1,stream_id='first')=>({type:'combo_snapshot',schema_version:2,stream_id,sequence,
  snapshot:{frame_valid:true,status:'识别中',slots:[{slot:0,status:'cooldown',progress:.5,estimated_remaining_ms:2000}]}});
const rows=refs.get('comboRows').children,values=()=>rows.map(row=>row.children[3].textContent);
assert.equal(rows.length,4);assert.deepEqual(values(),['—','—','—','—']);
send(payload());assert.equal(values()[0],'50% · ≈2.0s');
send({...payload(),snapshot:{frame_valid:true,slots:[]}});assert.equal(values()[0],'50% · ≈2.0s');
send({...payload(2),schema_version:1});assert.equal(values()[0],'50% · ≈2.0s');
const ready=payload(2);ready.snapshot.slots[0].status='ready';ready.snapshot.slots[0].progress=1;
send(ready);assert.equal(values()[0],'CD 就绪');
const held=payload(3);held.snapshot.frame_valid=false;held.snapshot.slots[0]={slot:0,status:'ready',progress:1,held:true,stale:true};
send(held);assert.equal(values()[0],'CD 就绪');assert.equal(rows[0].dataset.status,'ready');
assert.equal(refs.get('comboStatus').textContent,'沿用上次状态');
send({...payload(4),snapshot:{frame_valid:false,slots:[]}});assert.deepEqual(values(),['—','—','—','—']);
send(payload(0,'second'));send(ready);assert.equal(values()[0],'50% · ≈2.0s');
assert.equal(refs.get('comboRows').children[0],rows[0],'updates reuse slot/image nodes');
listeners.get('endfield-overlay-config')({detail:{settings:{display_style:'bars'}}});
assert.equal(document.body.dataset.style,'bars');
assert.equal(rows[0].children[2].children[0].style.width,'50%');
assert.equal(rows[0].children[0].children[2].style.height,'50%');
console.log('Visual v2 replacement, stale/reset, stream isolation and style checks passed.');
