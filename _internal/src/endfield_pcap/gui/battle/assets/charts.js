'use strict';
// Charts consume measured samples and the existing Python display projections.
// No combat model or contribution allocator is implemented in JavaScript.
A.svgChart = function(height,high,paths,dots=[],caption='',low=0) {
  const x=t=>A.x(t), y=v=>height-18-(v-low)/Math.max(1,high-low)*(height-50);
  let content='';
  for(let i=0;i<=4;i++) {
    const value=low+(high-low)*i/4, py=y(value);
    content+=`<line x1="0" x2="${A.plotWidth}" y1="${py}" y2="${py}" stroke="var(--grid)"/><text x="4" y="${py-3}" fill="var(--muted)" font-size="11">${A.esc(A.num(value))}</text>`;
  }
  content+=paths.map(p=>`<polyline points="${p.points.map(([t,v])=>`${x(t)},${y(v)}`).join(' ')}" stroke="${p.color}" ${p.dash?'stroke-dasharray="6 4"':''}/>`).join('');
  content+=dots.map(p=>`<circle data-stamp="${p.time_ms}" cx="${x(p.time_ms)}" cy="${y(p.value)}" r="3" fill="${p.color||'#61c4df'}"/>`).join('');
  return `<svg viewBox="0 0 ${A.plotWidth} ${height}" preserveAspectRatio="none" aria-label="${A.esc(caption)}">${content}</svg><span class="chart-caption">${A.esc(caption)}</span><div class="cursor"></div>`;
};
A.chartRow = function(label,height,html,tip,move,role='全队') {
  const row=A.addRow(role,label,height,html,'chart');
  row.plot.addEventListener('mousemove',e=>{
    const px=Math.max(0,Math.min(A.plotWidth,e.clientX-row.plot.getBoundingClientRect().left));
    const cursor=row.plot.querySelector('.cursor'); if(cursor){cursor.style.left=`${px}px`;cursor.style.display='block';}
    const dot=e.target.closest('circle[data-stamp]');
    move(e,dot?Number(dot.dataset.stamp):A.start+px/A.plotWidth*A.duration);
  });
  row.plot.addEventListener('mouseleave',()=>{const c=row.plot.querySelector('.cursor');if(c)c.style.display='none';A.hideTip();});
  row.track.title=tip;
};
A.renderCharts = function() {
  if(A.data.controls.length) {
    const html=A.data.controls.map(c=>`<div class="control-block" style="left:${A.x(c.start_ms)}px;width:${Math.max(.5,A.x(c.end_ms)-A.x(c.start_ms))}px;background:${A.color(c.character_key)}" title="${A.esc(`${A.time(c.start_ms)}–${A.time(c.end_ms)} · ${c.name}\n${c.evidence}`)}">${A.esc(c.name)}</div>`).join('');
    A.addRow('全队共享','主控（观测）',44*A.scale,html);
  }
  const energy=A.data.energy;
  if(energy.samples.length) {
    if(!A.energyPlot) {
    const anchors=new Map(energy.samples.map(p=>[p.time_ms,p]));
    const all=[...energy.samples.map(p=>p.value),...energy.segments.map(p=>p.end_value),energy.capacity||0];
    const high=Math.max(100,Math.ceil(Math.max(...all)/100)*100), low=Math.min(0,Math.floor(Math.min(...all)/100)*100);
    const paths=energy.segments.map(s=>{
      const points=[[s.start_ms,s.start_value]];
      if(s.rate && s.capacity!==null) {
        const at=s.start_ms+((s.rate>0?s.capacity:0)-s.start_value)/s.rate*1000;
        if(at>s.start_ms&&at<s.end_ms) points.push([at,s.rate>0?s.capacity:0]);
      }
      points.push([s.end_ms,s.end_value]);
      const anchor=anchors.get(s.end_ms);if(anchor)points.push([s.end_ms,anchor.value]);
      return {points,color:'#199cce',dash:true};
    });
    A.energyPlot={high,low,paths};
    }
    const {high,low,paths}=A.energyPlot;
    const height=180*A.scale;
    A.chartRow('全队技力',height,A.svgChart(height,high,paths,energy.samples,'实心点：实测 · 虚线：推算（非精确曲线）',low),energy.notes.join('\n'),(e,t)=>A.hover(e,'energy',0,t));
  }
  A.data.enemies.forEach((enemy,index)=>{
    if(!enemy.samples.length) {A.addRow('敌方观测',enemy.name,44*A.scale,'<div class="empty">失衡值未知：没有可配对的 POISE_V1 采样</div>');return;}
    const points=[];
    enemy.samples.forEach((p,i)=>{if(i)points.push([p.time_ms,enemy.samples[i-1].value]);points.push([p.time_ms,p.value]);});
    const height=125*A.scale;
    A.chartRow(enemy.name,height,A.svgChart(height,Math.max(1,enemy.peak),[{points,color:'#d79b28'}],enemy.samples.map(p=>({...p,color:p.value<=0?'#f46a72':'#d79b28'})),`失衡观测 · 峰值 ${A.num(enemy.peak)}（非上限） · ${enemy.samples.length} 个采样`),enemy.name,(e,t)=>A.hover(e,'poise',index,t),'敌方');
  });
  A.renderDamageCurve();
};
A.renderDamageCurve = function() {
  if(A.state.curve==='none'||!A.data.damage_events.length)return;
  const rd=A.state.curve.startsWith('r'), dps=A.state.curve.endsWith('dps');
  const end=Math.max(1,Number(A.data.battle.duration_ms)||A.duration), count=Math.max(1,Math.ceil(end/1000));
  const people=A.data.participants.filter(p=>!A.state.character||p.character_key===A.state.character);
  A.curveCache??=new Map();
  const key=JSON.stringify([A.state.curve,A.state.character]);
  if(!A.curveCache.has(key))A.curveCache.set(key,people.map(p=>{
    const buckets=new Array(count).fill(0);
    for(const e of A.data.damage_events) {
      const amount=rd?(e.rdps_contributions||[]).filter(c=>c.character_key===p.character_key).reduce((s,c)=>s+Number(c.value||0),0):(e.source_character_key===p.character_key?Number(e.value||0):0);
      buckets[Math.max(0,Math.min(count-1,Math.floor(Number(e.ts_ms_from_start||0)/1000)))]+=amount;
    }
    let total=0;const points=[[0,0]];
    buckets.forEach((v,i)=>{total+=v;const t=Math.min(end,(i+1)*1000);points.push([t,dps?total/(t/1000):total]);});
    return {name:p.display_name,points,color:A.color(p.character_key)};
  }));
  A.curves=A.curveCache.get(key);
  const high=Math.max(1,...A.curves.flatMap(c=>c.points.map(p=>p[1]))),height=190*A.scale;
  const metric=rd?(dps?'rDPS':'累计 rDMG'):(dps?'DPS':'累计 DMG');
  A.chartRow(metric,height,A.svgChart(height,high,A.curves,[],`${metric} · 1 秒分桶；rD 仅汇总核心已有分配`),'DPS / rDPS 为自战斗起点至分桶终点的累计每秒值，不是瞬时值。缺失的 rD 分配不会补猜。',(e,t)=>{
    const lines=A.curves.map(c=>{let point=c.points[0];for(const p of c.points){if(p[0]>t)break;point=p;}return `${c.name}：${A.num(point[1])}（分桶终点 ${A.time(point[0])}）`;});
    A.textTip(e,`${A.time(t)} · ${metric}\n${lines.join('\n')}\nrD 仅展示有分配证据的份额；缺失不视为 0 贡献。`);
  },'伤害统计');
};
