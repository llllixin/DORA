export function FollowupCard({ title, question, footer, onAsk, onAction }: { title:string; question:string; footer:string; onAsk:()=>void; onAction:()=>void }) {
  return <div className="followup-mini"><div className="ask-avatar">D</div><div className="followup-content"><div className="hint">问 Dora · 当前洞察：{title}</div><p>{question}</p></div><div className="followup-actions"><button className="q" onClick={onAsk}>继续追问 ↗</button><button className="q" onClick={onAction}>生成行动</button></div><div className="followup-footer"><span className="dot"/><span>{footer}</span></div></div>;
}
