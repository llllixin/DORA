import { useEffect, useState } from 'react';
import { AskBar } from '../../components/dora/AskBar';
import { Tag } from '../../components/ui/Tag';
import type { WatchParseIntent, WatchTargetCard, WatchTrendPoint } from '../../types';
import { createAction, createWatch, deleteWatch, listWatch, parseWatch, searchKnowledge, setWatchStatusStrict, checkWatchStrict } from '../../services/doraApi';
import type { KnowledgeHit } from '../../services/doraApi';
import { buildDelegateFlow, conditionText, flowSummary, frequencyText } from './delegateFlow';
import type { DelegateStepState } from './delegateFlow';
import { archiveState, handoffState, sparkLine, splitTargets, SPARK_H, SPARK_W, trendQuery, trendSummary, watchCounts } from './trendView';

// 频率选项文案与面板步骤 note 共用同一份（单一事实源，避免两处分叉）
const FREQS: { value: string; label: string }[] = ['on_update', 'daily 09:00', 'weekly'].map((value) => ({
  value,
  label: frequencyText(value),
}));

// 面板步骤态 → 既有 Tag 色调/文案（watch-delegate-flow D3：状态由真实委托推导，组件只渲染）
const STEP_TONE: Record<DelegateStepState, 'default' | 'green' | 'blue' | 'red'> = {
  done: 'green', active: 'blue', paused: 'default', pending: 'default', handoff: 'red',
};
// 头部状态 pill → 既有 Tag 色调（与步骤态同源，D3）
const FLOW_TONE: Record<string, 'default' | 'red' | 'green' | 'blue' | 'ai'> = {
  idle: 'default', parsed: 'ai', watching: 'green', hit: 'blue', escalated: 'red', paused: 'default', offline: 'ai',
};
const STEP_TEXT: Record<DelegateStepState, string> = {
  done: '已完成', active: '进行中', paused: '已暂停', pending: '待推进', handoff: '已移交',
};
const SUGGESTS = ['关注利润率', '关注库存周转', '关注华东订单量', '关注新品销量', '关注退货率', '关注高客单门店占比'];

/** 走向折线：只用卡片 `trend.points` 渲染（不新增请求）；`viewBox` 固定 + 等比缩放（迭代 43 结论）。 */
function Spark({ points, direction, label, className = '' }: {
  points: WatchTrendPoint[];
  direction: string;
  label: string;
  className?: string;
}) {
  const { d, dots, flat } = sparkLine(points);
  return (
    <svg
      className={`spark ${direction} ${className}`.trim()}
      viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={label}
    >
      {d && <path className="spark-line" d={d} />}
      {dots.map((p, i) => (
        <circle key={i} className="spark-dot" cx={p.x} cy={p.y} r={flat || dots.length === 1 ? 2.2 : 1.4} />
      ))}
    </svg>
  );
}

type Props = { onTrace: (id: string) => void; onNotice: (m: string) => void; onInsight: (id: string) => void; onAction?: () => void };

export function WatchPage({ onNotice, onAction, onInsight }: Props) {
  const [input, setInput] = useState('帮我关注华东订单量，如果连续三天下降就提醒我');
  const [freq, setFreq] = useState('on_update');
  const [intent, setIntent] = useState<WatchParseIntent | null>(null);
  const [error, setError] = useState('');
  const [targets, setTargets] = useState<WatchTargetCard[]>([]);
  const [offline, setOffline] = useState(false);      // D5：load() 回退演示数据即离线
  const [focusId, setFocusId] = useState<string | null>(null); // D4：面板跟随的当前委托
  // watch-goal-workbench：工作台状态（决策 5/10）
  const [selectedId, setSelectedId] = useState<string | null>(null); // 标题区点选的委托
  const [flowOpen, setFlowOpen] = useState(false);                   // 提示条默认折叠
  const [hits, setHits] = useState<KnowledgeHit[] | null>(null);     // 工具② 结果（null = 尚未检索）
  const [searchNote, setSearchNote] = useState('');                  // 工具② 说明（空命中 / 失败）
  const [searching, setSearching] = useState(false);
  const [archived, setArchived] = useState<{ code: string; created: boolean } | null>(null); // 工具③ 成功结果
  const [archiveErr, setArchiveErr] = useState('');                  // 工具③ 后端拒绝原因
  const [handoffOpen, setHandoffOpen] = useState(false);             // 已移交区（决策 9：默认折叠）

  const load = async () => {
    let fallback = false;
    try {
    const list = await listWatch(() => { fallback = true; }); // 服务层内部兜底不抛错，用回调判离线（D5）
    setTargets(list as WatchTargetCard[]);
    setOffline(fallback);
    } catch { setOffline(true); }
  };
  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void load();
    }, 20000); // F7：20s 轻量轮询（正式推送留阶段 2 SSE/异步）
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doParse = async (text: string) => {
    setError('');
    try {
    const r = await parseWatch(text);
    if (r.ok && r.intent) {
      setIntent(r.intent);
      if (r.intent.frequency) setFreq(r.intent.frequency);
    } else {
      setIntent(null);
      setError(r.unsupported?.[0]?.reason ?? '无法解析该委托');
    }
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  };

  const doCreate = async () => {
    try {
      const r = await createWatch(input, freq);
      if (!r.target) throw new Error('后端未确认委托创建');
      setInput('');
      setIntent(null);
      setError('');
      onNotice(`✓ 已开始持续关注${r.target?.name ? `：${r.target.name}` : ''}；后续变化会回到业务脉搏`);
      setFocusId(r.target?.id ?? null); // D4：面板跟随刚创建的委托
      void load();
    } catch (err) {
      onNotice(`✗ ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const toggle = async (t: WatchTargetCard) => {
    const next = t.status === 'paused' ? 'watching' : 'paused';
    try {
      await setWatchStatusStrict(t.id, next); // 4xx（非法迁移）上抛：不静默当成功（P015）
      onNotice(next === 'paused' ? '已暂停该委托（不会继续评估）' : '已恢复持续关注');
    } catch (err) {
      onNotice(`✗ ${err instanceof Error ? err.message : String(err)}`);
    }
    void load();
  };

  /** 从终态「已升级 · 已移交」恢复持续关注（非破坏性：历史 escalate 事件保留）；4xx 显式提示。 */
  const restore = async (t: WatchTargetCard) => {
    try {
      await setWatchStatusStrict(t.id, 'watching');
      onNotice(
        t.engineInsightId
          ? `✓ 已恢复持续关注：${t.name}；该口径当前仍命中引擎判定 ${t.engineInsightId}，下次评估可能再次移交`
          : `✓ 已恢复持续关注：${t.name}（历史升级记录保留）`,
      );
    } catch (err) {
      onNotice(`✗ 恢复失败：${err instanceof Error ? err.message : String(err)}`);
    }
    void load();
  };

  const remove = async (t: WatchTargetCard) => {
    try {
      await deleteWatch(t.id);
      onNotice(`已删除持续关注：${t.name}`);
    } catch (err) { onNotice(`✗ 删除未完成：${err instanceof Error ? err.message : String(err)}`); }
    void load();
  };

  const check = async (t: WatchTargetCard) => {
    try {
      const r = await checkWatchStrict(t.id); // 暂停 / 已移交 → 400 上抛（不伪装成"检查完成"）
      const txt = { escalate: '命中升级（已移交，见「已升级 · 已移交」）', change: '命中变化', miss: '未命中，保持观察' }[r.kind] ?? '检查完成';
      onNotice(`「${t.name}」${txt}`);
    } catch (err) {
      onNotice(`✗ 未能评估：${err instanceof Error ? err.message : String(err)}`);
    }
    void load();
  };

  const condText = intent ? conditionText(intent.condition) : '';

  // —— 目标工作台（watch-goal-workbench）：选中态 + 三工具 ①②③ ——
  const selected = targets.find((t) => t.id === selectedId) ?? null;
  const tool3 = archiveState(selected, !offline);

  const select = (id: string) => {
    setSelectedId((prev) => (prev === id ? null : id)); // 再点一次取消选中，回到默认提示
    setHits(null); setSearchNote(''); setArchived(null); setArchiveErr(''); // 换目标不串台
  };

  /** 工具②：检索串 = `intent.label` + 范围（检索关键词，不是业务判断；design 决策 7）。 */
  const doSearch = async () => {
    if (!selected || offline) return;
    const q = trendQuery(selected.intent);
    if (!q) { setHits(null); setSearchNote('该委托没有解析结果，无法检索'); return; }
    setSearching(true);
    const r = await searchKnowledge(q);
    setSearching(false);
    if (r.failed) { setHits(null); setSearchNote('检索不可用：未能连接后端（不展示推断结果）'); return; }
    setHits(r.hits);
    setSearchNote(r.empty ? '暂无历史先例' : `命中 ${r.hits.length} 条历史记录`);
  };

  /** 工具③ 通用实现：以卡片的引擎判定建档（工作台三工具与「已移交」行共用同一条路径）。 */
  const archiveFor = async (card: WatchTargetCard | null) => {
    const st = archiveState(card, !offline);
    if (!card) return;
    if (!st.enabled || !st.insightId) {
      setArchiveErr(st.reason); // 显式原因（缺引擎判定 / 需连接后端），不静默
      onNotice(`✗ 无法转为行动档案：${st.reason}`);
      return;
    }
    setArchiveErr('');
    try {
      // action-demo-separation：用户明确「转为行动档案」→ 认领已存在的演示档案（幂等）
      const r = await createAction(st.insightId, true);
      if (r.offline || !r.case) {
        // 服务层报告未连接后端（`offline`，P015/D003/D047）：未拿到档案就不得声称「已建档」
        setArchived(null);
        setArchiveErr('未能连接后端（未确认建档），请重试');
        onNotice('✗ 未确认建档：未能连接后端');
        return;
      }
      setArchived({ code: r.case.code, created: r.created });
      onNotice(r.created ? `✓ 已建档并加入行动回路：${r.case.code}` : '✓ 该档案已存在，已加入行动回路');
    } catch (err) {
      setArchived(null);
      const msg = err instanceof Error ? err.message : String(err);
      setArchiveErr(msg);
      onNotice(`✗ 无法转为行动档案：${msg}`);
    }
  };

  const doArchive = () => archiveFor(selected);
  /** 「已移交」行的建档入口（同一实现，卡片来自该行）。 */
  const archiveHandoff = (card: WatchTargetCard) => archiveFor(card);

  // D4：面板跟随「当前委托」——本会话刚理解/创建的委托优先，否则列表最新一条（标注「最近委托」）
  const current = targets.find((t) => t.id === focusId) ?? targets[0] ?? null;
  // watch-escalate-handoff：在手 / 已移交分区与计数（口径与 Pulse 共用 trendView.watchCounts）
  const { inHand, handedOff } = splitTargets(targets);
  const counts = watchCounts(targets);
  const isRecent = !!current && current.id !== focusId;
  const flow = buildDelegateFlow({ intent, target: offline ? null : current, online: !offline });
  const flowLine = flowSummary(flow); // 折叠态一行摘要（决策 10：真实状态 + 当前步骤/提示）

  return (
    <section className="page active">
      <div className="head">
        <div>
          <div className="eyebrow">CONTINUOUS WATCH · DELEGATE</div>
          <div className="h1">把业务目标交给 Dora，后面不用一直盯</div>
          <p className="sub">持续关注是“业务目标委托”。Dora 按你选的频率评估，命中变化会回到业务脉搏并升级。</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {offline && <Tag tone="ai">离线演示</Tag>}
          <span className="status">
            <span className="dot" />
            {counts.inHand} 个业务目标持续关注中
            {counts.handedOff > 0 && <span className="handoff-count"> · {counts.handedOff} 个已升级移交</span>}
          </span>
        </div>
      </div>

      <div className="delegate">
        <div className="card delegate-main">
          <div className="delegate-kicker">
            <span>业务目标委托</span>
            <span className="delegate-state">Dora 将持续检查</span>
          </div>
          <div className="d-title">用一句话托管一个业务目标</div>
          <div className="d-sub">描述你要关注的指标、范围和触发条件，Dora 会解析意图，确认后开始持续检查。</div>
          <label className="delegate-label" htmlFor="watchInput">告诉 Dora 你要关注什么</label>
          <div className="input-line">
            <input id="watchInput" className="delegate-input" value={input} onChange={(e) => setInput(e.target.value)} />
            <button className="btn primary" onClick={() => doParse(input)}>让 Dora 理解</button>
          </div>
          <div className="suggest-head">常用目标</div>
          <div className="suggests">
            {SUGGESTS.map((s) => (
              <button className="suggest" key={s} onClick={() => doParse(`帮我${s}`)}>{s}</button>
            ))}
          </div>
          {error && <div className="delegate-error">✗ {error}</div>}

          {intent && (
            <div className="delegate-result show">
              <b>✓ Dora 已理解你的业务委托{intent.condition_defaulted ? '（触发条件为建议默认，可调整）' : ''}</b>
              <div className="intent-grid">
                <div className="k">业务目标</div><div>{intent.label}</div>
                <div className="k">指标口径</div><div>{intent.dimension || '全量'}</div>
                <div className="k">触发条件</div><div>{condText}</div>
                <div className="k">升级路径</div><div>命中变化 → 回业务脉搏；引擎判定问题 / 机会时升级</div>
                <div className="k">主动反馈</div><div>数据变化 → 业务脉搏 → 变化洞察</div>
              </div>
              <div className="delegate-freq">
                <span className="freq-lbl">检查频率</span>
                {FREQS.map((x) => (
                  <button key={x.value} className={'freq-chip ' + (freq === x.value ? 'active' : '')} onClick={() => setFreq(x.value)}>{x.label}</button>
                ))}
              </div>
              <div className="main-buttons">
                <button className="btn primary" onClick={doCreate}>开始持续关注</button>
                <button className="btn" onClick={() => { setIntent(null); setError(''); document.getElementById('watchInput')?.focus(); }}>调整一下</button>
              </div>
            </div>
          )}
        </div>
        <div className="card delegate-side">
          {/* 决策 10：四步面板降级为可折叠提示条（默认一行 = 真实状态 + 一句摘要），样式与内容不复用静态文案 */}
          <div className="delegate-hint">
            <span className="delegate-hint-title">Dora 接到委托后会做什么</span>
            <Tag tone={FLOW_TONE[flow.state] ?? 'default'}>{flow.stateLabel}</Tag>
            <span className="delegate-hint-sum">{flowLine}</span>
            <button
              className="delegate-hint-toggle"
              aria-expanded={flowOpen}
              onClick={() => setFlowOpen((v) => !v)}
            >
              {flowOpen ? '收起步骤' : '展开步骤'}
            </button>
          </div>
          <div className="delegate-flow" hidden={!flowOpen}>
            <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 4 }}>
              {offline
                ? '当前委托 · 未连接后端'
                : current
                  ? `当前委托 · ${current.name}${isRecent ? '（最近委托）' : ''}`
                  : '当前委托 · 尚未创建'}
            </div>
            {flow.steps.map((st) => (
              <div className="mstep" key={st.n}>
                <div className="mnum">{st.n}</div>
                <div>
                  <b>{st.title}</b> <Tag tone={STEP_TONE[st.state]}>{STEP_TEXT[st.state]}</Tag>
                  <p>{st.desc}</p>
                  <p style={{ fontWeight: 600, color: st.state === 'pending' ? undefined : '#5149dc' }}>{st.note}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card watch-table">
        <div className="whead">
          <div>业务目标</div><div>当前状态</div><div>数据走向</div><div>关注逻辑</div><div>操作</div>
        </div>
        {inHand.length === 0 && (
          <div className="wrow">
            <div className="wname">（暂无在手委托）</div><div /><div /><div />
            <div>
              {counts.handedOff > 0
                ? `在手委托已全部升级移交（下方「已升级 · 已移交」有 ${counts.handedOff} 条），或在上方输入框新建委托`
                : '用上面输入框开始第一个委托'}
            </div>
          </div>
        )}
        {inHand.map((w) => {
          const isSel = w.id === selectedId;
          return (
            <div className={'wrow' + (isSel ? ' selected' : '')} key={w.id}>
              <div>
                {/* 决策 5：只有标题区是选中按钮（不与既有三按钮争抢点击） */}
                <button
                  className={'wtitle' + (isSel ? ' selected' : '')}
                  aria-pressed={isSel}
                  onClick={() => select(w.id)}
                  title={isSel ? '取消选中' : '选中该目标并查看工作台'}
                >
                  <span className="wname">{w.name}</span>
                </button>
                <small>持续关注 · {w.source}</small>
              </div>
              <div className="wvalue"><Tag tone={w.color}>{w.value}</Tag></div>
              <div className="wtrend">
                {w.trend ? (
                  <>
                    <Spark
                      points={w.trend.points}
                      direction={w.trend.direction}
                      label={`数据走向 ${trendSummary(w.trend)}`}
                    />
                    <div className="wtrend-txt">
                      <b>{trendSummary(w.trend)}</b>
                      <small>{w.trend.basis}</small>
                    </div>
                  </>
                ) : (
                  <span className="wtrend-none">暂无序列</span>
                )}
              </div>
              <div className="wlogic">{w.logic}</div>
              <div className="wopts">
                {/* 手检只有在手可评估（后端对 paused/escalated 显式 400）：禁用 + 原因，不静默失败 */}
                <button
                  className="rowbtn"
                  onClick={() => check(w)}
                  disabled={w.status !== 'watching'}
                  title={w.status === 'paused' ? '已暂停：恢复后才评估' : '立即评估一次'}
                >
                  检查
                </button>
                <button className="rowbtn" onClick={() => toggle(w)}>{w.status === 'paused' ? '恢复' : '暂停'}</button>
                <button className="rowbtn" onClick={() => remove(w)}>删除</button>
              </div>
            </div>
          );
        })}
      </div>

      {/* watch-escalate-handoff：已移交终态区（默认折叠，决策 9）——不在手，但可追溯、可恢复 */}
      {handedOff.length > 0 && (
        <div className="card handoff-zone">
          <div className="handoff-head">
            <b>已升级 · 已移交</b>
            <Tag tone="red">{handedOff.length} 条</Tag>
            <span className="handoff-sub">引擎判定升级后已移交问题 / 行动回路，不再计入「持续关注」；记录保留可追溯</span>
            <button
              className="delegate-hint-toggle"
              aria-expanded={handoffOpen}
              onClick={() => setHandoffOpen((v) => !v)}
            >
              {handoffOpen ? '收起明细' : '展开明细'}
            </button>
          </div>
          <div className="handoff-list" hidden={!handoffOpen}>
            {handedOff.map((w) => {
              const st = handoffState(w, !offline);
              const isSel = w.id === selectedId;
              return (
                <div className={'handoff-row' + (isSel ? ' selected' : '')} key={w.id}>
                  <button
                    className={'wtitle' + (isSel ? ' selected' : '')}
                    aria-pressed={isSel}
                    onClick={() => select(w.id)}
                    title={isSel ? '取消选中' : '选中该目标并查看工作台'}
                  >
                    <span className="wname">{w.name}</span>
                  </button>
                  <Tag tone={w.color}>{w.value}</Tag>
                  <span className="handoff-trend">
                    {w.trend ? trendSummary(w.trend) : '暂无序列'}
                  </span>
                  <span className={'handoff-to' + (st.insightId ? '' : ' warn')}>{st.reason}</span>
                  <span className="handoff-ops">
                    {st.insightId && (
                      <button className="rowbtn" onClick={() => onInsight(st.insightId as string)} title="打开该引擎洞察">
                        查看移交洞察 →
                      </button>
                    )}
                    {st.insightId && (
                      <button className="rowbtn" onClick={() => void archiveHandoff(w)} title="以引擎判定建档（复用工作台工具③）">
                        转为行动档案
                      </button>
                    )}
                    <button className="rowbtn" onClick={() => void restore(w)} disabled={offline} title={offline ? '需连接后端' : '恢复持续关注（非破坏性）'}>
                      恢复持续关注
                    </button>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 决策 5：目标工作台 = 表格下方通栏卡片（移动端天然单列） */}
      <div className="card goal-workbench">
        <div className="gwb-head">
          <b>目标工作台</b>
          {offline && <Tag tone="ai">离线镜像</Tag>}
          <span className="gwb-sub">
            {selected ? `${selected.name} · ${selected.source}` : '点选一个目标，查看它的走向与可用工具'}
          </span>
        </div>
        {/* watch-escalate-handoff：已移交委托在工作台保留三工具 + 恢复入口（非破坏性） */}
        {selected && selected.status === 'escalated' && (
          <div className="gwb-handoff">
            <Tag tone="red">已升级 · 已移交</Tag>
            <span>{handoffState(selected, !offline).reason}</span>
            <button className="btn" disabled={offline} onClick={() => void restore(selected)} title={offline ? '需连接后端' : '恢复持续关注（非破坏性）'}>
              恢复持续关注
            </button>
          </div>
        )}
        {!selected ? (
          <div className="gwb-empty">点选一个目标，查看它的走向与可用工具</div>
        ) : (
          <div className="gwb-tools">
            <div className="gwb-tool">
              <h4>① 走向图</h4>
              {selected.trend ? (
                <>
                  <Spark
                    className="gwb-spark"
                    points={selected.trend.points}
                    direction={selected.trend.direction}
                    label={`${selected.name} 数据走向 ${trendSummary(selected.trend)}`}
                  />
                  <div className="gwb-note">
                    <b>{trendSummary(selected.trend)}</b> · {selected.trend.basis}
                    {offline ? ' · 离线镜像' : ''}
                  </div>
                </>
              ) : (
                <div className="gwb-note">该口径暂无序列数据（不画假线；权威序列待后端提供）</div>
              )}
            </div>

            <div className="gwb-tool">
              <h4>② 历史类似情况</h4>
              <button className="btn" disabled={offline || searching} onClick={() => void doSearch()}>
                {searching ? '检索中…' : '查看历史类似情况'}
              </button>
              {offline ? (
                <div className="gwb-note warn">需连接后端（离线镜像不含历史先例）</div>
              ) : (
                <>
                  {searchNote && <div className={'gwb-note' + (hits && hits.length ? '' : ' warn')}>{searchNote}</div>}
                  {hits && hits.length > 0 && (
                    <ul className="gwb-hits">
                      {hits.map((h) => (
                        <li className="gwb-hit" key={`${h.entry_type}-${h.id}`}>
                          <span className="gwb-type">{h.entry_type}</span>
                          <span className="gwb-code">{h.code}</span>
                          <span className="gwb-title">{h.title}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>

            <div className="gwb-tool">
              <h4>③ 转为行动档案</h4>
              <button className="btn primary" disabled={!tool3.enabled} onClick={() => void doArchive()}>
                转为行动档案
              </button>
              <div className={'gwb-note' + (tool3.enabled ? '' : ' warn')}>
                {tool3.enabled ? `可用：${tool3.reason}` : tool3.reason}
              </div>
              <div className="gwb-note">专家由建档引擎按 kind 指派，权威名单待 E1 专家注册表</div>
              {archived && (
                <div className="gwb-done">
                  已建档 · {archived.code}{archived.created ? '' : '（档案已存在）'}
                  {onAction && <button className="gwb-link" onClick={() => onAction()}>去行动回路查看</button>}
                </div>
              )}
              {archiveErr && <div className="gwb-note warn">无法转为行动档案：{archiveErr}</div>}
            </div>
          </div>
        )}
      </div>

      <AskBar
        context="持续关注"
        onSubmit={(q) => onNotice(q ? `Dora：已带入持续关注上下文：“${q}”` : '可以直接输入一个业务问题。')}
        suggestions={['我正在关注哪些目标？', '为什么还没触发？']}
      />
    </section>
  );
}
