(function () {
  const query = new URLSearchParams(window.location.search);
  const inProcess = query.get("snapshotTransport") === "inprocess";
  const wsUrl = `ws://127.0.0.1:${query.get("wsPort") || "29325"}/ws?analysis=summary`;
  const state = { streamId: null, sequence: -1, snapshot: null, connected: inProcess, error: null, source: null };
  const retiredStreams = new Set();
  let barMode = query.get("barMode") === "rdps" ? "rdps" : "dps";
  const columns = [
    {key: "damage", label: "DMG", className: "row-damage", value: (p) => formatDamage(p.total_damage)},
    {key: "damage_rate", label: "DMG rate", className: "row-rate", value: (p, share) => share(p.total_damage)},
    {key: "rdamage", label: "rDMG", className: "row-rdamage", value: (p) => formatDamage(p.total_rd)},
    {key: "rdamage_rate", label: "rDMG rate", className: "row-rrate", value: (p, share) => share(p.total_rd)},
  ];
  let visibleColumns = query.has("columns") ? query.get("columns").split(",") : columns.map((column) => column.key);
  const refs = Object.fromEntries([
    "totalDamage", "totalDps", "combatTime", "combatIndicator", "rows",
    "emptyState", "footer", "footerText", "columnsHead",
  ].map((id) => [id, document.getElementById(id)]));
  let ws = null;
  let reconnectTimer = null;

  function acceptSnapshot(message) {
    if (!message || !["analysis_snapshot", "analysis_summary"].includes(message.type) || message.schema_version !== 1 ||
        typeof message.stream_id !== "string" || !message.stream_id ||
        !Number.isSafeInteger(message.sequence) || message.sequence < 0 ||
        !(message.snapshot === null || (typeof message.snapshot === "object" && !Array.isArray(message.snapshot)))) {
      return;
    }
    if (retiredStreams.has(message.stream_id)) return;
    if (message.stream_id === state.streamId && message.sequence <= state.sequence) return;
    if (state.streamId && message.stream_id !== state.streamId) retiredStreams.add(state.streamId);
    state.streamId = message.stream_id;
    state.sequence = message.sequence;
    // A snapshot replaces the whole state, including null after a reset.
    state.snapshot = message.snapshot;
    state.error = message.error || null;
    state.source = message.source || null;
    render();
    // Diagnostic watermark only; it never participates in displayed numbers.
    window.endfieldRenderedRevision = message.source_revision;
    window.endfieldRenderedGeneration = message.source_generation;
    window.endfieldRenderedAt = typeof performance !== "undefined" ? performance.now() : null;
  }

  function formatNumber(value, maximumFractionDigits = 0) {
    return typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString(undefined, { maximumFractionDigits }) : "—";
  }

  function formatTime(ms) {
    if (typeof ms !== "number" || !Number.isFinite(ms)) return "—";
    const seconds = Math.max(0, Math.floor(ms / 1000));
    return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
      .map((value) => String(value).padStart(2, "0")).join(":");
  }

  function formatDamage(value) {
    return typeof value === "number" && Math.abs(value) >= 1000000
      ? `${formatNumber(value / 1000000, 2)}M` : formatNumber(value);
  }

  function element(className, text) {
    const node = document.createElement("div");
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderRows(participants, totalDamage) {
    refs.rows.replaceChildren();
    refs.emptyState.classList.toggle("hidden", participants.length > 0);
    const metric = barMode === "rdps" ? "total_rd" : "total_damage";
    const players = [...participants].sort((a, b) => (b[metric] || 0) - (a[metric] || 0));
    const maximum = Math.max(0, ...players.map((player) => player[metric] || 0));
    const share = (value) => typeof value === "number" && Number.isFinite(value) &&
      typeof totalDamage === "number" && totalDamage > 0
      ? `${formatNumber(value / totalDamage * 100, 1)}%` : "—";
    for (const [index, player] of players.entries()) {
      const row = element("row");
      const progress = element("row-progress");
      // Chart geometry only; all battle numbers come directly from the snapshot.
      progress.style.width = `${maximum > 0 ? Math.max(0, Math.min(100, (player[metric] || 0) / maximum * 100)) : 0}%`;
      progress.className = `row-progress ${barMode}`;
      const name = String(player.character_name || player.character_key || "?");
      const identity = element("row-name");
      const crit = typeof player.crit_rate === "number" ? `${formatNumber(player.crit_rate * 100, 1)}%` : "—";
      identity.append(element("player-name", name), element("player-meta", `CRIT ${crit}`));
      row.append(progress, identity);
      for (const column of columns.filter((column) => visibleColumns.includes(column.key))) {
        const cell = element(`row-stat ${column.className}`, column.value(player, share));
        cell.title = formatNumber(column.key.startsWith("rdamage") ? player.total_rd : player.total_damage, 2);
        row.appendChild(cell);
      }
      refs.rows.appendChild(row);
    }
  }

  function render() {
    const snapshot = state.snapshot;
    const battle = snapshot && snapshot.battle || {};
    const quality = snapshot && (snapshot.quality_summary || snapshot.snapshot_quality) || {};
    const selectedColumns = columns.filter((column) => visibleColumns.includes(column.key));
    refs.columnsHead.replaceChildren(element("table-label table-label-name", `角色 · ${barMode === "rdps" ? "rDMG" : "DMG"}条`),
      ...selectedColumns.map((column) => element("table-label", column.label)));
    document.documentElement.style.setProperty("--table-columns", `minmax(6rem, 1.2fr)${selectedColumns.length ? ` repeat(${selectedColumns.length}, minmax(0, 1fr))` : ""}`);
    const active = !!((battle.timer_start_seen || battle.official_timer_start_seen) &&
      !(battle.timer_end_seen || battle.official_timer_end_seen));
    refs.totalDamage.textContent = snapshot ? formatNumber(battle.total_damage) : "0";
    refs.totalDps.textContent = snapshot ? formatNumber(battle.total_dps, 1) : "0.0";
    refs.combatTime.textContent = snapshot ? formatTime(battle.duration_ms) : "00:00:00";
    refs.combatIndicator.classList.toggle("active", active && state.connected);
    refs.footer.classList.toggle("active", active && state.connected);
    const labels = { verified: "已验证", provisional: "暂定", unavailable: "证据不可用" };
    const source = state.source && state.source.mode === "history" ? `历史 · ${state.source.label || "已加载"}` : "实时";
    refs.footerText.textContent = state.error ? "分析异常" : snapshot
      ? `${source} // ${labels[quality.status] || "质量未知"}${state.connected ? "" : " / 连接断开"}`
      : state.connected ? "STANDBY // 等待战斗数据" : "DISCONNECTED // 连接断开";
    refs.footer.title = ["rdps", "timing"].map((dimension) => {
      const item = quality[dimension] || {};
      return `${dimension}: ${item.status || "unknown"} ${(item.reasons || []).join(", ")}`;
    }).join("\n");
    renderRows(snapshot && Array.isArray(snapshot.participants) ? snapshot.participants : [], battle.total_damage);
  }

  function connect() {
    const socket = new WebSocket(wsUrl);
    ws = socket;
    socket.onopen = () => { if (ws === socket) { state.connected = true; render(); } };
    socket.onmessage = (message) => {
      if (ws !== socket) return;
      try { acceptSnapshot(JSON.parse(message.data)); }
      catch (error) { console.error("overlay ws parse error", error); }
    };
    socket.onclose = () => {
      if (ws !== socket) return;
      state.connected = false;
      render();
      reconnectTimer = window.setTimeout(connect, 1500);
    };
    socket.onerror = () => socket.close();
  }

  if (inProcess) {
    window.addEventListener("endfield-analysis-snapshot", (event) => acceptSnapshot(event.detail));
  } else {
    connect();
  }
  window.addEventListener("endfield-overlay-config", (event) => {
    if (event.detail && ["dps", "rdps"].includes(event.detail.barMode)) {
      barMode = event.detail.barMode;
    }
    if (event.detail && Array.isArray(event.detail.visibleColumns)) visibleColumns = event.detail.visibleColumns;
    render();
  });
  window.addEventListener("beforeunload", () => {
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    const socket = ws;
    ws = null;
    if (socket) socket.close();
  });
  render();
})();
