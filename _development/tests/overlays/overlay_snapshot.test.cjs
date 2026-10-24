const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const message = JSON.parse(fs.readFileSync(0, 'utf8'));
const script = fs.readFileSync(path.join(__dirname,
  '../../../_internal/src/endfield_pcap/overlays/assets/damage/app.js'), 'utf8');

class Element {
  constructor() {
    this.children = []; this.style = {}; this.textContent = ''; this.className = '';
    this.classes = new Set();
    this.classList = { toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name) };
  }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; }
}

function mount(inProcess, token = '') {
  const refs = new Map(); const listeners = new Map(); const sockets = []; const timers = [];
  const window = {
    location: { search: (inProcess ? '?snapshotTransport=inprocess' : '?wsPort=29325') +
      (token ? `&wsToken=${encodeURIComponent(token)}` : '') },
    addEventListener(name, handler) { listeners.set(name, handler); },
    setTimeout(fn) { timers.push(fn); return timers.length; },
    clearTimeout() {},
  };
  class Socket {
    constructor(url) { this.url = url; sockets.push(this); }
    close() { if (this.onclose) this.onclose(); }
  }
  vm.runInNewContext(script, {
    window, URLSearchParams, console, WebSocket: Socket,
    document: { documentElement: {style: {setProperty() {}}}, getElementById(id) {
      if (!refs.has(id)) refs.set(id, new Element());
      return refs.get(id);
    }, createElement: () => new Element() },
  });
  return { refs, listeners, sockets, timers,
    send(payload) {
      if (inProcess) listeners.get('endfield-analysis-snapshot')({ detail: payload });
      else sockets.at(-1).onmessage({ data: JSON.stringify(payload) });
    },
  };
}

for (const inProcess of [false, true]) {
  const app = mount(inProcess, 'fixture-token&with spaces');
  assert.equal(app.sockets.length, inProcess ? 0 : 1, 'Qt must not create a localhost WebSocket');
  if (!inProcess) assert.equal(new URL(app.sockets[0].url).searchParams.get('access_token'), 'fixture-token&with spaces');
  if (!inProcess) app.sockets[0].onopen();
  const text = id => app.refs.get(id).textContent;
  const rowNumbers = () => app.refs.get('rows').children.map(row => ({
    damage: row.children[2].textContent,
    rate: row.children[3].textContent,
    rdamage: row.children[4].textContent,
    rrate: row.children[5].textContent,
    crit: row.children[1].children[1].textContent,
    bar: row.children[0].style.width,
  }));
  app.send(message);
  assert.equal(text('totalDamage'), '760');
  assert.equal(text('totalDps'), '380');
  assert.equal(text('combatTime'), '00:00:02');
  assert.equal(rowNumbers()[0].damage, '760');
  assert.equal(rowNumbers()[0].rate, '100%');
  assert.equal(rowNumbers()[0].rdamage, '640');
  assert.equal(rowNumbers()[0].rrate, (640 / 760 * 100).toLocaleString(undefined, {maximumFractionDigits: 1}) + '%');
  assert.equal(rowNumbers()[1].rdamage, '120');
  assert.equal(rowNumbers()[1].crit, 'CRIT —', 'unknown crit must not become zero');
  assert.equal(rowNumbers()[0].crit, 'CRIT 0%');
  assert.equal(rowNumbers()[1].bar, '0%');
  app.listeners.get('endfield-overlay-config')({detail: {barMode: 'rdps'}});
  assert.equal(rowNumbers()[0].bar, '100%');
  assert.equal(rowNumbers()[1].bar, '18.75%');
  assert.match(app.refs.get('columnsHead').children[0].textContent, /rDMG/);
  assert.match(text('footerText'), /暂定/);
  const before = rowNumbers();
  for (let count = 0; count < 3; count++) app.send(message);
  assert.deepEqual(rowNumbers(), before, 'repeated complete snapshots never accumulate');
  app.send({ type: 'event_batch', events: [{ type: 'damage', details: [{ value: 999999 }] }] });
  assert.equal(text('totalDamage'), '760', 'raw diagnostic events cannot change canonical results');
  app.send({ ...message, sequence: message.sequence + 1 });
  assert.deepEqual(rowNumbers(), before, 'new revision still replaces the same numbers');
  app.send({ ...message, sequence: message.sequence + 2, snapshot: null });
  assert.equal(text('totalDamage'), '0');
  assert.equal(app.refs.get('rows').children.length, 0, 'reset clears all prior participants');
  app.send(message);
  assert.equal(text('totalDamage'), '0', 'stale revision cannot resurrect a reset battle');
  app.send({ ...message, stream_id: 'next-service', sequence: 0 });
  assert.equal(text('totalDamage'), '760', 'a restarted service can begin with sequence zero');
  app.send({ ...message, sequence: message.sequence + 100, snapshot: null });
  assert.equal(text('totalDamage'), '760', 'retired stream cannot overwrite the new service');
  if (!inProcess) {
    app.sockets[0].close();
    assert.match(text('footerText'), /连接断开/);
    assert.equal(app.timers.length, 1);
    app.timers[0]();
    app.sockets[1].onopen();
    app.send({ ...message, stream_id: 'next-service', sequence: 1 });
    assert.equal(text('totalDamage'), '760', 'reconnect does not add prior damage');
  }
  app.send({ ...message, stream_id: 'next-service', sequence: 2,
    snapshot: {...message.snapshot, battle: {...message.snapshot.battle, total_damage: 0},
      participants: [{character_name: 'Unknown', total_damage: 0, total_rd: null, crit_rate: null}]}});
  assert.equal(rowNumbers()[0].rate, '—', 'zero team damage has no defined share');
  assert.equal(rowNumbers()[0].rrate, '—');
  assert.equal(rowNumbers()[0].rdamage, '—', 'missing rDMG cannot become zero');
  const reordered = structuredClone(message.snapshot);
  reordered.participants[0].total_rd = 120;
  reordered.participants[1].total_rd = 640;
  app.send({...message, stream_id: 'next-service', sequence: 3, snapshot: reordered});
  assert.equal(rowNumbers()[0].damage, '0', 'rDPS mode sorts by the canonical rDMG');
  assert.equal(rowNumbers()[0].rdamage, '640');
  app.listeners.get('endfield-overlay-config')({detail: {barMode: 'dps'}});
  assert.equal(rowNumbers()[0].damage, '760', 'DMG mode changes chart order without altering values');
  assert.equal(rowNumbers()[0].rdamage, '120');
}
console.log('Overlay canonical replacement checks passed for WebSocket and Qt transports.');

for (const inProcess of [false, true]) {
  const app = mount(inProcess);
  if (!inProcess) {
    assert.match(app.sockets[0].url, /analysis=summary/);
    app.sockets[0].onopen();
  }
  const summary = {...message, type: 'analysis_summary', source_generation: 2, source_revision: 77,
    snapshot: {battle: message.snapshot.battle, participants: message.snapshot.participants,
      quality_summary: message.snapshot.snapshot_quality}};
  app.send(summary);
  const damage = app.refs.get('totalDamage').textContent;
  for (let index = 0; index < 3; index++) app.send(summary);
  assert.equal(app.refs.get('totalDamage').textContent, damage);
  assert.equal(app.refs.get('rows').children.length, message.snapshot.participants.length);
  assert.equal(app.refs.get('rows').children[0].children[2].textContent, '760');
  assert.equal(app.refs.get('rows').children[0].children[4].textContent, '640');
  app.send({...summary, sequence: summary.sequence + 1, source_revision: 78, snapshot: null});
  app.send(summary);
  assert.equal(app.refs.get('totalDamage').textContent, '0');
  assert.equal(app.refs.get('rows').children.length, 0);
  assert.equal(Number(app.refs.get('totalDps').textContent), 0);
}
console.log('Compact summaries replace state and preserve reset isolation.');
