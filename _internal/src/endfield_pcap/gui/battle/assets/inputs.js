'use strict';
A.inputColors={skill:'#3287ef',ultimate:'#ed9b32',combo:'#ad65e3',switch:'#699ca5',other:'#8492a4'};
A.renderInputEvidence=function(){
  const evidence=A.data.inputs||{},actions=(evidence.actions||[]).filter(a=>(['skill','ultimate','combo'].includes(a.action)||evidence.settings?.show_other)
    && (!A.state.character||a.action==='combo'||!a.character_key||a.character_key===A.state.character));
  const orphan=actions.filter(a=>a.action!=='combo'&&!document.querySelector(`.plot-row[data-input-owner="${CSS.escape(a.character_key||'')}"]`));
  let inputRow;
  if(orphan.length||evidence.raw?.length)inputRow=A.addRow('输入','独立输入证据',44*A.scale).plot;
  for(const row of A.$('timeline-grid').querySelectorAll('.plot-row:not(.ruler)')){
    const owner=row.dataset.inputOwner;
    const selected=actions.filter(a=>a.action==='combo'||(owner&&a.character_key===owner)||(row===inputRow&&orphan.includes(a)));
    row.inputEvidence=selected;
    for(const action of selected){
      const left=Math.max(0,A.x(action.start_ms)),right=Math.min(A.plotWidth,A.x(action.end_ms));
      if(right<left)continue;
      const span=document.createElement('span');span.className='input-evidence';
      span.style.cssText=`position:absolute;pointer-events:none;z-index:5;left:${left}px;top:0;height:100%;width:${Math.max(1,right-left)}px;border-left:2px ${action.action==='combo'||action.interrupted?'dashed':'solid'} ${A.inputColors[action.action]||A.inputColors.other};background:${A.inputColors[action.action]||A.inputColors.other}24;${action.interrupted?'border-right:1px dashed '+A.inputColors[action.action]+';':''}`;
      row.append(span);
    }
  }
  if(inputRow){
    const buckets=new Map();
    for(const raw of evidence.raw||[])buckets.set(`${raw.device}:${raw.code}:${Math.round(A.x(raw.time_ms))}`,raw);
    inputRow.rawInputs=[...buckets.values()];
    for(const raw of buckets.values()){
      const dot=document.createElement('span');
      const v=typeof raw.value==='number'?Math.max(-1,Math.min(1,raw.value/32768)):0;
      dot.style.cssText=`position:absolute;pointer-events:none;left:${A.x(raw.time_ms)}px;top:${22*A.scale-v*15*A.scale}px;width:2px;height:2px;background:#899ab3`;
      inputRow.append(dot);
    }
  }
};
A.inputHover=function(row,event,stamp){
  const tolerance=A.duration/A.plotWidth*4;
  const action=row.inputEvidence?.find(a=>Math.abs(a.start_ms-stamp)<tolerance||(a.start_ms<=stamp&&stamp<=a.end_ms));
  if(action){A.textTip(event,action.tooltip);return true;}
  const raw=row.rawInputs?.find(a=>Math.abs(a.time_ms-stamp)<tolerance);
  if(raw){A.textTip(event,`${A.time(raw.time_ms)} · ${raw.device} · ${raw.code}\n${JSON.stringify(raw.value)}`);return true;}
  return false;
};
