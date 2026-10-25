(() => {
  const keys=document.getElementById('keys'),status=document.getElementById('status');
  let stream=null,sequence=-1;const retired=new Set();
  function label(code){
    if(code.startsWith('K:')){
      const key=code.slice(2),number=Number(key);
      if(number>=48&&number<=90)return String.fromCharCode(number);
      if(number>=112&&number<=135)return 'F'+(number-111);
      return {32:'空格',27:'Esc',13:'Enter',9:'Tab',8:'Backspace'}[key]||key;
    }
    return code.replace('P:','手柄 ').replace('M:','鼠标 ');
  }
  window.addEventListener('endfield-input-snapshot',e=>{
    const m=e.detail;
    if(!m||m.type!=='input_snapshot'||m.schema_version!==1||!m.snapshot||typeof m.stream_id!=='string'||
       !Number.isSafeInteger(m.sequence)||m.sequence<0||retired.has(m.stream_id)||(stream===m.stream_id&&m.sequence<=sequence))return;
    if(stream&&stream!==m.stream_id){retired.add(stream);keys.replaceChildren();}
    stream=m.stream_id;sequence=m.sequence;
    const s=m.snapshot;
    status.textContent=({recording:'仅游戏前台',waiting_game:'等待游戏前台',error:'记录故障',stopped:'输入记录未开启'})[s.status]||'正在启动';
    const recent=['recording','waiting_game'].includes(s.status)?s.recent||[]:[];
    const existing=new Map([...keys.children].map(n=>[n.dataset.seq,n]));
    const keep=new Set();
    for(const item of recent){const id=String(item.seq);keep.add(id);let node=existing.get(id);
      if(!node){node=document.createElement('kbd');node.dataset.seq=id;node.textContent=label(item.code);node.title=`${item.device} · ${item.code}`;keys.append(node);}}
    for(const [id,node] of existing)if(!keep.has(id))node.remove();
  });
})();
