import { evidence, insights, watchItems } from '../data';
import type { ActionCaseCard, ActionCaseDetail, CaseLesson, Evidence, Insight, InsightType, KnowledgeEntry, KnowledgeStats, WatchItem, WatchParseResult, WatchTargetCard } from '../types';

// API 地址：开发环境默认走 Vite 代理 /api → http://localhost:8000（见 vite.config.ts proxy）；
// 生产部署可用环境变量 VITE_API_BASE_URL 覆盖为后端绝对地址。
const BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '');

// 模式：
//   auto = HTTP 优先，失败自动回退 Mock（无后端时页面仍可演示）
//   mock = 强制 Mock（不发出真实请求）
//   http = 强制 HTTP（失败会抛错，便于联调时第一时间暴露接口问题）
const MODE: 'auto' | 'mock' | 'http' =
  import.meta.env.VITE_API_MODE === 'mock'
    ? 'mock'
    : import.meta.env.VITE_API_MODE === 'http'
      ? 'http'
      : 'auto';

const wait = (ms = 240) => new Promise((r) => setTimeout(r, ms));

async function apiGet<T>(path: string, fallback: () => T, timeoutMs = 2600): Promise<T> {
  if (MODE === 'mock') {
    await wait(160);
    return fallback();
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, { signal: ctrl.signal });
    if (!res.ok) { const body = await res.json().catch(() => null); throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status); }
    return (await res.json()) as T;
  } catch (err) {
    if (MODE === 'http') throw err;
    console.warn(`[doraApi] ${path} 请求失败，已回退 Mock：`, err);
    await wait(120);
    return fallback();
  } finally {
    window.clearTimeout(timer);
  }
}

async function apiPost<T>(
  path: string,
  payload: unknown,
  fallback: () => T,
  timeoutMs = 2600,
): Promise<T> {
  if (MODE === 'mock') {
    await wait(160);
    return fallback();
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload ?? {}),
      signal: ctrl.signal,
    });
    if (!res.ok) { const body = await res.json().catch(() => null); throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status); }
    return (await res.json()) as T;
  } catch (err) {
    if (MODE === 'http') throw err;
    console.warn(`[doraApi] POST ${path} 失败，已回退 Mock：`, err);
    await wait(120);
    return fallback();
  } finally {
    window.clearTimeout(timer);
  }
}

export async function getInsights(type: InsightType): Promise<Insight[]> {
  return apiGet(`/insights?type=${type}`, () => insights[type]);
}

export async function getEvidence(id: string): Promise<Evidence> {
  if (MODE === 'mock' || dataConnection.source === 'demo' && !dataConnection.online) {
    const sample = evidence[id];
    if (!sample) throw new Error('此演示洞察没有证据');
    return { ...sample, source: `历史演示 · ${sample.source}` };
  }
  return remoteRead<Evidence>(`/evidence/${id}`);
}

export function getApiBase() {
  return BASE;
}

// ---------------------------------------------------------------------------
// 数据集接口（C3）：样例服务端化 + 真实文件上传入库
// ---------------------------------------------------------------------------
export async function loadSampleDataset() {
  if (MODE === 'mock') return { ok: true, counts: {}, offline: true };
  return apiSendStrict<{ ok: boolean; counts: Record<string, number>; offline?: boolean }>('POST', '/datasets/sample', {}, () => ({ ok: false, counts: {} }));
}

export async function uploadDataset(file: File) {
  if (MODE === 'mock') {
    await wait(160);
    throw new Error('离线演示不能上传真实文件，请先连接后端');
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 10000);
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${BASE}/datasets`, { method: 'POST', body: fd, signal: ctrl.signal });
    if (!res.ok) { const body = await res.json().catch(() => null); throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status); }
    return (await res.json()) as { ok: boolean; name: string; rows: number; affectedMetrics: string[]; updated: string };
  } catch (err) {
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

export type PreviewResult = { ok: boolean; name: string; columns: string[]; sampleRows: Record<string, string>[] };

export async function previewDataset(file: File): Promise<PreviewResult | null> {
  if (MODE === 'mock') return null;
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 10000);
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${BASE}/datasets/preview`, { method: 'POST', body: fd, signal: ctrl.signal });
    if (!res.ok) { const body = await res.json().catch(() => null); throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status); }
    return (await res.json()) as PreviewResult;
  } catch (err) {
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

export type UploadMapping = {
  metric_key: string;
  label_column: string;
  value_column: string;
  dimension_column?: string;
  unit?: string;
};

export type ReasoningRefreshResult = {
  ok: boolean;
  updated: string[];
  fallback: string[];
  provider: 'template' | 'llm';
};

export async function refreshReasoningApi(): Promise<ReasoningRefreshResult> {
  return apiPost(
    '/reason/refresh',
    {},
    () => ({ ok: true, updated: [] as string[], fallback: [] as string[], provider: 'template' as const }),
    30000, // Bug1 收口：默认 2600ms 会误杀真实 LLM 批量（预算 20s + 在途尾差），显式放宽到 30s
  );
}

export async function mappedDataset(file: File, mapping: UploadMapping) {
  if (MODE === 'mock') {
    throw new Error('离线演示模式不支持列映射，请选择"载入样例"或先启动后端');
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 15000);
  try {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('mapping', JSON.stringify(mapping));
    const res = await fetch(`${BASE}/datasets/mapped`, { method: 'POST', body: fd, signal: ctrl.signal });
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    if (!res.ok) {
      throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status);
    }
    return body as { ok: boolean; name: string; rows: number; affectedMetrics: string[]; updated: string };
  } catch (err) {
    if (MODE === 'http') throw err;
    throw err instanceof Error ? err : new Error(String(err));
  } finally {
    window.clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// 页面级数据同步：App 启动时探测后端并把 /insights /actions /watch 结果原位刷
// 新到 data.ts 的持有结构（insights / actionCases / watchItems）。
// 说明：页面组件全部读取 data.ts 的同一批数组/对象引用，因此刷新后页面即显示
//      后端数据，视觉与契约完全一致；后端不可用时不刷新（本地 Mock 兜底）。
// ---------------------------------------------------------------------------
export async function detectApi(): Promise<boolean> {
  if (MODE === 'mock') {
    return false;
  }
  if (MODE === 'http') {
    return true;
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 1200);
  try {
    const res = await fetch(`${BASE}/health`, { signal: ctrl.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

/**
 * V4-T4：委托列表。
 * watch-delegate-flow：`onFallback` 在「未取到后端、落到 data.ts 镜像」时回调——
 * auto 模式的服务层内部兜底不抛错（apiGet），组件无法靠 catch 判离线，故由本函数显式上报。
 */
export async function listWatch(onFallback?: () => void): Promise<WatchItem[]> {
  return apiGet('/watch', () => {
    onFallback?.();
    return [...watchItems];
  });
}

/** V4-T2：解析委托语句（后端无 parse 概念时前端回退静态演示解析）。 */
export async function parseWatch(text: string): Promise<WatchParseResult> {
  return apiPost('/watch/parse', { text }, () => demoParse(text));
}

/** V4-T4：创建委托 = parse（400 detail 上抛，不静默 mock）→ create → 即时评估。 */
export async function createWatch(text: string, frequency?: string): Promise<{ ok: boolean; target: WatchTargetCard | null }> {
  if (MODE === 'mock') throw new Error('离线演示：未创建委托，请连接后端');
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 8000);
  try {
    const res = await fetch(`${BASE}/watch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, frequency: frequency ?? undefined }),
      signal: ctrl.signal,
    });
    const body = (await res.json().catch(() => null)) as { detail?: string; ok?: boolean; target?: WatchTargetCard } | null;
    if (!res.ok) {
      throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status);
    }
    return { ok: true, target: body?.target ?? null };
  } catch (err) {
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

async function apiSend<T>(method: 'PATCH' | 'DELETE' | 'POST', path: string, payload: unknown, fallback: () => T, timeoutMs = 8000): Promise<T> {
  return apiSendStrict(method, path, payload, fallback, timeoutMs);
}

export function setWatchStatus(id: string, status: 'watching' | 'paused') {
  return apiSend('PATCH', `/watch/${id}`, { status }, () => ({ ok: true }));
}

export function deleteWatch(id: string) {
  return apiSend('DELETE', `/watch/${id}`, {}, () => ({ ok: true }));
}

export async function checkWatch(id: string): Promise<{ ok: boolean; kind: string; summary?: string }> {
  return apiSend('POST', `/watch/${id}/check`, {}, () => ({ ok: true, kind: 'miss' }));
}

/**
 * watch-escalate-handoff：`setWatchStatus` / `checkWatch` 需要区分「后端明确拒绝（4xx）」与「后端不可达」。
 *
 * `apiSend` 在 auto 模式下把一切失败都回退成 fallback → 会把 400（非法状态迁移 / 终态不可评估）
 * 伪装成成功（P015）。这两个端点改用严格版：4xx 上抛带 `detail` 的业务错误，仅**网络失败**回退。
 */
export class ApiRejectedError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiRejectedError';
    this.status = status;
  }
}

async function apiSendStrict<T>(method: 'PATCH' | 'DELETE' | 'POST', path: string, payload: unknown, _fallback: () => T, timeoutMs = 8000): Promise<T> {
  if (MODE === 'mock') throw new Error('离线演示：操作未提交到后端');
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: method === 'DELETE' ? undefined : JSON.stringify(payload ?? {}),
      signal: ctrl.signal,
    });
    const body = (await res.json().catch(() => null)) as (T & { detail?: string }) | null;
    if (!res.ok) {
      throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status);
    }
    if (!body || (body as {ok?: boolean}).ok === false) throw new Error('后端未确认操作成功');
    return body as T;
  } catch (err) {
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

/** PATCH /watch/{id}：`watching|paused`（`escalated→watching` = 恢复；非法迁移 → 400 上抛）。 */
export function setWatchStatusStrict(id: string, status: 'watching' | 'paused') {
  return apiSendStrict<{ ok: boolean }>('PATCH', `/watch/${id}`, { status }, () => ({ ok: true }));
}

/** POST /watch/{id}/check：仅在手（`watching`）可评估；暂停 / 已移交 → 400 上抛（不伪装成"检查完成"）。 */
export function checkWatchStrict(id: string) {
  return apiSendStrict<{ ok: boolean; kind: string; summary?: string }>(
    'POST', `/watch/${id}/check`, {}, () => ({ ok: true, kind: 'miss' }),
  );
}

function demoParse(text: string): WatchParseResult {
  const demo: [string, WatchParseResult] = [
    '华东订单量',
    { ok: true, intent: { metric_key: 'east_orders', dimension: '华东', label: '华东订单量', condition: { type: 'streak_below', days: 3 }, frequency: 'on_update', condition_defaulted: false } },
  ];
  const label = demo[0];
  if (text === '帮我关注华东订单量，如果连续三天下降就提醒我') return demo[1];
  if (text === '关注华东订单量' || text === '帮我关注华东订单量') return { ...demo[1], intent: { ...demo[1].intent!, condition_defaulted: true } };
  return { ok: false, unsupported: [{ token: text.slice(0, 8), reason: `暂不支持该指标（离线演示）；可用：${label} 等` }] };
}

function replaceList<T>(target: T[], items: T[]) {
  target.splice(0, target.length, ...items);
}

export const dataConnection = { online: false, source: 'demo' as 'demo' | 'live' | 'stale' };
let syncing: Promise<boolean> | null = null;

async function remoteRead<T>(path: string): Promise<T> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 5000);
  try {
    const res = await fetch(`${BASE}${path}`, { signal: ctrl.signal });
    if (!res.ok) throw new ApiRejectedError(`HTTP ${res.status}`, res.status);
    return await res.json() as T;
  } finally { window.clearTimeout(timer); }
}

export function syncRemoteData(): Promise<boolean> {
  if (syncing) return syncing;
  syncing = (async () => {
    try {
      if (MODE === 'mock') throw new Error('mock');
      // 一次取全部洞察，避免分类型请求跨越不同更新时刻。
      const [all, watch] = await Promise.all([remoteRead<Insight[]>('/insights?type=all'), remoteRead<WatchItem[]>('/watch')]);
      for (const type of ['problem', 'opportunity', 'change'] as const) replaceList(insights[type], all.filter(x => x.type === type));
      replaceList(watchItems, watch);
      dataConnection.online = true;
      dataConnection.source = 'live';
      return true;
    } catch {
      dataConnection.online = false;
      if (dataConnection.source === 'live') dataConnection.source = 'stale';
      return false;
    } finally { syncing = null; }
  })();
  return syncing;
}


export interface CaseStepBody {
  note?: string;
  result?: string;
}

/** 建档结果（D047）：`offline === true` = 未连接后端、**未确认建档**。
 *  调用方不得把它显示为成功，应走本地演示回退并如实标注「离线演示」。 */
export interface CreateActionOutcome {
  ok: boolean;
  created: boolean;
  case: ActionCaseDetail | null;
  /** 离线 = 未连后端、未确认建档（不是「档案已存在」） */
  offline: boolean;
}

/** V5-T4：行动档案 REST（真数据；业务 4xx 显式上抛）。
 *
 * action-demo-separation：`claim=true` 表示用户明确「加入行动回路 / 转为行动档案」——
 * 后端会把已存在的**演示**档案认领为「我的」（幂等）。缺省 false：既有调用逐字不变。
 *
 * 离线 = 显式未确认，不谎报成功：`MODE === 'mock'` 与断网（TypeError / AbortError，所有模式）都返回
 * `{ ok: false, created: false, case: null, offline: true }`，由调用方如实告知用户并落到本地演示档案
 * （见 `App.route` / `WatchPage.archiveFor`）；收到响应的 4xx/5xx **一律抛错**，不被 `offline` 吞掉。
 */
function isConnectionFailure(err: unknown): boolean {
  return err instanceof TypeError || (err instanceof Error && err.name === 'AbortError');
}

export async function createAction(insightId: string, claim = false): Promise<CreateActionOutcome> {
  if (MODE === 'mock') {
    await wait(160);
    return { ok: false, created: false, case: null, offline: true };
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 8000);
  try {
    const res = await fetch(`${BASE}/action/cases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(claim ? { insight_id: insightId, claim: true } : { insight_id: insightId }),
      signal: ctrl.signal,
    });
    const body = (await res.json().catch(() => null)) as { detail?: string; ok?: boolean; created?: boolean; case?: ActionCaseDetail } | null;
    if (!res.ok) throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status);
    return { ok: true, created: !!body?.created, case: body?.case ?? null, offline: false };
  } catch (err) {
    if (isConnectionFailure(err)) return { ok: false, created: false, case: null, offline: true };
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

/**
 * 行动档案列表（action-demo-separation）：`origin` = all | mine | demo（缺省 all，保持既有行为）。
 * `onFallback` 用于页面判离线（D5 同款：服务层内部兜底不抛错，用回调上报）——
 * 「我的为空」与「后端不可用」必须分得开，否则空列表会被误当离线演示。
 */
export async function listActionCases(
  origin: 'all' | 'mine' | 'demo' = 'all',
  onFallback?: () => void,
): Promise<ActionCaseCard[]> {
  const suffix = origin === 'all' ? '' : `?origin=${origin}`;
  const r = await apiGet(`/action/cases${suffix}`, () => {
    onFallback?.();
    return { ok: true, cases: [] as ActionCaseCard[] };
  });
  return (r as { cases: ActionCaseCard[] }).cases;
}

export async function fetchActionCase(id: string): Promise<ActionCaseDetail | null> {
  const r = await apiGet(`/action/cases/${id}`, () => ({ ok: true, case: null as ActionCaseDetail | null }));
  return (r as { case: ActionCaseDetail | null }).case;
}

export function startStep(id: string, seq: number) {
  return apiSend('POST', `/action/cases/${id}/steps/${seq}/start`, {}, () => ({ ok: true }));
}

export function doneStep(id: string, seq: number, body: CaseStepBody = {}) {
  return apiSend('POST', `/action/cases/${id}/steps/${seq}/done`, body, () => ({ ok: true }));
}

export function blockStep(id: string, seq: number, note = '') {
  return apiSend('POST', `/action/cases/${id}/steps/${seq}/blocked`, { note }, () => ({ ok: true }));
}

/** action-loop-timeline：整体设置某步负责专家（幂等：请求体即完整名单，空数组=清除）。
 *  离线/演示模式**不静默成功**——抛错让界面提示原因（D5：不做乐观更新、不伪造状态）。 */
export async function setStepExperts(
  caseId: string, seq: number, experts: string[],
): Promise<{ ok: boolean; case: ActionCaseDetail | null }> {
  if (MODE === 'mock') throw new Error('离线演示：专家分配需后端在线');
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 8000);
  try {
    const res = await fetch(`${BASE}/action/cases/${caseId}/steps/${seq}/experts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ experts }),
      signal: ctrl.signal,
    });
    const body = (await res.json().catch(() => null)) as { detail?: string; ok?: boolean; case?: ActionCaseDetail } | null;
    if (!res.ok) throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status);
    return { ok: true, case: body?.case ?? null };
  } catch (err) {
    if (MODE === 'http') throw err;
    if (err instanceof Error && /HTTP|detail|专家|步骤|冻结/.test(err.message)) throw err; // 业务 4xx：不静默 mock
    throw new Error('离线：专家分配需后端在线');
  } finally {
    window.clearTimeout(timer);
  }
}

export function verifyAction(id: string, outcome: 'resolved' | 'continue', note = '') {
  return apiSend('POST', `/action/cases/${id}/verify`, { outcome, note }, () => ({ ok: true }));
}

/** 迭代36：resolved 档案 → 经验沉淀（4xx 显式上抛）。 */
export async function archiveAsLesson(caseId: string, note: string): Promise<{ ok: boolean; created: boolean; lesson: CaseLesson | null }> {
  if (MODE === 'mock') return { ok: true, created: false, lesson: null };
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 8000);
  try {
    const res = await fetch(`${BASE}/action/cases/${caseId}/archive-as-lesson`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note }),
      signal: ctrl.signal,
    });
    const body = (await res.json().catch(() => null)) as { detail?: string; ok?: boolean; created?: boolean; lesson?: CaseLesson } | null;
    if (!res.ok) throw new ApiRejectedError(body?.detail || `HTTP ${res.status}`, res.status);
    return { ok: true, created: !!body?.created, lesson: body?.lesson ?? null };
  } catch (err) {
    if (MODE === 'http') throw err;
    throw err instanceof Error ? err : new Error(String(err));
  } finally {
    window.clearTimeout(timer);
  }
}

export async function listLessons(): Promise<CaseLesson[]> {
  const r = await apiGet('/action/lessons', () => ({ ok: true, lessons: [] as CaseLesson[] }));
  return (r as { lessons: CaseLesson[] }).lessons;
}


export async function listKnowledge(type = ''): Promise<{ entries: KnowledgeEntry[]; stats: KnowledgeStats }> {
  const q = type ? `?type=${type}` : '';
  const r = await apiGet(`/knowledge${q}`, () => ({
    ok: true,
    entries: [] as KnowledgeEntry[],
    stats: { problem: 0, opportunity: 0, change: 0, lesson: 0 } as KnowledgeStats,
  }));
  return { entries: (r as { entries: KnowledgeEntry[] }).entries, stats: (r as { stats: KnowledgeStats }).stats };
}

/** watch-goal-workbench：知识检索条目（`POST /api/knowledge/search` 的 `hits[i]`，含词法得分）。 */
export interface KnowledgeHit extends KnowledgeEntry {
  score: number;
}

export interface KnowledgeSearchResult {
  hits: KnowledgeHit[];
  references: { entry_type: string; source_id: string; code: string; title: string }[];
  empty: boolean;
  /** 服务层回退（离线 / 请求失败）时为 true —— 调用方据此不把失败说成「暂无先例」（P015） */
  failed: boolean;
}

/**
 * watch-goal-workbench 工具②「查看历史类似情况」：既有知识检索能力（词法 top-k + 可回溯 references）。
 * 空命中由后端显式 `empty=true`；请求失败走 `onFallback` 上报（auto 模式从不抛错，P015），
 * 不回退成本地伪造条目。
 */
export async function searchKnowledge(
  query: string,
  opts: { types?: string[]; topK?: number; onFallback?: () => void } = {},
): Promise<KnowledgeSearchResult> {
  let failed = false;
  const r = await apiPost(
    '/knowledge/search',
    { query, types: opts.types ?? [], top_k: opts.topK ?? 5 },
    () => {
      failed = true; // 服务层回退（离线 / 请求失败）——由调用方决定措辞，不在此处伪装成功
      opts.onFallback?.();
      return { ok: true, hits: [] as KnowledgeHit[], references: [], empty: true };
    },
  );
  const body = r as {
    hits?: KnowledgeHit[];
    references?: { entry_type: string; source_id: string; code: string; title: string }[];
    empty?: boolean;
  };
  const hits = body.hits ?? [];
  return {
    hits,
    references: body.references ?? [],
    empty: body.empty ?? hits.length === 0,
    failed,
  };
}

export interface DoraChatAnswer {
  text: string;
  references: { entry_type: string; source_id: string; code: string; title: string }[];
  intent: string;
  runId: string;
}

/** Dora Chat（SSE，迭代 42 后端能力）：逐事件解析 `thought_step/tool_call/evidence/answer/done` 后返回完整答案。
 *  离线或失败抛错，由调用方降级为引擎语义（模板）。 */
export async function askDora(
  question: string,
  opts: { insightId?: string; page?: string } = {},
): Promise<DoraChatAnswer> {
  if (MODE === 'mock') throw new Error('mock mode: chat disabled');
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 20000);
  try {
    const res = await fetch(`${BASE}/dora/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, insight_id: opts.insightId, page: opts.page ?? 'insight' }),
      signal: ctrl.signal,
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let answer = '';
    let references: DoraChatAnswer['references'] = [];
    let intent = '';
    let runId = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const chunks = buf.split('\n\n');
      buf = chunks.pop() ?? '';
      for (const chunk of chunks) {
        let ev = '';
        let data = '';
        for (const line of chunk.split('\n')) {
          if (line.startsWith('event: ')) ev = line.slice(7).trim();
          else if (line.startsWith('data: ')) data = line.slice(6);
        }
        if (!ev) continue;
        const payload = data ? JSON.parse(data) : {};
        if (ev === 'answer') { answer = payload.text ?? ''; references = payload.references ?? []; }
        else if (ev === 'thought_step' && payload.intent) intent = payload.intent;
        else if (ev === 'done') runId = payload.run_id ?? '';
      }
    }
    return { text: answer, references, intent, runId };
  } finally {
    window.clearTimeout(timer);
  }
}
