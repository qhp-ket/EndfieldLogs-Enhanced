from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


def _json_for_script(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/")


def _battle_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    battle = snapshot.get("battle") or {}
    events = snapshot.get("buff_events") or []
    loadout = snapshot.get("loadout") or []
    status_counts: dict[str, int] = {}
    for event in events:
        status = str(event.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "file_name": snapshot.get("file_name") or battle.get("file_name") or "",
        "boss_name": battle.get("boss_name") or battle.get("boss_key") or "未知对象",
        "duration_ms": battle.get("duration_ms"),
        "total_damage": battle.get("total_damage"),
        "rdps_available": battle.get("rdps_available"),
        "actor_mapping_complete": battle.get("actor_mapping_complete"),
        "loadout_count": len(loadout),
        "buff_event_count": len(events),
        "buff_status_counts": status_counts,
    }


def build_audit_viewer_html(snapshot: dict[str, Any], *, title: str = "Endfield Battle Audit") -> str:
    payload = {
        "summary": _battle_summary(snapshot),
        "participants": snapshot.get("participants") or [],
        "loadout": snapshot.get("loadout") or [],
        "buff_events": snapshot.get("buff_events") or [],
    }
    payload_json = _json_for_script(payload)
    page_title = escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<style>
:root {{
  color-scheme: dark;
  --bg: #15131f;
  --panel: #211d30;
  --panel2: #28233a;
  --line: #3a334d;
  --text: #ece7ff;
  --muted: #a79fbe;
  --accent: #46d6b5;
  --warn: #f5bf4f;
  --bad: #ee6d7a;
  --good: #55d081;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
  font-size: 14px;
}}
header {{
  padding: 18px 22px 10px;
  border-bottom: 1px solid var(--line);
  background: #1b1828;
}}
h1 {{ margin: 0 0 8px; font-size: 20px; font-weight: 700; letter-spacing: 0; }}
h2 {{ margin: 22px 0 10px; font-size: 16px; }}
.muted {{ color: var(--muted); }}
.wrap {{ padding: 16px 22px 32px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
.metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; min-height: 64px; }}
.metric .label {{ color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
.metric .value {{ font-size: 18px; font-weight: 700; overflow-wrap: anywhere; }}
.toolbar {{
  display: grid;
  grid-template-columns: 1.4fr repeat(3, minmax(130px, .6fr));
  gap: 8px;
  margin: 10px 0;
}}
input, select {{
  width: 100%;
  min-height: 34px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 7px 9px;
  color: var(--text);
  background: #181522;
}}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
th, td {{ border-bottom: 1px solid var(--line); padding: 8px 7px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }}
th {{ color: var(--muted); background: #1a1725; position: sticky; top: 0; z-index: 1; font-weight: 600; }}
.table-wrap {{ border: 1px solid var(--line); border-radius: 8px; overflow: auto; background: var(--panel); max-height: 66vh; }}
.card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }}
.loadout-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
.loadout-title {{ display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; font-weight: 700; }}
.tag {{ display: inline-flex; align-items: center; min-height: 20px; border-radius: 5px; padding: 2px 6px; margin: 1px 3px 1px 0; font-size: 12px; background: var(--panel2); color: var(--muted); }}
.tag.good {{ color: #dffce9; background: #21412e; }}
.tag.warn {{ color: #fff0c7; background: #4a3a18; }}
.tag.bad {{ color: #ffe1e4; background: #4a2229; }}
.status-included {{ color: var(--good); }}
.status-merged {{ color: var(--warn); }}
.status-filtered {{ color: var(--bad); }}
details {{ margin-top: 6px; }}
summary {{ color: var(--accent); cursor: pointer; }}
pre {{ white-space: pre-wrap; word-break: break-word; margin: 8px 0 0; padding: 8px; background: #14111d; border: 1px solid var(--line); border-radius: 6px; color: #d8d1ef; max-height: 260px; overflow: auto; }}
.small {{ font-size: 12px; }}
.empty {{ padding: 16px; color: var(--muted); border: 1px dashed var(--line); border-radius: 8px; }}
@media (max-width: 820px) {{
  .toolbar {{ grid-template-columns: 1fr; }}
  th, td {{ font-size: 12px; padding: 7px 5px; }}
}}
</style>
</head>
<body>
<header>
  <h1>Endfield DPS Meter 审计视图</h1>
  <div id="subtitle" class="muted"></div>
</header>
<main class="wrap">
  <section id="summary"></section>
  <section>
    <h2>当前队伍 / 装备</h2>
    <div id="loadout"></div>
  </section>
  <section>
    <h2>BUFF 审计</h2>
    <div class="toolbar">
      <input id="q" type="search" placeholder="搜索 buff、角色、BB、原因">
      <select id="status"><option value="">全部状态</option></select>
      <select id="source"><option value="">全部来源</option></select>
      <select id="target"><option value="">全部目标</option></select>
    </div>
    <div id="buff-count" class="muted small"></div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th style="width: 72px">状态</th>
            <th style="width: 142px">时间</th>
            <th style="width: 120px">来源</th>
            <th style="width: 130px">目标</th>
            <th style="width: 180px">BUFF</th>
            <th>效果 / 诊断</th>
          </tr>
        </thead>
        <tbody id="buff-body"></tbody>
      </table>
    </div>
  </section>
</main>
<script id="payload" type="application/json">{payload_json}</script>
<script>
const DATA = JSON.parse(document.getElementById("payload").textContent);
const summary = DATA.summary || {{}};
const events = Array.isArray(DATA.buff_events) ? DATA.buff_events : [];
const loadout = Array.isArray(DATA.loadout) ? DATA.loadout : [];
const byId = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
const pct = (value) => {{
  const n = Number(value);
  if (!Number.isFinite(n)) return "";
  return `${{(n * 100).toFixed(Math.abs(n) < 0.1 ? 1 : 0)}}%`;
}};
const msText = (ms) => {{
  const n = Number(ms);
  if (!Number.isFinite(n)) return "-";
  return `${{(n / 1000).toFixed(1)}}s`;
}};
const compactJson = (obj) => JSON.stringify(obj ?? null, null, 2);

function renderSummary() {{
  byId("subtitle").textContent = `${{summary.file_name || ""}}  Boss: ${{summary.boss_name || "未知对象"}}`;
  const counts = summary.buff_status_counts || {{}};
  const metrics = [
    ["战斗时间", msText(summary.duration_ms)],
    ["总伤害", summary.total_damage ?? "-"],
    ["队伍解析", `${{summary.loadout_count || 0}} 人`],
    ["BUFF 事件", summary.buff_event_count || 0],
    ["计入 / 合并 / 过滤", `${{counts.included || 0}} / ${{counts.merged || 0}} / ${{counts.filtered || 0}}`],
    ["rDPS / 名字映射", `${{summary.rdps_available ? "可用" : "未确认"}} / ${{summary.actor_mapping_complete ? "完整" : "未完整"}}`],
  ];
  byId("summary").innerHTML = `<div class="grid">${{metrics.map(([label, value]) => `
    <div class="metric"><div class="label">${{esc(label)}}</div><div class="value">${{esc(value)}}</div></div>
  `).join("")}}</div>`;
}}

function renderLoadout() {{
  if (!loadout.length) {{
    byId("loadout").innerHTML = `<div class="empty">没有解析到 loadout。需要 SC_SELF_SCENE_INFO / 队伍变更 / 装备变更包进入 trace。</div>`;
    return;
  }}
  byId("loadout").innerHTML = `<div class="card-grid">${{loadout.map(row => {{
    const weaponEffects = Array.isArray(row.weapon_source_skills) ? row.weapon_source_skills : [];
    const suits = Array.isArray(row.suit_effects) ? row.suit_effects : [];
    const equips = Array.isArray(row.equips) ? row.equips : [];
    return `<article class="loadout-card">
      <div class="loadout-title">
        <span>${{esc(row.character_name || row.character_key || row.char || "未知角色")}}</span>
        <span class="tag">潜能 ${{esc(row.potential ?? "-")}}</span>
      </div>
      <div><span class="muted">武器</span> ${{esc(row.weapon_name || row.weapon_template || "-")}}
        <span class="tag">Lv ${{esc(row.weapon_level ?? row.weapon_lv ?? "-")}}</span>
        <span class="tag">ATK ${{esc(row.weapon_base_atk ?? "-")}}</span>
      </div>
      <div style="margin-top:8px"><span class="muted">套装</span>
        ${{suits.length ? suits.map(s => `<span class="tag ${{s.active ? "good" : ""}}">${{esc(s.suit_name || s.suit_id)}} x${{esc(s.piece_count ?? 0)}}</span>`).join("") : `<span class="tag">无激活套装</span>`}}
      </div>
      <div style="margin-top:8px"><span class="muted">武器效果</span>
        ${{weaponEffects.length ? weaponEffects.map(w => `<span class="tag warn">${{esc(w.skill_id)}} ${{esc(Object.keys(w.bb || {{}}).join(","))}}</span>`).join("") : `<span class="tag">未解析</span>`}}
      </div>
      <details><summary>装备 / BB 详情</summary><pre>${{esc(compactJson({{weapon_source_skills: weaponEffects, suits, equips, gem_template: row.gem_template, gem_terms: row.gem_terms}}))}}</pre></details>
    </article>`;
  }}).join("")}}</div>`;
}}

function labelFor(value, fallback) {{
  return value == null || value === "" ? fallback : String(value);
}}

function eventSearchText(ev) {{
  return [
    ev.status, ev.raw_event_key, ev.event_key, ev.event_name,
    ev.source_character_name, ev.source_character_key, ev.raw_source,
    ev.target_character_name, ev.target_character_key, ev.owner_raw,
    ev.reason, ev.packet_classification && ev.packet_classification.reason,
    (ev.effect_summary || []).join(" "),
    (ev.bb_keys || []).join(" "),
    JSON.stringify(ev.bb_values || {{}}),
  ].filter(Boolean).join(" ").toLowerCase();
}}

function fillFilters() {{
  const status = [...new Set(events.map(e => e.status || "unknown"))].sort();
  const source = [...new Set(events.map(e => labelFor(e.source_character_name || e.source_character_key || e.raw_source, "")))].filter(Boolean).sort();
  const target = [...new Set(events.map(e => labelFor(e.target_character_name || e.target_character_key || e.owner_raw, "")))].filter(Boolean).sort();
  for (const value of status) byId("status").insertAdjacentHTML("beforeend", `<option value="${{esc(value)}}">${{esc(value)}}</option>`);
  for (const value of source) byId("source").insertAdjacentHTML("beforeend", `<option value="${{esc(value)}}">${{esc(value)}}</option>`);
  for (const value of target) byId("target").insertAdjacentHTML("beforeend", `<option value="${{esc(value)}}">${{esc(value)}}</option>`);
}}

function effectText(ev) {{
  const rows = Array.isArray(ev.effect_summary) && ev.effect_summary.length
    ? ev.effect_summary
    : (Array.isArray(ev.zone_effects) ? ev.zone_effects.map(z => `${{z.zone_label || z.zone || "效果"}}/${{z.element || "all"}} ${{pct(z.rate)}}`) : []);
  return rows.length ? rows.join(" / ") : (ev.packet_classification && ev.packet_classification.kind ? ev.packet_classification.kind : "无可计入效果");
}}

function renderBuffs() {{
  const q = byId("q").value.trim().toLowerCase();
  const status = byId("status").value;
  const source = byId("source").value;
  const target = byId("target").value;
  const filtered = events.filter(ev => {{
    const src = labelFor(ev.source_character_name || ev.source_character_key || ev.raw_source, "");
    const tgt = labelFor(ev.target_character_name || ev.target_character_key || ev.owner_raw, "");
    return (!status || (ev.status || "unknown") === status)
      && (!source || src === source)
      && (!target || tgt === target)
      && (!q || eventSearchText(ev).includes(q));
  }});
  byId("buff-count").textContent = `显示 ${{filtered.length}} / ${{events.length}} 条`;
  byId("buff-body").innerHTML = filtered.map(ev => {{
    const statusClass = `status-${{esc(ev.status || "unknown")}}`;
    const src = labelFor(ev.source_character_name || ev.source_character_key || ev.raw_source, "-");
    const tgt = labelFor(ev.target_character_name || ev.target_character_key || ev.owner_raw, "-");
    const start = ev.start_time || "-";
    const end = ev.end_time || ev.raw_end_time || "-";
    const bbKeys = Array.isArray(ev.bb_keys) ? ev.bb_keys.join(", ") : "";
    const reason = ev.reason || (ev.packet_classification && ev.packet_classification.reason) || "";
    const details = {{
      raw_event_key: ev.raw_event_key,
      event_key: ev.event_key,
      uid: ev.uid,
      status: ev.status,
      duration_ms: ev.duration_ms,
      raw_duration_ms: ev.raw_duration_ms,
      bb_values: ev.bb_values,
      zone_effects: ev.zone_effects,
      dynamic_effects: ev.dynamic_effects,
      effect_segments: ev.effect_segments,
      packet_mapping: ev.packet_mapping,
      packet_classification: ev.packet_classification,
      semantic_candidates: ev.semantic_candidates,
      raw_line: ev.raw_line,
    }};
    return `<tr>
      <td class="${{statusClass}}">${{esc(ev.status || "unknown")}}</td>
      <td>${{esc(start)}}<br><span class="muted">${{esc(end)}} / ${{esc(msText(ev.duration_ms))}}</span></td>
      <td>${{esc(src)}}<br><span class="muted small">${{esc(ev.raw_source || "")}}</span></td>
      <td>${{esc(tgt)}}<br><span class="muted small">${{esc(ev.owner_raw || "")}}</span></td>
      <td>${{esc(ev.raw_event_key || "-")}} -><br>${{esc(ev.event_key || ev.event_name || "-")}}</td>
      <td>${{esc(effectText(ev))}}<br><span class="muted small">${{esc(bbKeys)}} ${{esc(reason)}}</span>
        <details><summary>详情</summary><pre>${{esc(compactJson(details))}}</pre></details>
      </td>
    </tr>`;
  }}).join("");
}}

renderSummary();
renderLoadout();
fillFilters();
renderBuffs();
["q", "status", "source", "target"].forEach(id => byId(id).addEventListener("input", renderBuffs));
</script>
</body>
</html>
"""


def write_audit_viewer_html(snapshot: dict[str, Any], out_path: str | Path) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_audit_viewer_html(snapshot), encoding="utf-8")
    return path
