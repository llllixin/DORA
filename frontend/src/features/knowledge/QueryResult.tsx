import { useState } from 'react';
import type { QueryPacket, QueryOptions, QueryEvidence, SourceSelection } from '../../services/queryTypes';
export const valueText = (v: unknown): string => v === null || v === undefined || v === '' ? '未提供' : typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v);
const statuses = { answered: '已回答', partial: '部分回答', clarification_required: '需要澄清', abstained: '资料不足', limited: '达到本次限制', failed: '本次未完成' };
const grades: Record<string, string> = { simulated: '模拟资料', legacy_unknown: '来源等级未知', unreviewed_record: '未经评审的处理记录', project: '项目资料', reported: '上报记录', reviewed: '已评审' };
export const gradeText = (v: unknown) => grades[String(v)] || valueText(v);
export type SelectSource = (selection: SourceSelection, trigger: HTMLElement) => void;
export function EvidenceSummary({ e, runId, onSelectSource }: {
    e: QueryEvidence;
    runId: string;
    onSelectSource: SelectSource;
}) {
    return <li><button type="button" data-source="evidence" onClick={event => onSelectSource({ kind: 'evidence', runId, evidenceId: e.evidenceId, contentHash: e.contentHash }, event.currentTarget)}>{valueText(e.data.title || e.sourceKind)}</button><span className="knowledge-meta">{gradeText(e.evidenceLevel)} · {gradeText(e.approvalStatus)} · {e.sourceMode === 'simulated' ? '模拟资料' : valueText(e.sourceMode)}</span></li>;
}
export function QueryResult({ packet, question, options, stale, onSelectSource }: {
    packet: QueryPacket;
    question: string;
    options: QueryOptions;
    stale: boolean;
    onSelectSource: SelectSource;
}) {
    const [copied, setCopied] = useState('');
    return <section className="knowledge-panel query-result" data-status={packet.status} aria-labelledby="query-result-title">
  <h2 id="query-result-title">{packet.answer === undefined ? '资料检索结果' : '本次回答'}</h2>
  {stale && <p className="knowledge-notice">上次读取的会话副本，本次请求未更新此结果。</p>}
  <p className="submitted-question">问题：{question}</p><p role="status">{statuses[packet.status]}</p>
  {packet.answer && <p className="answer-text">{packet.answer}</p>}
  {!!packet.missingParts.length && <p>尚缺资料：{packet.missingParts.join('、')}</p>}
  {!!packet.clarifications.length && <ul>{packet.clarifications.map((v, i) => <li key={i}>{v}</li>)}</ul>}
  <p className="knowledge-meta">{options.includeSimulated ? '已纳入模拟资料' : '未纳入模拟资料'} · 读取时间：{valueText(packet.readAt)}</p>
  <ul className="knowledge-sources" aria-label="本次引用">{packet.evidence.map(e => <EvidenceSummary key={e.evidenceId} e={e} runId={packet.runId} onSelectSource={onSelectSource}/>)}</ul>
  {!packet.evidence.length && <p>本次没有可展示的引用。</p>}
  {packet.answer && <><button type="button" onClick={async () => { try {
        await navigator.clipboard.writeText(packet.answer!);
        setCopied('已复制答案');
    }
    catch {
        setCopied('复制失败，请手动选取答案');
    } }}>复制答案</button><span role="status">{copied}</span></>}
  <details className="knowledge-details"><summary>版本与本次记录</summary><dl><dt>运行记录</dt><dd>{packet.runId}</dd><dt>数据版本</dt><dd>{valueText(packet.businessVersion)}</dd><dt>知识源版本</dt><dd>{valueText(packet.sourceRevision)}</dd><dt>实际 Token / 费用</dt><dd>{valueText((packet.usage as Record<string, unknown> | undefined)?.totalTokens)} / {valueText((packet.usage as Record<string, unknown> | undefined)?.estimatedCost)}</dd><dt>来源状态 / 原因</dt><dd>{valueText(packet.sourceStates)} {valueText(packet.reasonCode)}</dd></dl></details>
 </section>;
}
