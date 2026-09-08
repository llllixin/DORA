export type Page = 'pulse' | 'insight' | 'action' | 'watch' | 'knowledge';
export type InsightType = 'problem' | 'opportunity' | 'change';
export type StatusKind = 'none' | 'action' | 'watch';

export interface Insight {
  id: string;
  type: InsightType;
  tag: string;
  title: string;
  desc: string;
  confidence: number;
  metric: string;
  delta: string;
  source: string;
  question: string;
  semantics?: InsightSemantics;
  reasonSource?: 'template' | 'llm';
  generatedAt?: string;
}

export interface InsightSemantics {
  causeA: { name: string; value: string };
  causeB: { name: string; value: string };
  next: string[];
}

export interface Evidence {
  title: string;
  source: string;
  updated: string;
  sheet: string;
  scope: string;
  metric: string;
  hits: string[];
  rows: string;
  path: string;
  fact: string;
  judgment: string;
  suggestion: string;
  rawRows: string[][];
}

export interface ActionCase {
  id: string;
  kind: 'problem' | 'opportunity';
  tag: string;
  tagCls: 'red' | 'green';
  caseTitle: string;
  code: string;
  source: string;
  steps: { title: string; desc: string; evidence: string }[];
  current: { title: string; desc: string; why: string; evidence: string };
  experts: string[];
  data: string[];
  expertDesc: string;
  archive: string;
}

export interface WatchItem {
  id: string;
  name: string;
  value: string;
  color: 'red' | 'blue' | 'green';
  logic: string;
  source: string;
}

/** V4-T4：真实委托卡片（后端 /api/watch 返回，WatchItem 超集） */
export interface WatchTargetCard extends WatchItem {
  status?: 'watching' | 'paused';
  frequency?: string;
  lastEventAt?: string;
}

export interface WatchCondition {
  type: string;
  days?: number;
  ref?: number | null;
  ref_is_pct?: boolean;
}

export interface WatchParseIntent {
  metric_key: string;
  dimension: string;
  condition: WatchCondition;
  frequency: string | null;
  label: string;
  condition_defaulted: boolean;
}

export interface WatchParseResult {
  ok: boolean;
  intent?: WatchParseIntent;
  unsupported?: { token: string; reason: string }[];
}

export type ChartPointSeries = { name: string; values: number[]; color: string };

export interface DataSource {
  name: string;
  kind: 'sample' | 'upload';
  at: string;
  rows: number;
  fields: number;
}

export type ChartData =
  | { kind: 'line'; unit: string; labels: string[]; series: ChartPointSeries[]; threshold?: { value: number; label: string; color: string } }
  | { kind: 'bar'; unit: string; labels: string[]; series: ChartPointSeries[] }
  | { kind: 'barline'; labels: string[]; bars: ChartPointSeries; line: ChartPointSeries }
  | { kind: 'bubble'; labels: string[]; bubbles: { name: string; size: number; count: string; value: string; color: string }[] }
  | { kind: 'step'; labels: string[]; steps: { name: string; note: string; done: boolean }[] };

/** V5：行动档案真实数据（/api/action/cases） */
export interface CaseStep {
  id: number;
  case_id: string;
  seq: number;
  title: string;
  desc: string;
  evidence: string;
  why: string;
  status: 'pending' | 'in_progress' | 'done' | 'blocked';
  note: string;
  result: string;
  finished_at: string;
}

export interface ActionCaseDetail {
  id: string;
  kind: 'problem' | 'opportunity';
  tag: string;
  tag_cls: string;
  case_title: string;
  code: string;
  source: string;
  status: 'open' | 'running' | 'waiting_verify' | 'resolved';
  orchestration: { experts: string[]; data: string[]; expertDesc: string };
  archive: string;
  steps: CaseStep[];
}

/** V5 列表摘要（无 steps；详情请用 fetchActionCase） */
export interface ActionCaseCard {
  id: string;
  kind: 'problem' | 'opportunity';
  tag: string;
  tag_cls: string;
  case_title: string;
  code: string;
  source: string;
  status: 'open' | 'running' | 'waiting_verify' | 'resolved';
  orchestration: { experts: string[]; data: string[]; expertDesc: string };
  archive: string;
  created_at: string;
  updated_at: string;
}

/** 行动经验沉淀（CaseLesson） */
export interface CaseLesson {
  case_id: string;
  code: string;
  kind: 'problem' | 'opportunity';
  title: string;
  archive: string;
  resolution: string;
  created_at: string;
}

export interface KnowledgeEntry {
  id: number;
  entry_type: 'problem' | 'opportunity' | 'change' | 'lesson';
  source_id: string;
  code: string;
  title: string;
  content: string;
  note: string;
  created_at: string;
}

export interface KnowledgeStats {
  problem: number;
  opportunity: number;
  change: number;
  lesson: number;
}
