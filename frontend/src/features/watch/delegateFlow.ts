import type { WatchCondition, WatchParseIntent, WatchTargetCard } from '../../types';

/**
 * 「Dora 接到委托后会做什么」面板的展示派生（watch-delegate-flow，design D2/D3/D5）。
 *
 * 步骤 → 字段 → 来源（design D3 表，勿删）：
 * | 步骤 | 所需字段 | 在线来源 | 离线兜底 |
 * |---|---|---|---|
 * | 1 理解目标 | `intent.label/dimension/condition/frequency` | 会话 `parseWatch` 结果，或卡片 `intent` | 会话 parse 结果（demo 词典） |
 * | 2 匹配数据口径 | `intent.metric_key` | 同上（解析器词典 = 引擎受支持 metric key） | 同上 |
 * | 3 持续检查 | `status`/`frequency`/`lastCheckedAt` | 卡片（`/api/watch`） | 显式「需连接后端」（不伪造） |
 * | 4 回到业务脉络 | `lastEvent.kind/summary` | 卡片（`/api/watch`） | 显式「需连接后端」（不伪造） |
 *
 * 红线：只消费真实字段，不嗅探 `logic`/`value` 字符串（D003/D004）；离线只推进本地已知步骤（D5）。
 */

export type DelegateStepState = 'pending' | 'done' | 'active' | 'paused';

export interface DelegateStep {
  n: string;
  title: string;
  desc: string;
  state: DelegateStepState;
  note: string;
}

export interface DelegateFlowInput {
  /** 本会话解析结果（`parseWatch` 返回），优先于卡片 `intent` */
  intent?: WatchParseIntent | null;
  /** 面板跟随的当前委托卡片（可为空 = 尚未创建） */
  target?: WatchTargetCard | null;
  /** 后端是否可用（`load()` 是否回退本地演示数据） */
  online: boolean;
}

export interface DelegateFlow {
  state: string;
  stateLabel: string;
  steps: DelegateStep[];
  hint: string;
}

/** 条件文案（与委托回显卡共用，避免两处措辞分叉）。 */
export function conditionText(cond?: WatchCondition | null): string {
  if (!cond) return '关注变化';
  if (cond.type === 'streak_below') return `连续 ${cond.days} 天下跌`;
  if (cond.type === 'streak_above') return `连续 ${cond.days} 天上涨`;
  if (cond.type === 'below') return `跌破 ${cond.ref}`;
  return `超过 ${cond.ref}`;
}

/** 频率文案（与检查频率选择器共用同一份文案）。 */
export function frequencyText(freq?: string | null): string {
  return { on_update: '数据更新时', 'daily 09:00': '每日 09:00', weekly: '每周' }[freq ?? ''] ?? (freq || '数据更新时');
}

/** ISO 时刻 → `MM-DD HH:mm`（与 `_watch_card` 的 logic 片段同格式；非法值原样返回）。 */
export function shortAt(at?: string | null): string {
  if (!at || at.length < 16) return at || '';
  return at.slice(5, 16).replace('T', ' ');
}

/** 引擎口径说明：`metric_key` 落在解析器受支持词典内（不支持的指标在 parse/创建阶段已被 4xx 拒绝）。 */
export function metricNote(intent: WatchParseIntent): string {
  return `引擎口径 · ${intent.metric_key}（${intent.dimension || '全量'}）`;
}

export function buildDelegateFlow({ intent, target, online }: DelegateFlowInput): DelegateFlow {
  const session = intent && intent.metric_key ? intent : null;
  const card = target?.intent && target.intent.metric_key ? target.intent : null;
  const parsed = session ?? card; // 会话 parse 优先，其次卡片回显的 intent
  const paused = target?.status === 'paused';
  const lastEvent = target?.lastEvent ?? null;

  const steps: DelegateStep[] = [
    {
      n: '1',
      title: '理解目标',
      desc: '识别指标、范围、条件和频率',
      state: parsed ? 'done' : 'pending',
      note: parsed
        ? `${parsed.label} · ${parsed.dimension || '全量'} · ${conditionText(parsed.condition)}`
        : '输入一句业务目标，例如「关注利润率，连续三天下跌提醒我」',
    },
    {
      n: '2',
      title: '匹配数据口径',
      desc: '自动关联引擎支持的指标序列',
      state: parsed ? 'done' : 'pending',
      note: parsed ? metricNote(parsed) : '解析成功后关联引擎口径',
    },
    {
      n: '3',
      title: '持续检查',
      desc: '数据更新 / 每日 / 每周按频率评估',
      state: 'pending',
      note: '确认「开始持续关注」后生效',
    },
    {
      n: '4',
      title: '回到业务脉络',
      desc: '命中变化 → 升级只引用引擎判定',
      state: 'pending',
      note: '命中变化 / 引擎判定升级后回到业务脉搏',
    },
  ];

  // 步骤 3：真实委托状态（离线只到步骤 1/2，D5）
  if (online && target) {
    if (paused) {
      steps[2] = { ...steps[2], state: 'paused', note: '已暂停 · 不评估' };
    } else {
      const freq = frequencyText(target.frequency);
      const at = shortAt(target.lastCheckedAt);
      steps[2] = { ...steps[2], state: 'active', note: at ? `${freq} · 最近检查 ${at}` : freq };
    }
  } else if (!online) {
    steps[2] = { ...steps[2], note: '需连接后端' };
  }

  // 步骤 4：最近命中事件（change/escalate 同源；无命中 = 观察中）
  if (online && target) {
    if (lastEvent) {
      const escalated = lastEvent.kind === 'escalate';
      steps[3] = {
        ...steps[3],
        state: 'done',
        note: `${escalated ? '已升级' : '已命中变化'} · ${lastEvent.summary}${paused ? '（已暂停）' : ''}`,
      };
    } else if (paused) {
      steps[3] = { ...steps[3], state: 'pending', note: '已暂停 · 恢复后继续评估' };
    } else {
      steps[3] = { ...steps[3], state: 'active', note: '观察中，尚未命中' };
    }
  } else if (!online) {
    steps[3] = { ...steps[3], note: '需连接后端' };
  }

  // 头部状态 pill 与步骤态同源推导（避免 pill 说 A、步骤说 B）
  let state: string;
  let stateLabel: string;
  if (!online) {
    state = 'offline';
    stateLabel = '离线演示';
  } else if (target) {
    if (paused) {
      state = 'paused';
      stateLabel = '已暂停';
    } else if (lastEvent?.kind === 'escalate') {
      state = 'escalated';
      stateLabel = '已升级';
    } else if (lastEvent) {
      state = 'hit';
      stateLabel = '已命中变化';
    } else {
      state = 'watching';
      stateLabel = '持续关注中';
    }
  } else if (parsed) {
    state = 'parsed';
    stateLabel = '已理解委托 · 待确认';
  } else {
    state = 'idle';
    stateLabel = '待命';
  }

  let hint = '';
  if (!online) {
    hint = '离线演示：持续检查与命中状态需连接后端，以下只展示本地已解析的步骤。';
  } else if (!target && parsed) {
    hint = '点「开始持续关注」后，Dora 才会真实落库并按频率评估。';
  }

  return { state, stateLabel, steps, hint };
}
