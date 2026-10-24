const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const message = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(path.join(__dirname, '../../../_internal/src/endfield_pcap/overlays/assets/combo/app.js'), 'utf8');
class Element {
  constructor() { this.children = []; this.style = {}; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; }
}
for (const inProcess of [false, true]) {
  const refs = new Map(), listeners = new Map(), sockets = [], timers = [];
  const window = {
    location: {search: inProcess ? '?snapshotTransport=inprocess' : '?wsPort=29325'},
    addEventListener: (key, fn) => listeners.set(key, fn),
    setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout() {},
  };
  class Socket {
    constructor() { sockets.push(this); }
    close() { this.onclose(); }
  }
  vm.runInNewContext(source, {window, URLSearchParams, console, WebSocket: Socket,
    document: {getElementById: id => {if (!refs.has(id)) refs.set(id, new Element()); return refs.get(id);},
      createElement: () => new Element()}});
  const send = msg => inProcess ? listeners.get('endfield-combo-snapshot')({detail: msg})
    : sockets.at(-1).onmessage({data: JSON.stringify(msg)});
  const remaining = () => refs.get('comboRows').children.map(row => row.children[1].children[1].textContent);
  assert.equal(sockets.length, inProcess ? 0 : 1);
  if (!inProcess) sockets[0].onopen();
  assert.deepEqual(remaining(), ['未知', '未知', '未知', '未知']);
  send(message);
  assert.deepEqual(remaining(), ['20.0s', '未知', '未知', '未知']);
  send(message); send(message);
  assert.equal(remaining()[0], '20.0s');
  assert.equal(timers.length, 0, 'client must not run its own cooldown timer');
  send({type: 'event_batch', events: [{type: 'BattleOpTriggerAction'}]});
  assert.equal(remaining()[0], '20.0s', 'raw events cannot start a second client-side timer');
  const ready = structuredClone(message);
  ready.sequence++;
  ready.snapshot.slots[0].status = 'ready'; ready.snapshot.slots[0].remaining_ms = 0;
  send(ready);
  assert.equal(remaining()[0], 'READY*');
  const reset = structuredClone(ready);
  reset.sequence++;
  reset.snapshot.slots.forEach(row => {row.status = 'unknown'; row.remaining_ms = null;});
  send(reset); send(message);
  assert.equal(remaining()[0], '未知', 'stale snapshot cannot undo a reset');
  send({...message, stream_id: 'new-service', sequence: 0});
  send({...reset, sequence: 999});
  assert.equal(remaining()[0], '20.0s', 'retired stream cannot overwrite new state');
  if (!inProcess) {
    sockets[0].close();
    assert.equal(remaining()[0], '断开');
    timers[0](); sockets[1].onopen();
    send({...ready, stream_id: 'new-service', sequence: 1});
    assert.equal(remaining()[0], 'READY*');
  }
}
console.log('Combo replacement, unknown/reset, reconnect and transport checks passed.');
