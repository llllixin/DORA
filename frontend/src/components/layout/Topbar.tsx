import type { Page } from '../../types';
const labels: Record<Page,string> = { pulse:'业务脉搏', insight:'洞察', action:'行动回路', watch:'持续关注', knowledge:'知识库' };
export function Topbar({ page, onTrace, onNotice, onUpdateData }: { page: Page; onTrace:()=>void; onNotice:(msg:string)=>void; onUpdateData:()=>void }) {
  return <header className="topbar"><div className="crumb">工作空间 <b>/</b> 门店经营 <b>/</b> <b>{labels[page]}</b></div><div className="top-actions"><button className="top-btn" onClick={onUpdateData}>⟳ 更新数据</button><button className="top-btn" onClick={()=>onNotice('主动构建链：数据 → 口径 → 值得关注 → 洞察 → 行动 → 持续关注')}>⌁ 主动构建链</button><button className="top-btn" onClick={onTrace}>↗ 数据证据链</button><div className="avatar">T</div></div></header>;
}
