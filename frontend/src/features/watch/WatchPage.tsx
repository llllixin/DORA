import { useEffect, useState } from 'react';
import { watchItems } from '../../data';
import { AskBar } from '../../components/dora/AskBar';
import { Tag } from '../../components/ui/Tag';
import type { WatchParseIntent, WatchTargetCard } from '../../types';
import { checkWatch, createWatch, deleteWatch, listWatch, parseWatch, setWatchStatus } from '../../services/doraApi';

const FREQS: { value: string; label: string }[] = [
  { value: 'on_update', label: '数据更新时' },
  { value: 'daily 09:00', label: '每日 09:00' },
  { value: 'weekly', label: '每周' },
];
const SUGGESTS = ['关注利润率', '关注库存周转', '关注华东销售', '关注新品增长', '关注退货率', '关注大额订单'];

type Props = { onTrace: (id: string) => void; onNotice: (m: string) => void; onInsight: (id: string) => void };

export function WatchPage({ onNotice }: Props) {
  const [input, setInput] = useState('帮我关注华东销售额，如果连续三天下降就提醒我');
  const [freq, setFreq] = useState('on_update');
  const [intent, setIntent] = useState<WatchParseIntent | null>(null);
  const [error, setError] = useState('');
  const [targets, setTargets] = useState<WatchTargetCard[]>([]);

  const load = async () => {
    try {
      setTargets(await listWatch());
    } catch {
      setTargets([...watchItems]);
    }
  };
  useEffect(() => {
    void load();
  }, []);

  const doParse = async (text: string) => {
    setError('');
    const r = await parseWatch(text);
    if (r.ok && r.intent) {
      setIntent(r.intent);
      if (r.intent.frequency) setFreq(r.intent.frequency);
    } else {
      setIntent(null);
      setError(r.unsupported?.[0]?.reason ?? '无法解析该委托');
    }
  };

  const doCreate = async () => {
    try {
      const r = await createWatch(input, freq);
      setInput('');
      setIntent(null);
      setError('');
      onNotice(`✓ 已开始持续关注${r.target?.name ? `：${r.target.name}` : ''}；后续变化会回到业务脉搏`);
      void load();
    } catch (err) {
      onNotice(`✗ ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const toggle = async (t: WatchTargetCard) => {
    const next = t.status === 'paused' ? 'watching' : 'paused';
    await setWatchStatus(t.id, next);
    onNotice(next === 'paused' ? '已暂停该委托（不会继续评估）' : '已恢复持续关注');
    void load();
  };

  const remove = async (t: WatchTargetCard) => {
    await deleteWatch(t.id);
    onNotice(`已删除持续关注：${t.name}`);
    void load();
  };

  const check = async (t: WatchTargetCard) => {
    const r = await checkWatch(t.id);
    const txt = { escalate: '命中升级（已回脉搏）', change: '命中变化', miss: '未命中，保持观察' }[r.kind] ?? '检查完成';
    onNotice(`「${t.name}」${txt}`);
    void load();
  };

  const condText = intent
    ? intent.condition.type === 'streak_below'
      ? `连续 ${intent.condition.days} 天下跌`
      : intent.condition.type === 'streak_above'
        ? `连续 ${intent.condition.days} 天上涨`
        : intent.condition.type === 'below'
          ? `跌破 ${intent.condition.ref}`
          : `超过 ${intent.condition.ref}`
    : '';

  return (
    <section className="page active">
      <div className="head">
        <div>
          <div className="eyebrow">CONTINUOUS WATCH · DELEGATE</div>
          <div className="h1">把业务目标交给 Dora，后面不用一直盯</div>
          <p className="sub">持续关注是“业务目标委托”。Dora 按你选的频率评估，命中变化会回到业务脉搏并升级。</p>
        </div>
        <span className="status">
          <span className="dot" />
          {targets.length} 个业务目标持续关注中
        </span>
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
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <b style={{ fontSize: 15 }}>Dora 接到委托后会做什么</b>
            <Tag tone="ai">自动完成</Tag>
          </div>
          {[['1', '理解目标', '识别指标、范围、条件和频率'], ['2', '匹配数据口径', '自动关联引擎支持的指标序列'], ['3', '持续检查', '数据更新 / 每日 / 每周按频率评估'], ['4', '回到业务脉络', '命中变化 → 升级只引用引擎判定']].map(([n, t, p]) => (
            <div className="mstep" key={n}>
              <div className="mnum">{n}</div>
              <div><b>{t}</b><p>{p}</p></div>
            </div>
          ))}
        </div>
      </div>

      <div className="card watch-table">
        <div className="whead">
          <div>业务目标</div><div>当前状态</div><div>关注逻辑</div><div>操作</div>
        </div>
        {targets.length === 0 && <div className="wrow"><div className="wname">（暂无委托）</div><div /><div /><div>用上面输入框开始第一个委托</div></div>}
        {targets.map((w) => (
          <div className="wrow" key={w.id}>
            <div>
              <div className="wname">{w.name}</div>
              <small>持续关注 · {w.source}</small>
            </div>
            <div className="wvalue"><Tag tone={w.color}>{w.value}</Tag></div>
            <div className="wlogic">{w.logic}</div>
            <div className="wopts">
              <button className="rowbtn" onClick={() => check(w)}>检查</button>
              <button className="rowbtn" onClick={() => toggle(w)}>{w.status === 'paused' ? '恢复' : '暂停'}</button>
              <button className="rowbtn" onClick={() => remove(w)}>删除</button>
            </div>
          </div>
        ))}
      </div>

      <AskBar
        context="持续关注"
        onSubmit={(q) => onNotice(q ? `Dora：已带入持续关注上下文：“${q}”` : '可以直接输入一个业务问题。')}
        suggestions={['我正在关注哪些目标？', '为什么还没触发？']}
      />
    </section>
  );
}
