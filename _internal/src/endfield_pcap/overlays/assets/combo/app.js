(() => {
  'use strict';
  const rows = document.getElementById('comboRows'), status = document.getElementById('comboStatus');
  const retired = new Set();
  let stream = null, sequence = -1, snapshot = null, config = {}, layoutSignature = null;
  const nodes = Array.from({length:4},(_,slot) => {
    const row = document.createElement('div'); row.className='slot'; row.dataset.slot=slot;
    const icon=document.createElement('div');icon.className='portrait';
    const img=document.createElement('img');img.alt='';img.draggable=false;
    const number=document.createElement('span');number.className='number';number.textContent=slot+1;
    const mask=document.createElement('div');mask.className='mask';
    icon.append(img,number,mask);
    const name=document.createElement('div');name.className='name';
    const track=document.createElement('div');track.className='track';
    const fill=document.createElement('div');fill.className='fill';track.append(fill);
    const value=document.createElement('div');value.className='value';
    row.append(icon,name,track,value);rows.append(row);
    return {row,img,number,name,fill,value,mask};
  });
  function render() {
    const data=snapshot||{};
    document.body.dataset.style=config.settings?.display_style||'circles';
    document.documentElement.style.setProperty('--avatar-scale',(Number(config.settings?.avatar_size_percent)||100)/100);
    const holding=data.slots?.some(s=>s.held&&s.status!=='unknown');
    status.textContent=holding?'沿用上次状态':data.status||'等待图像识别';
    status.title=holding?(data.status||'等待新的有效识别'):'';
    for(let i=0;i<4;i++) {
      const item=data.slots?.find(s=>s.slot===i)||{},node=nodes[i];
      const unknown=!item.status||item.status==='unknown';
      node.row.dataset.status=item.status||'unknown';
      node.row.classList.toggle('stale',unknown);
      const name=item.display_name||`位置 ${i+1}`;
      node.name.textContent=name;node.name.title=name;
      const catalog=config.characterAvatars||{},key=catalog.aliases?.[item.character_key]||item.character_key;
      const url=config.settings?.show_character_avatars!=='off'&&key ? catalog.portraits?.[key]||catalog.placeholder : null;
      if(url&&node.img.getAttribute('src')!==url)node.img.src=url;
      node.img.hidden=!url;node.number.hidden=!!url;node.img.title=name;
      const progress=Number.isFinite(item.progress)?Math.max(0,Math.min(1,item.progress)):null;
      node.fill.style.width=progress===null?'0%':`${progress*100}%`;
      node.mask.style.height=progress===null?'100%':`${(1-progress)*100}%`;
      const remaining=item.estimated_remaining_ms;
      node.value.textContent=unknown?'—':item.status==='ready'?'CD 就绪':item.status==='dead'?'阵亡':item.status==='empty'?'空位':
        `${progress===null?'—':Math.round(progress*100)+'%'} · ${Number.isFinite(remaining)?'≈'+(remaining/1000).toFixed(1)+'s':'—'}`;
      node.row.title=`${name}\n${node.value.textContent}\n${item.held?'沿用上次识别，秒数按已有速度估算':'图像观测'}；CD 就绪不等于满足连携触发条件`;
    }
    const signature=JSON.stringify([config, nodes.map(n=>n.name.textContent)]);
    if(signature!==layoutSignature){layoutSignature=signature;window.fitComboContent?.();}
  }
  window.addEventListener('endfield-combo-snapshot',e=>{
    const m=e.detail;
    if(!m||m.type!=='combo_snapshot'||m.schema_version!==2||typeof m.stream_id!=='string'||!m.stream_id||
      !Number.isSafeInteger(m.sequence)||m.sequence<0||!m.snapshot||!Array.isArray(m.snapshot.slots))return;
    if(retired.has(m.stream_id)||(m.stream_id===stream&&m.sequence<=sequence))return;
    if(stream&&m.stream_id!==stream)retired.add(stream);
    stream=m.stream_id;sequence=m.sequence;snapshot=m.snapshot;render();
    window.endfieldComboRenderedSequence=sequence;
  });
  window.addEventListener('endfield-overlay-config',e=>{config=e.detail||{};render();});
  if(window.endfieldOverlay?.config)config=window.endfieldOverlay.config;
  const cached=window.endfieldOverlay?.snapshots?.combo_snapshot;
  if(cached)window.dispatchEvent(new CustomEvent('endfield-combo-snapshot',{detail:cached}));
  render();
})();
