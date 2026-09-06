import type { Page } from '../../types';
import { capabilities } from '../../data';

const items: [Page,string,string][] = [['pulse','✦','业务脉搏'],['insight','◒','洞察'],['action','↗','行动回路'],['watch','◌','持续关注']];

export function Sidebar({ page, onPage, onCapability, onNotice }: { page: Page; onPage: (p: Page)=>void; onCapability: (name:string)=>void; onNotice:(msg:string)=>void }) {
  return <aside className="sidebar" role="navigation" aria-label="主导航">
    <div className="logo">Dora<small>主动经营回路 · React 全栈前端</small></div>
    <div className="s-title">工作台</div>
    <div className="nav">
      {items.map(([id,icon,label])=><button key={id} className={page===id?'active':''} aria-current={page===id?'page':undefined} onClick={()=>onPage(id)}>{icon} {label}</button>)}
    </div>
    <div className="s-title">Dora 能力</div>
    <div className="cap-grid">
      {Object.keys(capabilities).map(name=><button key={name} onClick={()=>onCapability(name)}>{name}</button>)}
    </div>
    <div className="s-title">系统记录</div>
    <div className="nav">
      <button onClick={()=>onNotice('当前有 3 条 Dora 主动发现')}>◉ Dora发现 <span style={{float:'right',color:'#8d84ff'}}>3</span></button>
      <button onClick={()=>onNotice('最近一次执行：采购价格分析')}>▣ 执行记录</button>
    </div>
    <div className="side-note">能力不消失，只从“用户要理解的结构”变成“Dora 自动编排的底座”。</div>
  </aside>;
}
