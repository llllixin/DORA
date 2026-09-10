import { Fragment, useMemo, useState } from 'react';
import type { InsightType } from '../../types';
import { insights, chartData } from '../../data';
import { Tag } from '../../components/ui/Tag';
import { AskBar } from '../../components/dora/AskBar';
import { FollowupCard } from '../../components/dora/FollowupCard';
import { InsightChart } from '../../components/charts/InsightChart';

/*
 * 字段盘点表（W2 frontend-loop-insight，design D3；勿删）
 * | 面板 | 所需字段 | 来源（在线） | 离线兜底 | 降级文案 |
 * | 归因卡 | semantics{causeA,causeB} | /api/insights 同步结构 | data.ts 镜像 semantics | 无 → 归因区显「模板未覆盖」note + 引擎原文（metric/delta/question/factors） |
 * | 置信/来源 | confidence/source | /api/insights | 镜像 | 有则显 |
 * | 下一步建议 | semantics.next | /api/insights | 镜像 | 无 → 「暂无引擎建议（可重新解释刷新）」 |
 * | 图表 | chartData[id] | 前端静态（F11，另立候选） | 静态 | —（注释显式暴露，不假装真实） |
 * 规则：本页不再按洞察 id 写死归因/下一步；cause/next 只消费引擎 semantics。
 */

export function InsightPage({type,selected,onType,onSelect,onTrace,onRoute,onNotice,onRefreshReasoning}:{type:InsightType;selected:number;onType:(t:InsightType)=>void;onSelect:(i:number)=>void;onTrace:(id:string)=>void;onRoute:(type:InsightType,id:string)=>void;onNotice:(m:string)=>void;onRefreshReasoning?:()=>void|Promise<void>}){
 const [explainBusy,setExplainBusy]=useState(false);const runExplain=async()=>{if(explainBusy||!onRefreshReasoning)return;setExplainBusy(true);try{await onRefreshReasoning()}finally{setExplainBusy(false)}};
 const list=insights[type];const x=list[selected]??list[0];const tone=x.type==='problem'?'red':x.type==='opportunity'?'green':'blue';
   const sem = x.semantics;
  const semFacts = sem
    ? [
        { k: x.type === 'problem' ? '主要因素' : x.type === 'opportunity' ? '主要贡献' : '当前变化', name: sem.causeA?.name ?? '', value: sem.causeA?.value ?? '' },
        { k: '进一步定位', name: sem.causeB?.name ?? '', value: sem.causeB?.value ?? '' },
      ]
    : [];
  const nxt = sem?.next ?? null;
  const title = x.type === 'problem' ? '为什么值得处理？' : x.type === 'opportunity' ? '为什么值得放大？' : '为什么值得关注？';
  const more = x.type === 'problem' ? 'Dora 判断必须有数据依据，否则不升级。' : x.type === 'opportunity' ? '机会判断关注“增长来源是否可复制”，而不是简单把上涨标成机会。' : '变化判断关注“是否值得升级”，没有达到阈值时 Dora 不制造噪音。';

 return <section className="page active"><div className="head"><div><div className="eyebrow">INSIGHT · MULTI-LAYER</div><div className="h1">Dora 的业务洞察</div><p className="sub">总览只是入口；真正的判断发生在这里。不同洞察拥有不同的图表、证据和可信度，不共用一套“模板答案”。</p></div><button className="btn" onClick={()=>onNotice('已返回业务脉搏')}>← 返回业务脉搏</button></div>
  <div className="tabs">{(['problem','opportunity','change'] as InsightType[]).map(t=><button key={t} className={'tab '+(type===t?'active':'')} onClick={()=>onType(t)}>{t==='problem'?'问题洞察':t==='opportunity'?'机会洞察':'变化洞察'} · {insights[t].length}</button>)}</div>
  <div className="insight-shell"><div className="card insight-list"><div className="list-head"><b>{type==='problem'?'问题列表':type==='opportunity'?'机会列表':'变化列表'}</b><span>{type==='problem'?'按业务影响排序':type==='opportunity'?'按增长潜力排序':'按重要性排序'}</span></div>{list.map((item,i)=><button key={item.id} className={'insight-item '+(i===selected?'active':'')} aria-selected={i===selected} onClick={()=>onSelect(i)}><div className="itop"><Tag tone={item.type==='problem'?'red':item.type==='opportunity'?'green':'blue'}>{item.tag}</Tag><span className="confidence">置信 <b>{item.confidence}%</b></span></div><div className="iname">{item.title}</div><div className="idesc">{item.desc}</div><div className={'list-status '+(item.type==='change'?'watch':'none')}>{item.type==='change'?'变化先进入持续关注':'未加入行动回路'}</div></button>)}</div>
   <div className="card detail"><div className="detail-top"><div><Tag tone={tone}>{x.tag}</Tag><div className="detail-title">{x.title}</div><div className="detail-sub">{x.desc}</div></div><div className="detail-right"><Tag tone="ai">可信度 {x.confidence}%</Tag><Tag tone={x.reasonSource==='llm'?'green':'blue'}>{(x.reasonSource==='llm'?'AI 解释':'模板解释')}</Tag></div></div>
    <div className="chart-card card"><div className="chart-header"><span>{x.type==='problem'?'异常趋势':x.type==='opportunity'?'增长结构':'变化趋势'}</span><span className="muted">鼠标移动到图表区域查看具体数据</span></div><InsightChart data={chartData[x.id]}/></div>
    <div className="insight-route"><div className="route-node"><b>洞察页</b><p>{x.type==='change'?'先判断变化是否值得继续观察，并设置升级条件。':'先确认影响因素，再决定是否进入执行。'}</p></div><div className="route-arrow">→</div><div className="route-node"><b>{x.type==='change'?'持续关注':'行动回路'}</b><p>{x.type==='change'?'变化先进入持续关注，满足阈值后再升级为问题或机会。':'问题 / 机会直接进入行动回路，形成任务、验证和回写。'}</p></div></div>
    {x.type==='change'&&<div className="change-lifecycle"><h4>变化洞察的升级路径</h4><div className="level-row"><div className="level-badge watch">{x.id==='c2'?'数据事件':'观察中'}</div><div className="level-copy"><b>当前状态：</b>{x.id==='c2'?'数据更新已完成，先确认刷新是否带来新的经营变化。':'当前变化尚未达到升级阈值，先进入持续关注。'}</div></div><div className="level-row"><div className="level-badge op">机会升级</div><div className="level-copy"><b>满足条件：</b>正向变化稳定后，可升级为机会洞察并进入行动回路。</div></div><div className="level-row"><div className="level-badge problem">问题升级</div><div className="level-copy"><b>风险条件：</b>变化继续恶化并突破阈值后，升级为问题洞察，转入行动回路处理。</div></div><div className="logic-strip"><span className="logic-pill">持续关注</span><span className="logic-pill">阈值判断</span><span className="logic-pill">升级为问题 / 机会</span></div></div>}
    <div className="detail-bottom"><div className="panel"><h4>{title}</h4><div className="cause">{semFacts.map((f, i) => (<Fragment key={f.k}>{i > 0 && <div className="arrow">→</div>}<div className={"cause-box" + (i === 0 ? " hot" : "")}><div className="k">{f.k}</div><b>{f.name}</b>{f.value ? <div className="n">{f.value}</div> : null}</div></Fragment>))}{!semFacts.length && (<div className="cause-box"><div className="k">模板未覆盖</div><b>引擎原文</b><div className="n" style={{ fontSize: 11, lineHeight: 1.5 }}>{[x.metric, x.delta, x.question].filter(Boolean).join(" · ")}</div></div>)}</div><div className="confidence-large"><div style={{display:'flex',justifyContent:'space-between'}}><span>为什么相信这次判断</span><b>{x.confidence}%</b></div><div className="cbar"><i style={{width:`${x.confidence}%`}}/></div><div style={{fontSize:12,color:'var(--muted)',marginTop:4}}>{x.source}</div></div><div className="evidence"><div><b>这条洞察有自己的依据</b><br/><span>{more}</span></div><button className="btn" onClick={()=>onTrace(x.id)}>打开证据链 →</button></div></div>
      <div className="panel next-panel"><h4>下一步建议</h4><div className="suggested">{nxt && nxt.length ? nxt.map((n, i) => <div key={n}><span>{i + 1}</span>{n}</div>) : <div style={{ fontSize: 12, opacity: 0.7 }}>暂无引擎建议（可点击「↻ 重新解释」刷新）</div>}</div><FollowupCard title={x.title} question={x.question} onAsk={()=>onNotice(`Dora 已带入问题：“${x.question}”`)} onAction={()=>{onRoute(x.type,x.id);onNotice('已生成行动建议')}} footer={x.type==='change'?'这条变化先进入持续关注，达到阈值后会自动升级为问题或机会。':'这条洞察会生成行动回路，并在行动页形成可切换的任务。'}/></div>
    </div>
    <div className="main-buttons"><button className={`btn ${x.type==='opportunity'?'green':'primary'}`} onClick={()=>onRoute(x.type,x.id)}>{x.type==='change'?'加入持续关注 →':'加入行动回路 →'}</button><button className="btn" onClick={()=>onTrace(x.id)}>查看证据链 →</button><button className="btn" onClick={runExplain} disabled={explainBusy}>{explainBusy?'解释中…':'↻ 重新解释'}</button></div>
   </div>
  </div><AskBar context={`${type==='problem'?'问题':type==='opportunity'?'机会':'变化'}洞察 · ${x.title}`} onSubmit={(q)=>onNotice(q?`Dora：已带入当前洞察上下文：“${q}”`:'可以直接输入一个业务问题。')} suggestions={[x.question,'哪些数据支持这个判断？']}/>
 </section>;
}
