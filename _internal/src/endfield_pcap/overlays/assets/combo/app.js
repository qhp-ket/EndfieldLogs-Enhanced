(function () {
  const query = new URLSearchParams(window.location.search);
  const inProcess = query.get("snapshotTransport") === "inprocess";
  const rows = document.getElementById("comboRows");
  const status = document.getElementById("comboStatus");
  const state = { streamId: null, sequence: -1, snapshot: null, connected: inProcess };
  const retiredStreams = new Set();
  let ws = null;
  let reconnectTimer = null;

  function element(className, text) {
    const node = document.createElement("div");
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function render() {
    const slots = state.snapshot && state.snapshot.slots || [];
    status.textContent = !state.connected ? "连接断开" : slots.some((slot) => slot.battle_inst_id)
      ? "触发 + 配置 · 估算" : "估算 · 等待队伍";
    rows.replaceChildren();
    for (let index = 0; index < 4; index++) {
      const slot = slots[index] || {};
      const known = ["cooldown", "ready"].includes(slot.status) &&
        typeof slot.remaining_ms === "number" && Number.isFinite(slot.remaining_ms);
      const row = element(`combo-row ${!state.connected ? "disconnected" : known ? slot.status : "unknown"}`);
      if (known && slot.status === "cooldown" && slot.remaining_ms <= slot.notice_ms) row.className += " notice";
      const bar = element("combo-progress");
      // Geometry only. Remaining time is replaced from the publisher; the
      // browser never starts, restarts or advances a cooldown itself.
      bar.style.width = `${known && state.connected ? slot.total_ms > 0
        ? Math.max(0, Math.min(100, (1 - slot.remaining_ms / slot.total_ms) * 100)) : 100 : 0}%`;
      const content = element("combo-content");
      const remaining = !state.connected ? "断开" : !known ? "未知" : slot.status === "ready"
        ? "READY*" : `${(slot.remaining_ms / 1000).toFixed(1)}s`;
      content.append(element("combo-name", slot.name || `角色 ${index + 1}`), element("combo-remaining", remaining));
      row.append(bar, content);
      row.title = known ? "基于抓包触发及官网版配置估算；READY 不代表满足连携释放条件" : "尚未观察到该角色的连携触发";
      rows.appendChild(row);
    }
  }
  function accept(message) {
    if (!message || message.type !== "combo_snapshot" || message.schema_version !== 1 ||
        typeof message.stream_id !== "string" || !message.stream_id ||
        !Number.isSafeInteger(message.sequence) || message.sequence < 0 ||
        !message.snapshot || !Array.isArray(message.snapshot.slots) ||
        message.snapshot.slots.length !== 4) return;
    if (retiredStreams.has(message.stream_id)) return;
    if (message.stream_id === state.streamId && message.sequence <= state.sequence) return;
    if (state.streamId && message.stream_id !== state.streamId) retiredStreams.add(state.streamId);
    state.streamId = message.stream_id;
    state.sequence = message.sequence;
    state.snapshot = message.snapshot;
    render();
  }
  function connect() {
    const socket = new WebSocket(`ws://127.0.0.1:${query.get("wsPort") || "29325"}/ws`);
    ws = socket;
    socket.onopen = () => { if (ws === socket) { state.connected = true; render(); } };
    socket.onmessage = (event) => {
      if (ws !== socket) return;
      try { accept(JSON.parse(event.data)); }
      catch (error) { console.error("combo snapshot parse error", error); }
    };
    socket.onclose = () => {
      if (ws !== socket) return;
      state.connected = false;
      render();
      reconnectTimer = window.setTimeout(connect, 1500);
    };
    socket.onerror = () => socket.close();
  }
  if (inProcess) window.addEventListener("endfield-combo-snapshot", (event) => accept(event.detail));
  else connect();
  window.addEventListener("beforeunload", () => {
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    const socket = ws;
    ws = null;
    if (socket) socket.close();
  });
  render();
})();
