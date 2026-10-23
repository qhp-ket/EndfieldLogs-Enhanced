'use strict';
A.detailTab='overview';A.selectedBlock=null;A.selectedHit=null;
A.blockEvidence=new Map();
A.evidence=function(id) {
  if(!A.blockEvidence.has(id))A.blockEvidence.set(id,new Promise((resolve,reject)=>
    A.bridge.blockDetails(id,raw=>{try{resolve(JSON.parse(raw));}catch(error){A.blockEvidence.delete(id);reject(error);}})));
  return A.blockEvidence.get(id);
};
A.hitTip=function(h) {
  const contributions=(h.rdps_contributions||[]).map(c=>`${A.data.names[c.character_key]||c.character_name||c.character_key} ${A.num(c.value)}`).join('；')||'未知';
  return `${A.time(Number(h.ts_ms_from_start||0))} · DMG ${A.num(h.value)}\n目标：${h.target_label}\nrD 基数：${A.num(h.rdps_basis_value)}\nrDMG 分配：${contributions}\n本击抗性：${h.element_name} ${A.num(h.resistance)}\n核心匹配失衡值：${A.num((h.poise_damage||{}).current_value)}`;
};
A.inspectBlock=function(id,hit) {
  A.selectedBlock=id;A.selectedHit=hit===undefined?null:Number(hit);
  if(hit!==undefined)A.detailTab='hits';
  A.state.selectedBlock=id;A.state.selectedHit=A.selectedHit;A.state.detailTab=A.detailTab;
  document.querySelectorAll('.node.selected').forEach(n=>n.classList.remove('selected'));
  document.querySelectorAll(`.node[data-block="${id}"]`).forEach(n=>n.classList.add('selected'));
  A.renderInspector();A.changed();
};
A.renderInspector=function() {
  const revision=A.inspectorRevision=(A.inspectorRevision||0)+1;
  A.state.detailTab=A.detailTab;
  document.querySelectorAll('[data-detail]').forEach(n=>n.classList.toggle('active',n.dataset.detail===A.detailTab));
  const body=A.$('inspector-body');if(A.selectedBlock===null||!A.$('inspector').open)return;
  body.textContent='正在读取此块证据…';
  A.evidence(A.selectedBlock).then(evidence=>{
  if(revision!==A.inspectorRevision)return;
  const b={...A.data.blocks[A.selectedBlock],...evidence},summary=b.summary;
  if(A.detailTab==='overview')body.innerHTML=`<pre>${A.esc(b.description[A.state.unit])}</pre>`;
  else if(A.detailTab==='allocation')body.innerHTML=`<p class="muted">DMG ${A.num(summary.damage)} · rD 基数 ${A.num(summary.basis)} · 已分配 ${A.num(summary.allocated)}<br>有分配证据 ${summary.covered}/${summary.hits} 击；占比以已分配 rDMG 为分母。直接使用核心结果，不补猜缺失份额。</p>`+A.table(['贡献者','rDMG','占已分配 rDMG'],summary.contributions.map(c=>[c.name,A.num(c.value),`${c.percent.toFixed(2)}%`]));
  else if(A.detailTab==='hits') {
    body.innerHTML=A.table([`时间 / ${A.state.unit==='frames'?'F（30F/s）':'s'}`,'目标','DMG','rD 基数','rDMG 分配','本击抗性 / 点','核心匹配失衡值'],b.hits.map(h=>[
      A.time(Number(h.ts_ms_from_start||0)),h.target_label,A.num(h.value),A.num(h.rdps_basis_value),
      (h.rdps_contributions||[]).map(c=>`${A.data.names[c.character_key]||c.character_name||c.character_key} ${A.num(c.value)}`).join('；')||'未知',
      `${h.element_name} ${A.num(h.resistance)}`,A.num((h.poise_damage||{}).current_value)]),i=>`data-hit="${i}"`);
    body.querySelectorAll('[data-hit]').forEach(row=>{
      row.title=A.hitTip(b.hits[Number(row.dataset.hit)]);
      row.onclick=()=>{A.selectedHit=Number(row.dataset.hit);A.state.selectedHit=A.selectedHit;A.detailTab='raw';A.renderInspector();A.changed();};
      if(Number(row.dataset.hit)===A.selectedHit)row.style.background='var(--hover)';
    });
  } else {
    const original=b.events.filter(e=>e.event_type==='damage');
    const value=A.selectedHit!==null&&original[A.selectedHit]?original[A.selectedHit]:b.events;
    body.innerHTML=(A.selectedHit!==null?'<button id="all-evidence">查看此块全部证据</button>':'')+`<pre>${A.esc(JSON.stringify(value,null,2))}</pre>`;
    const all=A.$('all-evidence');if(all)all.onclick=()=>{A.selectedHit=null;A.state.selectedHit=null;A.renderInspector();A.changed();};
  }
  }).catch(error=>{if(revision===A.inspectorRevision)body.textContent='证据读取失败：'+error;});
};
A.skillSort={field:'total_damage',direction:-1};
A.renderSkills=function() {
  const fields=['display_character','category','display_skill','cast_count','total_damage','damage_percent','avg_damage','max_damage'];
  const rows=A.data.skills.filter(r=>!A.state.character||r.character_key===A.state.character).slice();
  const {field,direction}=A.skillSort;
  rows.sort((a,b)=>direction*(typeof a[field]==='number'?a[field]-b[field]:String(a[field]||'').localeCompare(String(b[field]||''),'zh-CN')));
  A.$('skill-table').innerHTML=A.table(['角色','分类','技能','次数','总伤害','DMG rate','平均单次','最大单次'],rows.map(r=>fields.map((f,i)=>i<3?r[f]:f==='damage_percent'?`${Number(r[f]||0).toFixed(2)}%`:A.num(r[f]))),()=>'',(i,j)=>j<3?rows[i].skill_key:'');
  A.$('skill-table').querySelectorAll('th').forEach((th,i)=>{th.classList.add('sortable');th.title='点击排序；DMG rate 为该角色总伤占比。次数、平均和最大按核心合并后的单次施放统计。';th.onclick=()=>{A.skillSort={field:fields[i],direction:field===fields[i]?-direction:-1};A.renderSkills();};});
  const ordered=rows.slice().sort((a,b)=>Number(b.total_damage||0)-Number(a.total_damage||0));
  const maximum=Math.max(1,...ordered.map(r=>Number(r.total_damage||0)));
  A.$('skill-composition').innerHTML=ordered.slice(0,12).map(r=>`<div class="composition-row" title="${A.esc(`${r.display_character} · ${r.display_skill}\n${r.skill_key}\nDMG ${A.num(r.total_damage)} · 角色内占比 ${Number(r.damage_percent||0).toFixed(2)}%`)}"><span>${A.esc(r.display_character+' · '+r.display_skill)}</span><div class="composition-bar"><i style="width:${Number(r.total_damage||0)/maximum*100}%"></i></div><span>${A.num(r.total_damage)}</span></div>`).join('');
};
A.renderEnemies=function() {
  A.$('enemy-stats').innerHTML=A.table(['敌人 / 实例','属性记录时间','防御','物理抗性','自然抗性','寒冷抗性','电磁抗性','灼热抗性','源石抗性','证据'],A.data.enemy_rows);
  A.$('enemy-poise').innerHTML=A.table(['敌人 / 实例','采样数','首个值','最后值','观测峰值','零值采样数'],A.data.enemies.map(e=>[e.name,e.samples.length,A.num(e.samples[0]?.value),A.num(e.samples[e.samples.length-1]?.value),A.num(e.peak),e.samples.length?e.samples.filter(p=>p.value<=0).length:'未知']));
};
