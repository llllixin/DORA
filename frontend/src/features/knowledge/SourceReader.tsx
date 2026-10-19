import { useEffect, useRef, useState } from 'react';
import { knowledgeApi } from '../../services/queryApi';
import { errorText } from '../../services/queryContract';
import type { QueryEvidence, SourceDocument, SourceSelection } from '../../services/queryTypes';
import { gradeText, valueText } from './QueryResult';
import type { SelectSource } from './QueryResult';
export function SourceReader({ selection, trigger, onClose, onSelectSource }: {
    selection: SourceSelection;
    trigger: HTMLElement;
    onClose: () => void;
    onSelectSource: SelectSource;
}) {
    const dialog = useRef<HTMLDialogElement>(null), title = useRef<HTMLHeadingElement>(null), closeRef = useRef(onClose);
    closeRef.current = onClose;
    const [loaded, setLoaded] = useState<{
        key: string;
        value: QueryEvidence | SourceDocument;
    } | null>(null), [error, setError] = useState(''), [tick, setTick] = useState(0), [pending, setPending] = useState(true);
    const key = JSON.stringify(selection);
    useEffect(() => { const el = dialog.current!, previous = document.body.style.overflow; document.body.style.overflow = 'hidden'; el.showModal(); title.current?.focus(); return () => { el.close(); document.body.style.overflow = previous; (trigger.isConnected ? trigger : document.querySelector<HTMLElement>('#knowledge-title'))?.focus(); }; }, []);
    useEffect(() => { const controller = new AbortController(); let alive = true; setPending(true); setError(''); const promise = selection.kind === 'evidence' ? knowledgeApi.getRunEvidence(selection, controller.signal) : selection.kind === 'wiki' ? knowledgeApi.getWikiCard(selection.documentId, selection.version, controller.signal) : knowledgeApi.getStoredDocument(selection.documentId, selection.version, controller.signal); promise.then(value => { if (alive)
        setLoaded({ key, value }); }).catch(e => { if (alive)
        setError(errorText(e)); }).finally(() => { if (alive)
        setPending(false); }); return () => { alive = false; controller.abort(); }; }, [key, tick]);
    const value = loaded?.key === key ? loaded.value : null, evidence = selection.kind === 'evidence' ? value as QueryEvidence | null : null;
    return <dialog className="source-reader" ref={dialog} aria-labelledby="reader-title" onKeyDown={event => {
            if (event.key !== 'Tab')
                return;
            const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')).filter(el => el.getClientRects().length > 0);
            const first = controls[0], last = controls[controls.length - 1];
            if (event.shiftKey && (document.activeElement === first || document.activeElement === title.current)) {
                event.preventDefault();
                last?.focus();
            }
            else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first?.focus();
            }
        }} onCancel={e => { e.preventDefault(); closeRef.current(); }}><div className="reader-layout"><header><h2 id="reader-title" tabIndex={-1} ref={title}>资料原文</h2><button type="button" aria-label="关闭资料原文" onClick={onClose}>关闭</button></header><div className="reader-scroll">{pending && <p role="status">正在读取原始版本…</p>}{error && <div className="knowledge-error" role="alert"><p>{error}</p><button type="button" onClick={() => setTick(v => v + 1)}>重试此版本</button></div>}
 {value && <div className="reader-content">{(pending || error) && <p className="knowledge-notice">上次读取的会话副本</p>}<h3>{valueText(evidence ? evidence.data.title : value.title)}</h3>{evidence ? <><p className="knowledge-meta">{gradeText(evidence.evidenceLevel)} · {gradeText(evidence.approvalStatus)} · {evidence.sourceMode === 'simulated' ? '模拟资料' : valueText(evidence.sourceMode)}</p><pre>{valueText(evidence.data.text ?? evidence.data)}</pre><dl>{[['原始观测周期', evidence.observedPeriod], ['读取时间', evidence.readAt], ['主体 / 范围', evidence.subject], ['历史快照', evidence.snapshotId], ['历史发生标识', evidence.occurrenceId], ['归档版本', evidence.archiveVersion], ['内容摘要', evidence.contentHash]].map(([label, v]) => <div key={String(label)}><dt>{String(label)}</dt><dd>{valueText(v)}</dd></div>)}</dl>{evidence.documentId && typeof evidence.documentVersion === 'number' && <div className="knowledge-actions"><button type="button" onClick={e => onSelectSource({ kind: 'wiki', documentId: evidence.documentId!, version: evidence.documentVersion! }, e.currentTarget)}>补充阅读源卡 v{evidence.documentVersion}</button><button type="button" onClick={e => onSelectSource({ kind: 'stored', documentId: evidence.documentId!, version: evidence.documentVersion! }, e.currentTarget)}>补充阅读存储版本</button></div>}</> : <><p className="knowledge-meta">明确版本 v{valueText(value.version)} · 补充资料，不能替代请求时证据</p><pre>{valueText(value.content)}</pre><details><summary>来源与资格信息</summary><pre>{valueText(value)}</pre></details></>}</div>}
 </div><footer><button type="button" onClick={onClose}>返回刚才的位置</button></footer></div></dialog>;
}
