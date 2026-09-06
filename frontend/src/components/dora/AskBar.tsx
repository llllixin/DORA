import { useState } from 'react';
export function AskBar({ context, onSubmit, suggestions = ['今天最需要处理的是什么？','有哪些增长机会？'] }: { context:string; onSubmit:(text:string)=>void; suggestions?:string[] }) {
  const [value,setValue] = useState('');
  const submit=()=>{onSubmit(value); if(value.trim()) setValue('');};
  return <div className="ask"><div className="ask-avatar">D</div><div className="ask-main"><div className="hint">问 Dora · 当前上下文：{context}</div><input value={value} onChange={e=>setValue(e.target.value)} onKeyDown={e=>e.key==='Enter'&&submit()} placeholder="例如：为什么它值得关注？ / 哪些数据支持这个判断？"/></div><div className="ask-chips">{suggestions.map(s=><button className="ask-chip" key={s} onClick={()=>setValue(s)}>{s.replace(/[？?]/,'')}</button>)}</div><button className="btn" onClick={submit}>发送 ↗</button></div>;
}
