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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
  return apiGet(`/evidence/${id}`, () => evidence[id] ?? evidence.p1);
}

export function getApiBase() {
  return BASE;
}

// ---------------------------------------------------------------------------
// 数据集接口（C3）：样例服务端化 + 真实文件上传入库
// ---------------------------------------------------------------------------
export async function loadSampleDataset() {
  return apiPost('/datasets/sample', {}, () => ({ ok: true, counts: {} }));
}

export async function uploadDataset(file: File) {
  if (MODE === 'mock') {
    await wait(160);
    return { ok: true, name: file.name, rows: 0, affectedMetrics: [] as string[], updated: '' };
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 10000);
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${BASE}/datasets`, { method: 'POST', body: fd, signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as { ok: boolean; name: string; rows: number; affectedMetrics: string[]; updated: string };
  } catch (err) {
    if (MODE === 'http') throw err;
    console.warn('[doraApi] 数据集上传失败，已回退本地演示：', err);
    await wait(120);
    return { ok: true, name: file.name, rows: 0, affectedMetrics: [] as string[], updated: '' };
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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as PreviewResult;
  } catch (err) {
    if (MODE === 'http') throw err;
    console.warn('[doraApi] 预览失败，走规范直传：', err);
    return null;
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
      throw new Error(body?.detail || `HTTP ${res.status}`);
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

export async function listWatch(): Promise<WatchItem[]> {
  return apiGet('/watch', () => [...watchItems]);
}

/** V4-T2：解析委托语句（后端无 parse 概念时前端回退静态演示解析）。 */
export async function parseWatch(text: string): Promise<WatchParseResult> {
  return apiPost('/watch/parse', { text }, () => demoParse(text));
}

/** V4-T4：创建委托 = parse（400 detail 上抛，不静默 mock）→ create → 即时评估。 */
export async function createWatch(text: string, frequency?: string): Promise<{ ok: boolean; target: WatchTargetCard | null }> {
  if (MODE === 'mock') {
    await wait(160);
    const r = demoParse(text);
    if (!r.ok || !r.intent) throw new Error(r.unsupported?.[0]?.reason ?? '无法解析该委托');
    return { ok: true, target: null };
  }
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
      throw new Error(body?.detail || `HTTP ${res.status}`);
    }
    return { ok: true, target: body?.target ?? null };
  } catch (err) {
    if (MODE === 'http') throw err;
    // 网络失败（后端离线）→ 走演示路径；业务 4xx（不支持指标）继续抛给调用方
    if (err instanceof Error && /HTTP|detail/.test(err.message)) throw err;
    console.warn('[doraApi] POST /watch 失败，走演示创建：', err);
    const r = demoParse(text);
    if (!r.ok) throw new Error(r.unsupported?.[0]?.reason ?? '无法解析该委托');
    return { ok: true, target: null };
  } finally {
    window.clearTimeout(timer);
  }
}

async function apiSend<T>(method: 'PATCH' | 'DELETE' | 'POST', path: string, payload: unknown, fallback: () => T, timeoutMs = 8000): Promise<T> {
  if (MODE === 'mock') {
    await wait(140);
    return fallback();
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: method === 'DELETE' ? undefined : JSON.stringify(payload ?? {}),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } catch (err) {
    if (MODE === 'http') throw err;
    console.warn(`[doraApi] ${method} ${path} 失败，已回退：`, err);
    await wait(100);
    return fallback();
  } finally {
    window.clearTimeout(timer);
  }
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

function demoParse(text: string): WatchParseResult {
  const demo: [string, WatchParseResult] = [
    '华东销售额',
    { ok: true, intent: { metric_key: 'east_orders', dimension: '华东', label: '华东销售额', condition: { type: 'streak_below', days: 3 }, frequency: 'on_update', condition_defaulted: false } },
  ];
  const label = demo[0];
  if (text.includes('华东') && text.includes('销售')) return demo[1];
  return { ok: false, unsupported: [{ token: text.slice(0, 8), reason: `暂不支持该指标（离线演示）；可用：${label} 等` }] };
}

function replaceList<T>(target: T[], items: T[]) {
  target.splice(0, target.length, ...items);
}

export async function syncRemoteData(): Promise<boolean> {
  const ok = await detectApi();
  if (!ok) return false;
  const [problems, opportunities, changes, watch] = await Promise.all([
    getInsights('problem'),
    getInsights('opportunity'),
    getInsights('change'),
    listWatch(),
  ]);
  replaceList(insights.problem, problems);
  replaceList(insights.opportunity, opportunities);
  replaceList(insights.change, changes);
  // Action 档案由 ActionPage 直读 /api/action/cases（不再同步覆写 data.ts 演示数据，F1）
  replaceList(watchItems, watch);
  return true;
}


export interface CaseStepBody {
  note?: string;
  result?: string;
}

/** V5-T4：行动档案 REST（真数据；业务 4xx 显式上抛）。 */
export async function createAction(insightId: string): Promise<{ ok: boolean; created: boolean; case: ActionCaseDetail | null }> {
  if (MODE === 'mock') {
    await wait(160);
    return { ok: true, created: false, case: null };
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 8000);
  try {
    const res = await fetch(`${BASE}/action/cases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ insight_id: insightId }),
      signal: ctrl.signal,
    });
    const body = (await res.json().catch(() => null)) as { detail?: string; ok?: boolean; created?: boolean; case?: ActionCaseDetail } | null;
    if (!res.ok) throw new Error(body?.detail || `HTTP ${res.status}`);
    return { ok: true, created: !!body?.created, case: body?.case ?? null };
  } catch (err) {
    if (MODE === 'http') throw err;
    if (err instanceof Error && /HTTP|detail/.test(err.message)) throw err; // 业务 4xx：不静默 mock
    await wait(120);
    return { ok: true, created: false, case: null }; // 断网演示路径
  } finally {
    window.clearTimeout(timer);
  }
}

export async function listActionCases(): Promise<ActionCaseCard[]> {
  const r = await apiGet('/action/cases', () => ({ ok: true, cases: [] as ActionCaseCard[] }));
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
    if (!res.ok) throw new Error(body?.detail || `HTTP ${res.status}`);
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

