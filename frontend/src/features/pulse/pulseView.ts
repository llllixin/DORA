import type { Insight, WatchItem, WatchTargetCard } from '../../types';

/**
 * Pulse 展示派生（W1 frontend-loop-pulse）。
 *
 * 字段盘点表（design D6，勿删）：
 * | Pulse 面板 | 所需字段 | 来源（后端在线） | 离线兜底 | 降级文案 |
 * |---|---|---|---|---|
 * | Summary 计数 | problems/opportunities/changes 长度、持续关注数 | `/api/insights`（insights.*）+ `/api/watch`（watchItems）同步结构 | data.ts 镜像 | 按镜像计数 + 「离线演示」标识 |
 * | 主区优先级卡 | title/desc/confidence/metric/delta/source + semantics{causeA,causeB} | `/api/insights?type=problem`（含 semantics） | data.ts 镜像 semantics | 无 semantics → 「模板未覆盖」缺省，只展示 metric/delta/source |
 * | 信号板 | type/title/desc/metric/delta | `/api/insights?type=opportunity|change` | 镜像 | 空 → 「暂无该类信号」 |
 * | 监控卡 | name/value/color/logic/status | `/api/watch`（listWatch → watchItems） | 镜像 watch 行 | 空 → 「暂无持续关注委托」 |
 * | 本轮工作 | 判定计数 + dataLabel | insights.* 计数 + props dataLabel | 镜像 | 沿用 dataLabel + 计数 |
 *
 * 说明：不消费 `/api/pulse`（engine 内 watching=changes 计数 ≠ 真实委托数，见 design D1/D6）；
 * PulsePage 与 pulseView 全用 `/api/insights` + `/api/watch` 的 D008 同步结构（insights.* / watchItems）。
 */

export interface PulseFact {
  k: string;
  v: string;
}

export interface HeroView {
  copy: string;
  facts: PulseFact[];
  note: string;
  reason: string;
}

export interface SignalRow {
  kind: 'op' | 'ch';
  title: string;
  desc: string;
  value: string;
}

export interface MonitorRow {
  name: string;
  sub: string;
  status: string;
}

const fmtFact = (s: { name: string; value: string }) => (s.value ? `${s.name} · ${s.value}` : s.name);

/** 主区优先级卡：copy/facts/reason 只拼引擎字段（desc/semantics），无 semantics 显式「模板未覆盖」。 */
export function heroFor(insight?: Insight | null): HeroView {
  if (!insight) {
    return { copy: '暂无引擎判定的问题', facts: [], note: '', reason: '' };
  }
  const sem = insight.semantics;
  const facts: PulseFact[] = sem
    ? [
        { k: '主要影响因素', v: fmtFact(sem.causeA) },
        { k: '进一步定位', v: fmtFact(sem.causeB) },
      ]
    : [];
  return {
    copy: insight.desc || '',
    facts,
    note: sem ? '' : '模板未覆盖该洞察的可视化归因；以下为引擎原文字段。',
    reason: sem ? `规则已定位：${fmtFact(sem.causeA)} → ${fmtFact(sem.causeB)}。` : insight.desc || '',
  };
}

/** 信号板行：全部取自引擎 opportunity/change 洞察字段，不编造。 */
export function signalsFrom(opportunities: Insight[], changes: Insight[]): SignalRow[] {
  const toRow = (i: Insight, kind: 'op' | 'ch'): SignalRow => ({
    kind,
    title: i.title,
    desc: i.desc,
    value: [i.metric, i.delta].filter(Boolean).join(' · '),
  });
  return [...opportunities.map((i) => toRow(i, 'op')), ...changes.map((i) => toRow(i, 'ch'))];
}

/** 监控卡行：来自真实 watch 卡片 + 问题标题包含匹配（已触发问题）。 */
export function monitorsFrom(watch: WatchItem[], problems: Insight[]): MonitorRow[] {
  const isTriggered = (w: WatchItem) =>
    problems.some((p) => p.id === w.id || p.title.includes(w.name));
  const statusOf = (w: WatchItem): string => {
    const status = (w as WatchTargetCard).status;
    if (status === 'paused') return '已暂停';
    if (isTriggered(w)) return '已触发问题';
    if (w.color === 'green') return '机会候选';
    if ((w as WatchTargetCard).lastEventAt) return '有变化';
    return '观察中';
  };
  return watch.map((w) => ({
    name: w.name,
    sub: w.source || w.logic || '',
    status: statusOf(w),
  }));
}

/** 跟进别名表（首版唯一受控的前后端重复，见 design D5）：与 watch parser 词典同义。 */
const FOLLOW_ALIASES: Record<string, string> = { margin: '利润率' };

/** 从洞察解析可委托的 metric key（引擎返回 evidence.kind / 备选 metric_key 字段）。 */
export function metricLabelOf(insight?: Insight | null): string | null {
  if (!insight) return null;
  const kind =
    (insight as { evidence?: { kind?: string } }).evidence?.kind ??
    (insight as { metric_key?: string }).metric_key ??
    null;
  return kind ? (FOLLOW_ALIASES[kind] ?? null) : null;
}

/**
 * 可委托跟进文本：仅当 metric 命中别名表才返回可解析委托句（显式 streak_below days=3，
 * curl 实测 condition_defaulted=false），否则 null（按钮禁用并提示原因）。
 */
export function followTargetFor(insight?: Insight | null): string | null {
  const label = metricLabelOf(insight);
  return label ? `关注${label}，连续 3 天下跌提醒我` : null;
}

/** 已关注态：watchItems 中是否存在同 label（如「利润率」）的委托。 */
export function followedTargetOf(insight: Insight | null | undefined, targets: WatchItem[]): WatchTargetCard | null {
  const label = metricLabelOf(insight);
  if (!label) return null;
  return ((targets as WatchTargetCard[]).find((w) => w.name === label) as WatchTargetCard | undefined) ?? null;
}
