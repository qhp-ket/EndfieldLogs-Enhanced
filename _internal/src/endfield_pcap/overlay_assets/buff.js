(() => {
  const params = new URLSearchParams(location.search);
  const rows = document.getElementById("buffRows"), status = document.getElementById("buffStatus");
  let settings = {targets: "characters", durations: "all", layout: "list"};
  let message = null, connected = params.get("snapshotTransport") === "inprocess", socket, retry;
  const retired = new Set();
  function node(cls, text) {
    const el = document.createElement("div"); el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function render() {
    const offset = rows.scrollTop;
    rows.replaceChildren(); rows.dataset.layout = settings.layout;
    const buffs = (message?.snapshot.buffs || []).filter(b =>
      (settings.targets === "all" || String(b.owner).startsWith("chr_")) &&
      (settings.durations !== "timed" || b.duration_ms !== null));
    status.textContent = connected ? `${buffs.length} 项 · 时长估算` : "连接断开";
    for (const b of buffs) {
      const row = node(`buff-row ${b.status}`);
      row.title = `${b.buff_id}\n实例 ${b.uid}\n来源 ${b.source}\n计时依据 ${b.duration_source}；未校正暂停/时间膨胀`;
      const detail = node("buff-detail");
      const time = !connected ? "断开" : b.enabled === false ? "未启用" : b.status === "indefinite" ? "无固定时长" :
        b.remaining_ms === null ? "时长未知" : b.remaining_ms === 0 ? "估计已到期" : `${(b.remaining_ms / 1000).toFixed(1)}s*`;
      detail.append(node("buff-owner", b.owner), node("buff-time", time));
      row.append(node("buff-name", b.buff_id), detail);
      if (b.duration_ms > 0) {
        const bar = node("buff-bar"); bar.style.width = `${Math.max(0, Math.min(100, b.remaining_ms / b.duration_ms * 100))}%`;
        row.append(bar);
      }
      rows.append(row);
    }
    if (!buffs.length) rows.append(node("buff-empty", connected ? "暂无符合筛选的 BUFF 观测" : "等待连接"));
    rows.scrollTop = offset;
  }
  function accept(next) {
    if (next?.type !== "buff_snapshot" || next.schema_version !== 1 || typeof next.stream_id !== "string" || !next.stream_id ||
      !Number.isSafeInteger(next.sequence) || next.sequence < 0 || !Array.isArray(next.snapshot?.buffs)) return;
    if (retired.has(next.stream_id) || message?.stream_id === next.stream_id && next.sequence <= message.sequence) return;
    if (message && message.stream_id !== next.stream_id) retired.add(message.stream_id);
    message = next; render();
  }
  window.addEventListener("endfield-overlay-config", e => {settings = {...settings, ...e.detail.settings}; render();});
  window.addEventListener("endfield-buff-snapshot", e => accept(e.detail));
  function connect() {
    const ws = socket = new WebSocket(`ws://127.0.0.1:${params.get("wsPort") || "29325"}/ws`);
    ws.onopen = () => {if (socket === ws) {connected = true; render();}};
    ws.onmessage = e => {if (socket === ws) {try {accept(JSON.parse(e.data));} catch (error) {console.error(error);}}};
    ws.onclose = () => {if (socket === ws) {connected = false; render(); retry = setTimeout(connect, 1500);}};
    ws.onerror = () => ws.close();
  }
  if (params.get("snapshotTransport") !== "inprocess") connect();
  window.addEventListener("beforeunload", () => {clearTimeout(retry); const ws = socket; socket = null; ws?.close();});
  render();
})();
