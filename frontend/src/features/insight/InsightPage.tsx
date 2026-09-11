import { useEffect, useMemo, useState } from 'react';
import type { InsightType } from '../../types';
import { insights, chartData } from '../../data';
import { Tag } from '../../components/ui/Tag';
import { AskBar } from '../../components/dora/AskBar';
import { InsightChart } from '../../components/charts/InsightChart';
import { askDora } from '../../services/doraApi';

/*
 * 字段盘点表（W2 frontend-loop-insight，design D3；勿删）
 * | 面板 | 所需字段 | 来源（在线） | 离线兜底 | 降级文案 |
 * | 归因卡 | semantics{causeA,causeB} | /api/insights 同步结构 | data.ts 镜像 semantics | 无 → 归因区显「模板未覆盖」note + 引擎原文（metric/delta/question/factors） |
 * | 置信/来源 | confidence/source | /api/insights | 镜像 | 有则显 |
 * | 下一步建议 | semantics.next | /api/insights | 镜像 | 无 → 「暂无引擎建议（可重新解释刷新）」 |
 * | 图表 | chartData[id] | 前端静态（F11，另立候选） | 静态 | —（注释显式暴露，不假装真实） |
 * | 判断列 | /api/dora/chat(why) 判断原文 | dora chat SSE | 引擎 semantics 兜底句 | AI 不可用 → 「引擎语义兜底」note |
 * 规则：本页不再按洞察 id 写死归因/下一步；cause/next 只消费引擎 semantics。
 * 规则：判断列不重复其它区块已有的行——归因行→左栏归因卡、下一步建议→下方面板、历史先例→左栏「历史先例」行（见 belongsElsewhere）。
 */

// 把 AI 判断长文拆成「结论（第一句）」+「补充说明（其余）」，用于突出重点
const splitVerdict = (t: string): { lead: string; rest: string } => {
  const s = (t || '').trim();
  if (!s) return { lead: '', rest: '' };
  const m = s.match(/^[\s\S]*?[。！？!?]/);
  if (m) return { lead: m[0].trim(), rest: s.slice(m[0].length).trim() };
  return { lead: s, rest: '' };
};

export function InsightPage({type,selected,onType,onSelect,onTrace,onRoute,onNotice,onRefreshReasoning}:{type:InsightType;selected:number;onType:(t:InsightType)=>void;onSelect:(i:number)=>void;onTrace:(id:string)=>void;onRoute:(type:InsightType,id:string)=>void;onNotice:(m:string)=>void;onRefreshReasoning?:()=>void|Promise<void>}){
 const [explainBusy,setExplainBusy]=useState(false);const runExplain=async()=>{if(explainBusy||!onRefreshReasoning)return;setExplainBusy(true);try{await onRefreshReasoning()}finally{setExplainBusy(false)}};
 const list=insights[type];const x=list[selected]??list[0];const tone=x.type==='problem'?'red':x.type==='opportunity'?'green':'blue';
  const [listOpen, setListOpen] = useState(true);
  const [restOpen, setRestOpen] = useState(false); // 判断列「补充说明」默认收起，避免长文过载
  // 「为什么值得处理/放大/关注？」= 接入 Dora AI 判断（/api/dora/chat SSE，迭代 42）；失败/离线自动降级为引擎 semantics
  const [judge, setJudge] = useState<{ loading: boolean; text: string; refs: { code: string; title: string }[]; err: boolean }>({ loading: true, text: '', refs: [], err: false });
  useEffect(() => {
    let alive = true;
    setRestOpen(false); // 换洞察时收起补充说明，避免把上一条的展开状态带过来
    setJudge({ loading: true, text: '', refs: [], err: false });
    askDora(x.question || `为什么「${x.title}」值得关注？`, { insightId: x.id, page: 'insight' })
      .then((r) => {
        if (alive) setJudge({ loading: false, text: r.text, refs: (r.references ?? []).map((f) => ({ code: f.code, title: f.title })), err: false });
      })
      .catch(() => {
        if (alive) setJudge({ loading: false, text: '', refs: [], err: true });
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [x?.id]);
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
  // 判断列：先取引擎/AI 原文，再拆成结论 + 补充，突出重点
  const verdictRaw = judge.loading
    ? ''
    : judge.text ||
      (sem
        ? `主要因素：${sem.causeA?.name ?? ''} ${sem.causeA?.value ?? ''}；进一步定位：${sem.causeB?.name ?? ''} ${sem.causeB?.value ?? ''}。`
        : '模板未覆盖该洞察的可视化归因，请查看证据链。');
  const { lead, rest } = splitVerdict(verdictRaw);
  // 判断列「补充说明」按行拆：判断列**只**显示「判断独占」的行；已归属其它区块的行一律不显示（展开也不带出），
  // 否则「为什么值得处理」会复述下方的「下一步建议」面板（同一批 semantics.next）。
  // 例：(chat why 原文) 结论句 / 主要影响因素… / 进一步定位… / 下一步建议… / 历史知识库暂无同指标先例。
  //   → 归因行落进左栏归因卡、下一步建议落进下方面板、历史先例落进左栏「历史先例」行。
  const restLines = rest ? rest.split(/\n+/).map((l) => l.trim()).filter(Boolean) : [];
  const belongsElsewhere = [
    /^(主要影响因素|主要因素|主要贡献|当前变化|进一步定位)[：:]/, // → 左栏归因卡
    /^下一步建议[：:]/, // → 下方「下一步建议」面板
    /^(可参考历史先例|历史知识库暂无同指标先例)/, // → 左栏「历史先例」行
  ];
  const ownRest = restLines.filter((l) => !belongsElsewhere.some((re) => re.test(l)));
  const shownRest = restOpen ? ownRest : ownRest.slice(0, 2);
  const moreRest = ownRest.length - shownRest.length;

 return <section className="page active"><div className="head"><div><div className="eyebrow">INSIGHT · MULTI-LAYER</div><div className="h1">Dora 的业务洞察</div><p className="sub">总览只是入口；真正的判断发生在这里。不同洞察拥有不同的图表、证据和可信度，不共用一套“模板答案”。</p></div><button className="btn" onClick={()=>onNotice('已返回业务脉搏')}>← 返回业务脉搏</button></div>
  <div className="tabs">{(['problem','opportunity','change'] as InsightType[]).map(t=><button key={t} className={'tab '+(type===t?'active':'')} onClick={()=>onType(t)}>{t==='problem'?'问题洞察':t==='opportunity'?'机会洞察':'变化洞察'} · {insights[t].length}</button>)}</div>
  <div className="insight-shell"><aside className={'insight-drawer'+(listOpen?' open':'')}><div className="insight-drawer-head">{listOpen&&<b>{type==='problem'?'问题列表':type==='opportunity'?'机会列表':'变化列表'}</b>}<button className="drawer-toggle" onClick={()=>setListOpen(v=>!v)} title={listOpen?'收起':'展开'}>{listOpen?'‹ 收起':'›'}</button></div>{listOpen&&<><div className="list-head"><span>{type==='problem'?'按业务影响排序':type==='opportunity'?'按增长潜力排序':'按重要性排序'}</span></div>{list.map((item,i)=><button key={item.id} className={'insight-item '+(i===selected?'active':'')} aria-selected={i===selected} onClick={()=>onSelect(i)}><div className="itop"><Tag tone={item.type==='problem'?'red':item.type==='opportunity'?'green':'blue'}>{item.tag}</Tag><span className="confidence">置信 <b>{item.confidence}%</b></span></div><div className="iname">{item.title}</div><div className="idesc">{item.desc}</div><div className={'list-status '+(item.type==='change'?'watch':'none')}>{item.type==='change'?'变化先进入持续关注':'未加入行动回路'}</div></button>)}</>}</aside>
   <div className="card detail"><div className="detail-top"><div><Tag tone={tone}>{x.tag}</Tag><div className="detail-title">{x.title}</div><div className="detail-sub">{x.desc}</div></div><div className="detail-right"><Tag tone="ai">可信度 {x.confidence}%</Tag><Tag tone={x.reasonSource==='llm'?'green':'blue'}>{(x.reasonSource==='llm'?'AI 解释':'模板解释')}</Tag></div></div>
    <div className="chart-card card"><div className="chart-header"><span>{x.type==='problem'?'异常趋势':x.type==='opportunity'?'增长结构':'变化趋势'}</span><span className="muted">鼠标移动到图表区域查看具体数据</span></div><InsightChart data={chartData[x.id]}/></div>
    <div className="insight-route"><div className="route-node"><b>洞察页</b><p>{x.type==='change'?'先判断变化是否值得继续观察，并设置升级条件。':'先确认影响因素，再决定是否进入执行。'}</p></div><div className="route-arrow">→</div><div className="route-node"><b>{x.type==='change'?'持续关注':'行动回路'}</b><p>{x.type==='change'?'变化先进入持续关注，满足阈值后再升级为问题或机会。':'问题 / 机会直接进入行动回路，形成任务、验证和回写。'}</p></div></div>
    {x.type==='change'&&<div className="change-lifecycle"><h4>变化洞察的升级路径</h4><div className="level-row"><div className="level-badge watch">{x.id==='c2'?'数据事件':'观察中'}</div><div className="level-copy"><b>当前状态：</b>{x.id==='c2'?'数据更新已完成，先确认刷新是否带来新的经营变化。':'当前变化尚未达到升级阈值，先进入持续关注。'}</div></div><div className="level-row"><div className="level-badge op">机会升级</div><div className="level-copy"><b>满足条件：</b>正向变化稳定后，可升级为机会洞察并进入行动回路。</div></div><div className="level-row"><div className="level-badge problem">问题升级</div><div className="level-copy"><b>风险条件：</b>变化继续恶化并突破阈值后，升级为问题洞察，转入行动回路处理。</div></div><div className="logic-strip"><span className="logic-pill">持续关注</span><span className="logic-pill">阈值判断</span><span className="logic-pill">升级为问题 / 机会</span></div></div>}
    <div className="detail-bottom one-col">
      <div className="panel">
        <h4>{title}</h4>
        <div className="judge-grid">
          <div className="judge-col judge-facts">
            <div className="jc-head"><span className="jc-title">事实 · 具体数据</span><span className="jc-note">引擎计算</span></div>
            <div className="ev-list">
              <div className="ev-row"><b>关键数值</b><span>{[x.metric, x.delta].filter(Boolean).join(' / ')}</span></div>
              {x.trigger ? <div className="ev-row"><b>触发条件</b><span>{x.trigger}</span></div> : null}
              {!semFacts.length && x.factors?.length ? <div className="ev-row"><b>归因因素</b><span>{x.factors.join(' · ')}</span></div> : null}
              <div className="ev-row"><b>证据来源</b><span>{x.source}{x.evidence?.kind ? <> <code className="ev-code">{x.evidence.kind}</code></> : null}</span></div>
              {judge.refs.length ? (
                <div className="ev-row"><b>历史先例</b><span>{judge.refs.map((r) => `${r.title}（${r.code}）`).join('、')}</span></div>
              ) : !judge.loading && !judge.err ? (
                // 检索确实为空（chat 的 references 来自真实 search_knowledge），如实陈述，避免它挤进判断列
                <div className="ev-row"><b>历史先例</b><span className="ev-none">暂无同指标先例</span></div>
              ) : null}
            </div>
            <div className="cause-grid">
              {semFacts.map((f) => (
                <div key={f.k} className="cause-item">
                  <span className="k">{f.k}</span>
                  <b>{f.name}</b>
                  {f.value ? <em>{f.value}</em> : null}
                </div>
              ))}
              {!semFacts.length && (
                <div className="cause-item">
                  <span className="k">模板未覆盖</span>
                  <b>引擎原文</b>
                  <em style={{ fontSize: 12 }}>{[x.metric, x.delta, x.question].filter(Boolean).join(" · ")}</em>
                </div>
              )}
            </div>
          </div>
          <div className="judge-col verdict">
            <div className="jc-head"><span className="jc-title">判断</span><Tag tone="ai">Dora AI 判断</Tag></div>
            {judge.loading ? (
              <p className="verdict-lead muted">正在结合证据判断…</p>
            ) : (
              <>
                <p className="verdict-lead">{lead}</p>
                {shownRest.length ? <p className="verdict-rest">{shownRest.join('\n')}</p> : null}
                {moreRest > 0 ? (
                  <button className="verdict-toggle" onClick={() => setRestOpen((v) => !v)}>{restOpen ? '收起补充说明' : `展开补充说明（还有 ${moreRest} 行）`}</button>
                ) : null}
              </>
            )}
            {judge.err && !judge.loading ? <div className="verdict-note">AI 暂不可用，以上为引擎语义兜底</div> : null}
            <div className="verdict-conf">
              <div className="verdict-bar"><span>置信度</span><b>{x.confidence}%</b></div>
              <div className="cbar"><i style={{ width: `${x.confidence}%` }} /></div>
            </div>
          </div>
        </div>
        <div className="evidence"><div><b>这条洞察有自己的依据</b><br /><span>{more}</span></div><button className="btn" onClick={() => onTrace(x.id)}>打开证据链 →</button></div>
      </div>
      <div className="panel next-panel"><h4>下一步建议</h4><div className="suggested">{nxt && nxt.length ? nxt.map((n, i) => <div key={n}><span>{i + 1}</span>{n}</div>) : <div style={{ fontSize: 12, opacity: 0.7 }}>暂无引擎建议（可点击「↻ 重新解释」刷新）</div>}</div>{null}</div>
    </div>
    <div className="main-buttons"><button className={`btn ${x.type==='opportunity'?'green':'primary'}`} onClick={()=>onRoute(x.type,x.id)}>{x.type==='change'?'加入持续关注 →':'加入行动回路 →'}</button><button className="btn" onClick={()=>onTrace(x.id)}>查看证据链 →</button><button className="btn" onClick={runExplain} disabled={explainBusy}>{explainBusy?'解释中…':'↻ 重新解释'}</button></div>
   </div>
  </div><AskBar context={`${type==='problem'?'问题':type==='opportunity'?'机会':'变化'}洞察 · ${x.title}`} onSubmit={(q)=>onNotice(q?`Dora：已带入当前洞察上下文：“${q}”`:'可以直接输入一个业务问题。')} suggestions={[x.question,'哪些数据支持这个判断？']}/>
 </section>;
}
