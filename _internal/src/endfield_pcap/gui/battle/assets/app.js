'use strict';
A.syncDetails=function() {
  A.state.details=A.$('inspector').open;
  if(!A.state.details)A.state.detailsMaximized=false;
  A.$('toggle-details').textContent=A.state.details?'收起详情 ▾':'展开详情 ▸';
  A.$('inspector').classList.toggle('maximized',A.state.details&&A.state.detailsMaximized);
  const button=A.$('maximize-details'),label=A.state.detailsMaximized?'还原详情':'最大化详情';
  button.textContent=A.state.detailsMaximized?'❐':'□';button.title=label;button.setAttribute('aria-label',label);
};
A.applyState=function(raw) {
  let state;try {state=JSON.parse(raw);}catch{return;}
  Object.assign(A.state,state);
  document.body.classList.toggle('avatars-off',A.state.avatars===false);
  document.documentElement.style.setProperty('--avatar-scale',Math.max(50,Math.min(300,Number(A.state.avatarPercent)||100))/100);
  if(state.selectedBlock!==undefined)A.selectedBlock=state.selectedBlock;
  if(state.selectedHit!==undefined)A.selectedHit=state.selectedHit;
  if(state.detailTab)A.detailTab=state.detailTab;
  for(const [id,key] of [['character','character'],['skill-character','character'],['unit','unit'],['curve','curve'],['zoom','zoom'],['graphics','graphics']])A.$(id).value=A.state[key];
  A.$('buffs').checked=A.state.buffs;A.$('fallback').checked=A.state.fallback;
  A.$('graphics-value').textContent=`${A.state.graphics}%`;
  A.$('inspector').open=A.state.details;A.syncDetails();
  A.skillsDirty=true;A.showTab(A.state.tab);A.renderInspector();
};
A.ensureTimeline=function() {
  if(A.$('timeline').hidden)return;
  const s=A.state,width=A.$('timeline-scroll').clientWidth;
  const key=JSON.stringify([width,s.character,s.avatars,s.buffs,s.fallback,s.zoom,s.graphics,s.unit,s.curve,s.expanded,s.roleWidth,s.trackWidth]);
  if(width>0&&key!==A.timelineKey){A.renderTimeline();A.timelineKey=key;}
};
A.scheduleTimeline=function() {
  if(A.timelinePending)return;
  A.timelinePending=true;requestAnimationFrame(()=>{A.timelinePending=false;A.ensureTimeline();});
};
A.showTab=function(tab) {
  A.state.tab=tab;
  document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==tab);
  A.hideTip();
  if(tab==='timeline')A.ensureTimeline();
  if(tab==='skills'&&A.skillsDirty){A.renderSkills();A.skillsDirty=false;}
  if(tab==='enemy'&&!A.enemiesRendered){A.renderEnemies();A.enemiesRendered=true;}
};
A.setCharacter=function(value) {
  A.state.character=value;A.$('character').value=value;A.$('skill-character').value=value;
  A.skillsDirty=true;A.showTab(A.state.tab);A.changed();
};
A.initialize=function(data) {
  A.data=data;A.$('record-name').textContent=data.label;A.$('record-name').title=data.label;
  const b=data.battle;A.$('metrics').innerHTML=`<span><small>DMG</small><strong>${A.num(b.total_damage)}</strong></span><span><small>DPS</small><strong>${A.num(b.total_dps)}</strong></span><span><small>时长</small><strong>${A.num(Number(b.duration_ms||0)/1000)}s</strong></span>`;
  const quality=JSON.stringify(data.quality,null,2);A.$('quality').textContent=quality;A.$('metrics').title=quality;
  A.$('roster').innerHTML=data.participants.map(p=>`<button class="roster-card" data-owner="${A.esc(p.character_key)}" style="--color:${A.color(p.character_key)}"><strong class="character-identity">${A.avatar(p.character_key,p.display_name)}<span>${A.esc(p.display_name)}</span></strong><span>DMG ${A.num(p.total_damage)} · rDMG ${A.num(p.total_rd)}<br>DPS ${A.num(p.dps)} · rDPS ${A.num(p.rdps)}</span></button>`).join('');
  A.$('roster').querySelectorAll('[data-owner]').forEach(n=>{n.title=data.names[n.dataset.owner]||n.dataset.owner;n.onclick=()=>A.setCharacter(A.state.character===n.dataset.owner?'':n.dataset.owner);});
  const options='<option value="">全部角色</option>'+data.participants.map(p=>`<option value="${A.esc(p.character_key)}">${A.esc(p.display_name)}</option>`).join('');
  A.$('character').innerHTML=options;A.$('skill-character').innerHTML=options;
  A.$('character').onchange=e=>A.setCharacter(e.target.value);A.$('skill-character').onchange=e=>A.setCharacter(e.target.value);
  for(const [id,key] of [['buffs','buffs'],['fallback','fallback']])A.$(id).onchange=e=>{A.state[key]=e.target.checked;A.ensureTimeline();A.changed();};
  for(const [id,key] of [['zoom','zoom'],['graphics','graphics']])A.$(id).oninput=e=>{A.state[key]=Number(e.target.value);A.$('graphics-value').textContent=`${A.state.graphics}%`;A.scheduleTimeline();A.changed();};
  A.$('fit').onclick=()=>{A.state.zoom=100;A.$('zoom').value=100;A.ensureTimeline();A.changed();};
  A.$('unit').onchange=e=>{A.state.unit=e.target.value;A.ensureTimeline();A.renderInspector();A.changed();};
  A.$('curve').onchange=e=>{A.state.curve=e.target.value;A.ensureTimeline();A.changed();};
  A.$('toggle-details').onclick=()=>{A.$('inspector').open=!A.$('inspector').open;};
  A.$('inspector').ontoggle=()=>{A.syncDetails();A.renderInspector();A.changed();};
  A.$('collapse-details').onclick=()=>{A.$('inspector').open=false;A.syncDetails();A.changed();};
  A.$('maximize-details').onclick=()=>{A.state.detailsMaximized=!A.state.detailsMaximized;A.syncDetails();A.changed();};
  document.querySelectorAll('[data-tab]').forEach(n=>n.onclick=()=>{A.showTab(n.dataset.tab);A.changed();});
  document.querySelectorAll('[data-detail]').forEach(n=>n.onclick=()=>{A.detailTab=n.dataset.detail;A.renderInspector();A.changed();});
  A.$('timeline-help').onmousemove=e=>A.textTip(e,'红菱形：真实伤害时间点，可点击查看逐击证据。\n蓝点：BUFF 层数变化，持续时间和层数按已有状态覆盖。\n技能块：完整日志起止优先；虚线为固定起止配置回退，实线下划线保留原日志区间。\n点击类型轨道展开 / 收起重叠技能；拖动表头列分隔线改变宽度。\n曲线悬停显示时间和数值；技力推算与实测区分，失衡仅显示最近观测。\nCtrl + 滚轮调整图形大小；普通滚轮立即滚动，无平滑拖尾。');
  A.$('timeline-help').onmouseleave=()=>A.hideTip();
  A.$('timeline-scroll').addEventListener('wheel',e=>{
    if(!e.ctrlKey)return;e.preventDefault();A.state.graphics=Math.min(250,Math.max(75,A.state.graphics+(e.deltaY<0?10:-10)));A.$('graphics').value=A.state.graphics;A.$('graphics-value').textContent=`${A.state.graphics}%`;A.scheduleTimeline();A.changed();
  },{passive:false});
  let lastWidth=-1,resizePending=false;
  new ResizeObserver(entries=>{
    const width=entries[0].contentRect.width;
    if(width<=0||Math.abs(width-lastWidth)<1)return;
    lastWidth=width;
    if(!resizePending){resizePending=true;requestAnimationFrame(()=>{resizePending=false;A.ensureTimeline();});}
  }).observe(A.$('timeline-scroll'));
  A.bridge.initialState(raw=>{A.applyState(raw);A.bridge.pageReady();document.body.dataset.ready='true';});
};
if(typeof qt==='undefined')A.fail('此界面需要从开发版 GUI 的战斗分析窗口打开。');
else new QWebChannel(qt.webChannelTransport,channel=>{
  A.bridge=channel.objects.analysis;
  A.bridge.environmentChanged.connect((theme,scale)=>{document.documentElement.dataset.theme=theme;document.documentElement.style.setProperty('--font-scale',scale);});
  A.bridge.labelChanged.connect(label=>{A.data.label=label;A.$('record-name').textContent=label;A.$('record-name').title=label;});
  A.bridge.stateChanged.connect(raw=>{if(A.data)A.applyState(raw);});
  A.bridge.inputsChanged.connect(raw=>{if(A.data){A.data.inputs=JSON.parse(raw);A.timelineKey=null;A.ensureTimeline();}});
  A.bridge.payload(raw=>{try{A.initialize(JSON.parse(raw));}catch(e){A.fail(e.stack||e);}});
});
