import { useCallback, useEffect, useState } from 'react';
import type { InsightType, Page } from '../../types';
import { insights, watchItems, capabilities, autoExpertNotes } from '../../data';
import { Tag } from '../../components/ui/Tag';
import { AskBar } from '../../components/dora/AskBar';
import { createWatch, deleteWatch, detectApi, syncRemoteData } from '../../services/doraApi';
import { followTargetFor, followedTargetOf, heroFor, monitorsFrom, signalsFrom } from './pulseView';

export function PulsePage({
  onPage,
  onInsight,
  onTrace,
  onNotice,
  dataLabel = '门店经营数据.xlsx · 09:32 更新',
}: {
  onPage: (p: Page) => void;
  onInsight: (t: InsightType, idx?: number) => void;
  onTrace: (id: string) => void;
  onNotice: (m: string) => void;
  dataLabel?: string;
}) {
  const [problem, setProblem] = useState<string>('');
  const [followBusy, setFollowBusy] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [tick, setTick] = useState(0);
  const expertEntries = capabilities['专家团'] ?? [];
  const [expert, setExpert] = useState<string>(expertEntries[0]?.[0] ?? '');

  const refresh = useCallback(async () => {
    let ok = false;
    try {
      ok = await syncRemoteData();
    } catch {
      ok = false;
    }
    setOnline(ok);
    setTick((t) => t + 1);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const list = insights.problem;
  // 默认焦点 = 第一个引擎问题（不再写死固定 id）；问题列表变化时 clamp/reset（review P1-2）
  useEffect(() => {
    if (list.length && !list.some((x) => x.id === problem)) setProblem(list[0].id);
  }, [list.length, problem, tick]);

  const cur = list.find((x) => x.id === problem) ?? list[0];
  const hero = heroFor(cur);
  const signalRows = signalsFrom(insights.opportunity, insights.change);
  const monitorRows = monitorsFrom(watchItems, list);
  const followText = cur ? followTargetFor(cur) : null;
  const followed = cur ? followedTargetOf(cur, watchItems) : null;
  const followHint = !cur
    ? ''
    : online === false
      ? '后端离线：无法真实建档（演示模式）'
      : !followText
        ? '该洞察暂不支持一键委托，可到持续关注页输入委托'
        : '';

  const doFollow = async () => {
    if (!cur || !followText) return;
    setFollowBusy(true);
    try {
      const up = await detectApi();
      if (!up) {
        onNotice('✗ 后端离线：无法真实建档「持续关注」，请先启动后端');
        return;
      }
      const r = await createWatch(followText);
      if (!r.target) {
        onNotice('✗ 未能真实建档（离线/演示模式不落库）');
        return;
      }
      onNotice(`✓ 已创建持续关注「${r.target.name}」，可到持续关注页管理`);
      await refresh();
    } catch (err) {
      onNotice(`✗ 建档失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setFollowBusy(false);
    }
  };

  const cancelFollow = async () => {
    if (!cur) return;
    const t = followedTargetOf(cur, watchItems);
    if (!t) return;
    setFollowBusy(true);
    try {
      const up = await detectApi();
      if (!up) {
        onNotice('✗ 后端离线：无法取消委托（演示模式不落库）');
        return;
      }
      await deleteWatch(t.id);
      onNotice(`✓ 已取消持续关注「${t.name}」`);
      await refresh();
    } catch (err) {
      onNotice(`✗ 取消失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setFollowBusy(false);
    }
  };

  return (
    <section className="page active">
      <div className="head">
        <div>
          <div className="eyebrow">BUSINESS PULSE · OVERVIEW</div>
          <div className="h1">今天，有什么业务值得你关注？</div>
          <p className="sub">数据更新后，Dora 自动完成“理解数据 → 判断重要性 → 形成业务脉络”。这里是总览入口，不在这里解决问题。</p>
        </div>
        <div className="status">
          <span className="dot" />
          {dataLabel}
          {online === false && <Tag tone="ai">离线演示</Tag>}
        </div>
      </div>
      <div className="summary">
        <Summary label="需要处理" num={String(insights.problem.length)} cls="problem" desc="高影响问题 · 优先进入问题洞察" onClick={() => onInsight('problem')} />
        <Summary label="增长机会" num={String(insights.opportunity.length)} cls="opportunity" desc="可放大机会 · 看增长来源" onClick={() => onInsight('opportunity')} />
        <Summary label="重要变化" num={String(insights.change.length)} cls="change" desc="正在观察 · 看是否升级" onClick={() => onInsight('change')} />
        <Summary label="持续关注" num={String(watchItems.length)} cls="watch" desc="Dora 正在替你持续检查" onClick={() => onPage('watch')} />
      </div>
      <div className="cockpit-kicker">
        <span>今日经营主线</span>
        <span className="line" />
        <span>先判断优先级，再进入洞察</span>
      </div>
      <div className="pulse-layout">
        <div className="card hero pulse-priority">
          {cur ? (
            <>
              <div className="priority-meta">
                <Tag tone="red">{cur.tag}</Tag>
                <span className="priority-score">置信 {cur.confidence}%</span>
              </div>
              <div className="priority-title">{cur.title}</div>
              <div className="priority-copy">{hero.copy}</div>
              <div className="value-line">
                <span className="value">{cur.metric}</span>
                <span className={cur.delta.startsWith('↑') ? 'delta-up' : 'down'}>{cur.delta}</span>
              </div>
              {hero.reason && (
                <div className="reason">
                  <b>Dora 判断：</b>
                  {hero.reason}
                </div>
              )}
              {hero.note && <div className="reason" style={{ opacity: 0.75 }}>{hero.note}</div>}
              <div className="priority-evidence">
                {hero.facts.map((f) => (
                  <div className="fact" key={f.k}>
                    <div className="k">{f.k}</div>
                    <div className="v">{f.v}</div>
                  </div>
                ))}
              </div>
              <div className="main-buttons">
                <button className="btn primary" onClick={() => onInsight('problem', list.findIndex((i) => i.id === cur.id))}>进入当前问题洞察 →</button>
                {followed ? (
                  <>
                    <button className="btn soft" disabled>已加入跟进 ✓</button>
                    <button className="btn" disabled={followBusy} onClick={() => void cancelFollow()}>取消委托</button>
                  </>
                ) : (
                  <button
                    className="btn soft"
                    disabled={!followText || online !== true || followBusy}
                    title={followHint}
                    onClick={followText && online === true ? () => void doFollow() : undefined}
                  >
                    {followBusy ? '处理中…' : '让 Dora 帮我跟进'}
                  </button>
                )}
                <button className="btn" onClick={() => onTrace(cur.id)}>查看当前问题证据链</button>
              </div>
              {followed && (
                <div className="followup-mini">
                  <div className="ask-avatar">D</div>
                  <div className="followup-content">
                    <div className="hint">Dora 正在替你持续检查（真实委托）</div>
                    <p>{followed.name} · {followed.logic || '关注中'}</p>
                  </div>
                  <Tag tone="ai">自动监控</Tag>
                  <button className="btn" style={{ marginLeft: 8 }} onClick={() => onPage('watch')}>管理 →</button>
                </div>
              )}
              <div className="problem-stack">
                <div className="problem-stack-head"><b>业务脉络 · 问题</b><span>{list.length} 条问题 · 可上下滑动查看</span></div>
                <div className="problem-list">
                  {list.map((x) => (
                    <div key={x.id} className={'problem-item ' + (x.id === cur.id ? 'active selected' : '')}>
                      <button className="problem-toggle" onClick={() => setProblem(x.id === cur.id ? '' : x.id)}>
                        <div className="meta"><b>{x.title}</b><div className="subline">{x.desc}</div></div>
                        <div className="mini"><Tag tone="red">{x.metric}</Tag><Tag>{x.delta}</Tag><Tag>{x.source}</Tag></div>
                      </button>
                      <div className="problem-evidence">
                        <span>证据：{x.source}</span>
                        <button className="btn" onClick={(e) => { e.stopPropagation(); onTrace(x.id); }}>证据链</button>
                      </div>
                    </div>
                  ))}
                  {!list.length && <div className="action-empty">暂无引擎判定的问题；数据更新后会自动出现。</div>}
                </div>
              </div>
            </>
          ) : (
            <div className="action-empty">暂无引擎判定的问题；数据更新后会自动出现在这里。</div>
          )}
        </div>

        <div className="cockpit-side">
          <div className="card monitor-card">
            <div className="monitor-head">
              <h3>Dora 监控状态</h3>
              <span className="monitor-count">{watchItems.length} 个目标运行中</span>
            </div>
            <div className="monitor-stat">
              <div><b>{monitorRows.length}</b><span>持续关注目标</span></div>
              <div><b>{list.length}</b><span>引擎判定问题</span></div>
            </div>
            <div className="monitor-list">
              {monitorRows.map((m) => <Monitor key={m.name} name={m.name} sub={m.sub} status={m.status} />)}
              {!monitorRows.length && <div style={{ padding: '8px 0', fontSize: 12, opacity: 0.7 }}>暂无持续关注委托；可在下方「让 Dora 帮我跟进」或持续关注页建立。</div>}
            </div>
            <button className="btn full" onClick={() => onPage('watch')}>查看全部关注目标 →</button>
          </div>
          <div className="card monitor-card">
            <div className="monitor-head"><h3>本轮 Dora 工作</h3><Tag tone="ai">自动运行</Tag></div>
            <Step done title="读取与清洗数据" sub={dataLabel} />
            <Step done title="建立经营口径" sub="销售 / 利润 / 客单价 / 库存" />
            <Step active title="判断值得关注什么" sub={`${insights.problem.length} 问题 · ${insights.opportunity.length} 机会 · ${insights.change.length} 变化`} />
            <div className="auto">
              <div className="auto-title">自动编排 · 专家团能力说明</div>
              <div className="auto-tags">
                {expertEntries.map(([name]) => (
                  <button
                    key={name}
                    className={'auto-tag ' + (expert === name ? 'active' : '')}
                    onClick={() => setExpert(name)}
                  >
                    {name}
                  </button>
                ))}
              </div>
              {expert && (
                <div className="auto-note">
                  <b>{expert}</b>：{(expertEntries.find(([n]) => n === expert)?.[1] ?? '')}
                  {autoExpertNotes[expert] ? ` ${autoExpertNotes[expert]}` : ''}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="card signal-board">
        <div className="signal-board-head">
          <div><h3>其他经营信号</h3><p>这里承接主线之外的机会与变化，不与 P1 问题争夺视觉焦点。</p></div>
          <div className="signal-tabs">
            <button className="signal-tab active">全部 {signalRows.length}</button>
            <button className="signal-tab" onClick={() => onInsight('opportunity')}>机会 {insights.opportunity.length}</button>
            <button className="signal-tab" onClick={() => onInsight('change')}>变化 {insights.change.length}</button>
          </div>
        </div>
        <div className="signal-list">
          {signalRows.map((s) => (
            <Signal key={`${s.kind}-${s.title}`} type={s.kind} title={s.title} desc={s.desc} value={s.value} onClick={() => onInsight(s.kind === 'op' ? 'opportunity' : 'change')} />
          ))}
          {!signalRows.length && <div style={{ padding: 12, fontSize: 12, opacity: 0.7 }}>暂无该类信号（引擎当前未产出机会/变化洞察）。</div>}
        </div>
      </div>

      <AskBar context="门店经营总览" onSubmit={(q) => onNotice(q ? `Dora：已带入“${q}”并继续分析。` : '可以直接输入一个业务问题。')} />
    </section>
  );
}

function Summary({ label, num, cls, desc, onClick }: { label: string; num: string; cls: string; desc: string; onClick: () => void }) {
  return (
    <button className={`card summary-card ${cls}`} onClick={onClick}>
      <div className="label">{label}</div>
      <div className="num">{num}</div>
      <div className="desc">{desc}</div>
    </button>
  );
}

function Monitor({ name, sub, status }: { name: string; sub: string; status: string }) {
  return (
    <div className="monitor-item">
      <div><b>{name}</b><span> · {sub}</span></div>
      <span>{status}</span>
    </div>
  );
}

function Step({ title, sub, done, active }: { title: string; sub: string; done?: boolean; active?: boolean }) {
  return (
    <div className={'step ' + (done ? 'done ' : '') + (active ? 'active' : '')}>
      <div className="step-icon">{done ? '✓' : '●'}</div>
      <div><b>{title}</b><p>{sub}</p></div>
    </div>
  );
}

function Signal({ type, title, desc, value, onClick }: { type: 'op' | 'ch'; title: string; desc: string; value: string; onClick: () => void }) {
  const parts = value.split(' · ');
  return (
    <div className="signal-row">
      <div className={`signal-kind ${type}`}>{type === 'op' ? '增长机会' : '重要变化'}</div>
      <div className="signal-main"><b>{title}</b><p>{desc}</p></div>
      <div className="signal-value"><span className="base">{parts[0] ?? value}</span>{parts[1] ? <span className={`delta ${type === 'op' ? 'pos' : 'neutral'}`}>{parts[1]}</span> : null}</div>
      <button className="btn signal-action" onClick={onClick}>查看 →</button>
    </div>
  );
}
