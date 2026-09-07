import { actionCases, evidence, insights, watchItems } from '../data';
import type { ActionCase, Evidence, Insight, InsightType, WatchItem } from '../types';

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

export async function getActionCase(id: string): Promise<ActionCase> {
  return apiGet(`/actions/${id}`, () => actionCases[id] ?? actionCases.p1);
}

export async function createFollowup(payload: { insightId: string }) {
  return apiPost(
    '/watch',
    payload,
    () => ({ ok: true, id: `followup-${payload.insightId}`, status: 'watching' as const }),
  );
}

export async function executeAction(payload: { actionId: string }) {
  return apiPost(
    `/actions/${payload.actionId}/execute`,
    {},
    () => ({
      ok: true,
      actionId: payload.actionId,
      status: 'running' as const,
      message: '执行结果已回写问题档案，Dora 将继续验证。',
    }),
  );
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

export async function listActions(): Promise<ActionCase[]> {
  return apiGet('/actions', () => Object.values(actionCases));
}

export async function listWatch(): Promise<WatchItem[]> {
  return apiGet('/watch', () => [...watchItems]);
}

function replaceList<T>(target: T[], items: T[]) {
  target.splice(0, target.length, ...items);
}

export async function syncRemoteData(): Promise<boolean> {
  const ok = await detectApi();
  if (!ok) return false;
  const [problems, opportunities, changes, actions, watch] = await Promise.all([
    getInsights('problem'),
    getInsights('opportunity'),
    getInsights('change'),
    listActions(),
    listWatch(),
  ]);
  replaceList(insights.problem, problems);
  replaceList(insights.opportunity, opportunities);
  replaceList(insights.change, changes);
  const actionMap: Record<string, ActionCase> = {};
  actions.forEach((a) => {
    actionMap[a.id] = a;
  });
  Object.keys(actionCases).forEach((k) => delete actionCases[k]);
  Object.assign(actionCases, actionMap);
  replaceList(watchItems, watch);
  return true;
}

