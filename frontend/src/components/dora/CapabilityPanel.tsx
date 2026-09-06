import { capabilities } from '../../data';
export function CapabilityPanel({ name,onClose }: { name:string|null; onClose:()=>void }) {
 if(!name) return null; return <div className="cap-overlay" onMouseDown={onClose}><div className="cap-panel open" onMouseDown={e=>e.stopPropagation()}><button className="close" onClick={onClose}>×</button><div className="eyebrow">DORA CAPABILITY</div><h2 style={{margin:'4px 0 0'}}>{name}</h2><p>这些能力仍然存在，但不再要求用户先理解产品结构。</p><div className="cap-grid-large">{(capabilities[name]??[]).map(([a,p])=><div className="cap-card" key={a}><b>{a}</b><p>{p}</p></div>)}</div></div></div>;
}
