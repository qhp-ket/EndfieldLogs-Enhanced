'use strict';
A.bounds=b=>A.state.fallback?b.bounds:[b.start,b.end];
A.addRow=function(role,label,height,html='',className='') {
  const grid=A.$('timeline-grid'),r=document.createElement('div'),t=document.createElement('div'),p=document.createElement('div');
  r.className='role-cell';r.textContent=role;r.title=role;
  t.className='track-cell';t.innerHTML=`<span>${A.esc(label)}</span>`;t.title=label;
  p.className=`plot-row ${className}`;p.innerHTML=html;
  for(const cell of [r,t,p]){cell.style.height=`${height}px`;grid.appendChild(cell);}
  return {role:r,track:t,plot:p};
};
A.renderTimeline=function() {
  const scroll=A.$('timeline-scroll'),grid=A.$('timeline-grid');
  const previous=[scroll.scrollLeft,scroll.scrollTop];grid.replaceChildren();
  A.scale=A.state.graphics/100;
  const blocks=A.data.blocks.filter(b=>(!A.state.character||b.owner===A.state.character)&&(A.state.buffs||b.lane!=='buff'));
  A.start=0;A.duration=Math.max(1,Number(A.data.battle.duration_ms)||1);
  A.plotWidth=Math.max(320,scroll.clientWidth-A.state.roleWidth-A.state.trackWidth-24)*A.state.zoom/100*A.scale;
  A.x=t=>(t-A.start)/A.duration*A.plotWidth;
  const unit=A.state.unit==='frames'?.03:.001;
  const step=Math.max(A.state.unit==='frames'?1:.001,A.duration*unit/Math.max(2,A.plotWidth/(90*A.scale)));
  const magnitude=10**Math.floor(Math.log10(step)),tick=[1,2,5,10].map(n=>n*magnitude).find(n=>n>=step);
  grid.style.setProperty('--role',`${A.state.roleWidth}px`);grid.style.setProperty('--track',`${A.state.trackWidth}px`);
  grid.style.setProperty('--plot',`${A.plotWidth}px`);grid.style.setProperty('--row-scale',A.scale);
  grid.style.setProperty('--tick-gap',`${tick/unit/A.duration*A.plotWidth}px`);grid.style.setProperty('--tick-offset',`${A.x(0)}px`);
  const head=A.addRow('干员','轨道 / 类型',36);
  for(const cell of [head.role,head.track,head.plot])cell.classList.add('ruler');
  head.plot.setAttribute('data-ruler','');
  for(let v=Math.ceil(A.start*unit/tick)*tick;v<=(A.start+A.duration)*unit+tick*1e-8;v+=tick){
    const tag=document.createElement('span');tag.className='tick';tag.style.left=`${A.x(v/unit)}px`;tag.textContent=`${Number(v.toPrecision(8))}${A.state.unit==='frames'?'F':'s'}`;head.plot.appendChild(tag);
  }
  A.installColumnHandle(head.role,'roleWidth',64);A.installColumnHandle(head.track,'trackWidth',90);
  const owners=[...new Set([...A.data.participants.map(p=>p.character_key),...blocks.map(b=>b.owner)])];
  for(const owner of owners) {
    const own=blocks.filter(b=>b.owner===owner);if(!own.length)continue;
    let first=null,rowCount=0;
    const categories=[...new Set([...A.data.categories,...own.filter(b=>b.lane==='skill').map(b=>b.category)])];
    for(const cat of categories) {
      const items=own.filter(b=>b.lane==='skill'&&b.category===cat);if(!items.length)continue;
      const key=JSON.stringify([owner,cat]),expanded=A.state.expanded.includes(key),edges=[];
      const placed=items.sort((a,b)=>A.bounds(a)[0]-A.bounds(b)[0]).map(b=>{
        const bounds=A.bounds(b),left=A.x(bounds[0]),right=Math.max(left+4,A.x(bounds[1]));
        let row=expanded?edges.findIndex(edge=>edge+2<=left):0;if(row<0)row=edges.length;
        edges[row]=Math.max(edges[row]||-Infinity,right);return {b,left,right,row};
      });
      const pitch=43*A.scale,parts=placed.map(p=>A.blockHtml(p.b,p.left,p.right,p.row*pitch)).join('');
      const row=A.addRow(A.data.names[owner],`${expanded?'▾':'▸'} ${A.data.category_names[cat]||cat}`,Math.max(1,edges.length)*pitch+5,parts);
      row.plot.dataset.inputOwner=owner;row.role.classList.add('character-name');row.track.classList.add('expand');row.track.dataset.lane=key;row.track.title+=' · 点击展开 / 收起重叠技能';
      row.track.onclick=()=>{A.state.expanded=expanded?A.state.expanded.filter(k=>k!==key):[...A.state.expanded,key];A.ensureTimeline();A.changed();};
      if(!first)first=row.role;else row.role.remove();rowCount++;
    }
    const tracks=[...new Set(own.filter(b=>b.lane==='buff').map(b=>JSON.stringify(b.track)))];
    for(const track of tracks) {
      const items=own.filter(b=>b.lane==='buff'&&JSON.stringify(b.track)===track);
      const row=A.addRow(A.data.names[owner],items[0].name,43*A.scale,items.map(b=>A.blockHtml(b,A.x(b.start),Math.max(A.x(b.start)+.8,A.x(b.end)),0)).join(''));
      row.plot.dataset.inputOwner=owner;row.role.classList.add('character-name');
      row.track.title=items[0].name+' · '+items[0].buff_text;
      if(!first)first=row.role;else row.role.remove();rowCount++;
    }
    if(first){first.style.gridRow=`span ${rowCount}`;first.style.height='auto';first.innerHTML=`<span class="character-identity timeline-identity">${A.avatar(owner,A.data.names[owner],40)}<span>${A.esc(A.data.names[owner])}</span></span>`;}
  }
  if(!blocks.length)A.addRow('—','技能 / BUFF',64,'<div class="empty">此筛选没有技能 / BUFF 事件</div>');
  A.renderCharts(); if(A.renderInputEvidence)A.renderInputEvidence();
  grid.querySelectorAll('[data-block]').forEach(node=>{
    const b=A.data.blocks[Number(node.dataset.block)];
    node.addEventListener('click',()=>A.inspectBlock(b.id,node.dataset.hitIndex));
    node.addEventListener('mousemove',e=>{
      if(node.classList.contains('stack-dot')){A.hover(e,'buff',b.id,Number(node.dataset.stamp));return;}
      const stamp=A.start+(e.clientX-node.parentElement.getBoundingClientRect().left)/A.plotWidth*A.duration;
      if(b.lane==='buff')A.hover(e,'buff',b.id,stamp);
      else if(node.dataset.hitIndex!==undefined){A.tipRevision++;A.textTip(e,A.hitTip(b.hits[Number(node.dataset.hitIndex)]));}
      else A.hover(e,'block',b.id,stamp);
    });
    node.addEventListener('mouseleave',()=>A.hideTip());
  });
  grid.querySelectorAll('.plot-row').forEach(row=>row.addEventListener('mousemove',e=>{
    const stamp=Math.max(A.start,Math.min(A.start+A.duration,A.start+(e.clientX-row.getBoundingClientRect().left)/A.plotWidth*A.duration));
    A.$('hover-time').textContent='时间 '+A.time(stamp);
    if(A.inputHover?.(row,e,stamp))return;
    if(e.target===row&&!row.classList.contains('chart')) {
      A.hover(e,'energy',0,stamp);
    }
  }));
  scroll.onmouseleave=()=>{A.$('hover-time').textContent='时间 —';};
  scroll.scrollLeft=previous[0];scroll.scrollTop=previous[1];
};
A.blockHtml=function(b,left,right,y) {
  const reference=b.lane==='skill'&&b.reference&&A.state.fallback;
  const color=A.categoryColors[b.category]||A.categoryColors['其他'];
  const label=b.lane==='buff'?b.buff_text:(right-left>100*A.scale?b.name:b.category);
  let html=`<button class="node ${b.lane==='buff'?'buff':''} ${reference?'reference':''}" data-block="${b.id}" style="left:${left}px;width:${right-left}px;top:${y+5}px;--color:${color}" aria-label="${A.esc(b.name)}">${right-left>24?A.esc(label):''}</button>`;
  if(reference)html+=`<span class="logged-interval" style="left:${A.x(b.start)}px;width:${Math.max(1,A.x(b.end)-A.x(b.start))}px;top:${y+33*A.scale}px;--color:${color}" title="${A.esc(`日志区间：${A.time(b.start)}–${A.time(b.end)}`)}"></span>`;
  b.hits.forEach((h,i)=>{html+=`<button class="hit" data-block="${b.id}" data-hit-index="${i}" style="left:${A.x(Number(h.ts_ms_from_start||0))}px;top:${y+34*A.scale}px" aria-label="实际伤害点"></button>`;});
  let previous=0;
  b.states.forEach(s=>{
    if(s.stacks!==null&&previous!==null&&s.stacks!==previous)html+=`<button class="stack-dot" data-block="${b.id}" data-stamp="${s.start_ms}" style="left:${A.x(s.start_ms)}px;top:${y+14*A.scale}px" title="${A.esc(`${A.time(s.start_ms)} · 层数 ${previous} → ${s.stacks}`)}" aria-label="层数变化"></button>`;
    previous=s.stacks;
  });
  return html;
};
A.installColumnHandle=function(cell,key,minimum) {
  const handle=document.createElement('span');handle.className='col-handle';handle.title='拖动调整列宽';cell.appendChild(handle);
  handle.onpointerdown=e=>{
    e.preventDefault();const start=e.clientX,width=A.state[key];handle.setPointerCapture(e.pointerId);
    handle.onpointermove=event=>{A.state[key]=Math.max(minimum,Math.min(900,width+event.clientX-start));A.$('timeline-grid').style.setProperty(key==='roleWidth'?'--role':'--track',`${A.state[key]}px`);};
    handle.onpointerup=()=>{handle.onpointermove=null;A.ensureTimeline();A.changed();};
  };
};
