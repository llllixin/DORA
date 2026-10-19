import type { WatchParseIntent, WatchTargetCard, WatchTrend, WatchTrendPoint } from '../../types';

/**
 * 「目标工作台」与「走向列」的展示派生（watch-goal-workbench，design 决策 3/4/6/7）。
 *
 * 红线：只表达后端 `trend` 字段与卡片状态，不在前端重算方向 / 判定距离（D003、D015）。
 * - 倒计时（「还差 N 天」）**不在此实现**：`runDays` 与 `condition.days` 相减就是第二条判定链（决策 4）。
 * - 走向图点位只用卡片 `trend.points`（决策 1：不新增请求）。
 */

/** 走向一句话摘要：方向 + 连续天数（按全序列）+ 展示窗口幅度；无 `trend` → 「暂无序列」。 */
export function trendSummary(trend?: WatchTrend | null): string {
  if (!trend) return '暂无序列';
  const dir = { down: '下跌', up: '上涨', flat: '走平' }[trend.direction] ?? '变化';
  const run = trend.direction !== 'flat' && trend.runDays > 0 ? `连续 ${trend.runDays} 天${dir}` : '无明显方向';
  const pct = trend.changePct === null ? '' : ` · ${trend.changePct > 0 ? '+' : ''}${trend.changePct.toFixed(1)}%`;
  return `${run}${pct}`;
}

export const SPARK_W = 96;
export const SPARK_H = 24;
export const SPARK_PAD = 3;

/**
 * sparkline 几何：固定 `viewBox` + 等比缩放（`preserveAspectRatio="xMidYMid meet"`，沿用迭代 43 结论）。
 * 单点退化为居中圆点；全等值退化为中位线（不画假起伏）。
 */
export function sparkLine(points: WatchTrendPoint[]): {
  d: string;
  dots: { x: number; y: number }[];
  flat: boolean;
} {
  if (!points.length) return { d: '', dots: [], flat: true };
  const vs = points.map((p) => p.value);
  const min = Math.min(...vs);
  const max = Math.max(...vs);
  const span = max - min;
  const flat = span === 0;
  const innerW = SPARK_W - SPARK_PAD * 2;
  const innerH = SPARK_H - SPARK_PAD * 2;
  const dots = points.map((p, i) => ({
    x: SPARK_PAD + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW),
    y: flat ? SPARK_PAD + innerH / 2 : SPARK_PAD + (1 - (p.value - min) / span) * innerH,
  }));
  return {
    d: dots.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' '),
    dots,
    flat,
  };
}

/**
 * 已移交去向（watch-escalate-handoff）：卡片 `engineInsightId` = 最近 `escalate` 事件引用的引擎洞察 id。
 * 离线 / 缺字段 → 显式原因（不伪造去向）。
 */
export function handoffState(
  card: WatchTargetCard | null | undefined,
  online: boolean,
): { insightId: string | null; reason: string } {
  const id = card?.engineInsightId ?? null;
  if (!online) return { insightId: id, reason: '需连接后端（离线镜像不含移交去向）' };
  if (!id) return { insightId: null, reason: '缺引擎判定引用（该历史事件未携带 engine_insight）' };
  return { insightId: id, reason: `移交去向：引擎洞察 ${id}` };
}

/**
 * 在手 / 已移交分区 + 计数口径（watch-escalate-handoff 决策 6；Watch 与 Pulse 共用**同一份**口径，
 * 避免两处各写一遍导致分叉）：
 * - 在手（`watching|paused`）= 「我的持续关注」；
 * - 运行中（`watching`）= 监控卡「N 个目标运行中」；
 * - 已移交（`escalated`）= 升级终态，**不计入**任何在手 / 运行中计数。
 */
export function splitTargets(cards: WatchTargetCard[]): {
  inHand: WatchTargetCard[];
  handedOff: WatchTargetCard[];
} {
  return {
    inHand: cards.filter((c) => c.status !== 'escalated'),
    handedOff: cards.filter((c) => c.status === 'escalated'),
  };
}

export function watchCounts(cards: WatchTargetCard[]): {
  inHand: number;
  running: number;
  handedOff: number;
} {
  const { inHand, handedOff } = splitTargets(cards);
  return {
    inHand: inHand.length,
    running: inHand.filter((c) => c.status !== 'paused').length,
    handedOff: handedOff.length,
  };
}

/** 工具② 检索串：`intent.label` + 范围（检索关键词不是业务判断，design 决策 7）。 */
export function trendQuery(intent?: WatchParseIntent | null): string {
  if (!intent?.label) return '';
  return [intent.label, intent.dimension].filter(Boolean).join(' ');
}

/**
 * 工具③「转为行动档案」可用性 + 原因（动作按钮三态红线：真实调用 / 明确禁用+原因 / 诚实提示离线）。
 * 可用判据只有一条：卡片 `engineInsightId` 非空（= 引擎判定升级）。
 */
export function archiveState(
  card: WatchTargetCard | null | undefined,
  online: boolean,
): { enabled: boolean; reason: string; insightId: string | null } {
  if (!card) return { enabled: false, reason: '先选择一个目标', insightId: null };
  if (!online) return { enabled: false, reason: '需连接后端', insightId: null };
  const id = card.engineInsightId || null;
  if (!id) return { enabled: false, reason: '需引擎判定命中升级', insightId: null };
  return { enabled: true, reason: `将以引擎判定 ${id} 建档`, insightId: id };
}
