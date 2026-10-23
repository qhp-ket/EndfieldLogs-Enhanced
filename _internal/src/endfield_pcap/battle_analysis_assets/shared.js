'use strict';
const A = window.Analysis = {
  data: null, bridge: null,
  state: {character:'', buffs:false, fallback:false, zoom:100, graphics:100, unit:'seconds', details:false, detailsMaximized:false, expanded:[], roleWidth:120, trackWidth:200, tab:'timeline', curve:'damage'},
  colors: ['#61c4df','#8ccc4b','#f0c971','#b291ed','#ff8b72'],
  categoryColors: {'重击':'#567594','战技':'#168c7b','连携':'#8060b4','大招':'#ae761d','其他':'#69798b','BUFF':'#ad526a'},
  $: id => document.getElementById(id),
  esc: value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  num: value => value === null || value === undefined ? '未知' : Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2}),
  time: value => A.state.unit === 'frames' ? `${(value*.03).toFixed(2)}F` : `${(value/1000).toFixed(3)}s`,
  color: key => A.colors[Math.max(0,A.data.participants.findIndex(p => p.character_key===key))%A.colors.length],
  textTip(event,text) {
    const tip=A.$('tooltip'); tip.textContent=text; tip.hidden=false;
    tip.style.left=`${Math.max(8,Math.min(event.clientX+16,innerWidth-tip.offsetWidth-10))}px`;
    tip.style.top=`${Math.max(8,Math.min(event.clientY+16,innerHeight-tip.offsetHeight-10))}px`;
  },
  hideTip() { A.tipRevision++; A.$('tooltip').hidden=true; },
  tipRevision:0,
  hover(event,kind,index,stamp) {
    const revision=++A.tipRevision, point={clientX:event.clientX,clientY:event.clientY};
    A.bridge.hover(kind,index,stamp,A.state.unit,text => {if(revision===A.tipRevision) A.textTip(point,text);});
  },
  table(headers,rows,attrs=()=>'',tips=()=> '') {
    if(!rows.length) return '<div class="empty">没有可展示的记录</div>';
    return `<table><thead><tr>${headers.map(h=>`<th>${A.esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((row,i)=>`<tr ${attrs(i)}>${row.map((v,j)=>`<td title="${A.esc(tips(i,j)||v)}">${A.esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  },
  changed() { A.hideTip(); A.bridge.saveState(JSON.stringify(A.state)); },
  fail(message) { A.$('record-name').textContent='战斗分析加载失败'; A.$('failure').hidden=false; A.$('failure').textContent=String(message); }
};
window.addEventListener('error',event=>A.fail(event.message));
window.addEventListener('unhandledrejection',event=>A.fail(event.reason));
document.addEventListener('mouseleave',()=>A.hideTip());
document.addEventListener('scroll',()=>A.hideTip(),true);
