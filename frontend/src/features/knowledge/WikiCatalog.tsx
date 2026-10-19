import { useEffect, useState } from 'react';
import { knowledgeApi } from '../../services/queryApi';
import { errorText } from '../../services/queryContract';
import type { CatalogPage, CatalogParams } from '../../services/queryTypes';
import { gradeText } from './QueryResult';
import type { SelectSource } from './QueryResult';
export function WikiCatalog({ onSelectSource }: {
    onSelectSource: SelectSource;
}) {
    const [q, setQ] = useState(''), [type, setType] = useState(''), [include, setInclude] = useState(false), [params, setParams] = useState<CatalogParams>({ offset: 0, pageSize: 20, includeSimulated: false });
    const [page, setPage] = useState<CatalogPage | null>(null), [pending, setPending] = useState(true), [error, setError] = useState(''), [tick, setTick] = useState(0);
    useEffect(() => { const controller = new AbortController(); let alive = true; setPending(true); setError(''); knowledgeApi.getWikiCatalog(params, controller.signal).then(value => { if (alive)
        setPage(value); }).catch(e => { if (alive)
        setError(errorText(e)); }).finally(() => { if (alive)
        setPending(false); }); return () => { alive = false; controller.abort(); }; }, [params, tick]);
    const reset = () => setParams({ q, knowledgeType: type, includeSimulated: include, offset: 0, pageSize: 20 });
    return <section className="knowledge-panel wiki-catalog"><h2>阅读 Wiki</h2><p className="knowledge-meta">阅读当前具备资格的资料；正文按明确版本打开。</p>
 <form className="catalog-form" onSubmit={e => { e.preventDefault(); if ([...q].length <= 300)
        reset(); }}><label>搜索资料标题<input type="search" value={q} onChange={e => setQ(e.target.value)} maxLength={600}/></label><label>知识类型<select value={type} onChange={e => setType(e.target.value)}><option value="">全部类型</option>{[['glossary', '术语'], ['rule', '规则'], ['procedure', '流程'], ['case', '案例'], ['external', '外部资料']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label><label className="knowledge-checkbox"><input type="checkbox" checked={include} onChange={e => setInclude(e.target.checked)}/>包含模拟资料</label><button type="submit" disabled={[...q].length > 300}>搜索资料</button><button type="button" onClick={() => { setQ(''); setType(''); setInclude(false); setParams({ offset: 0, pageSize: 20, includeSimulated: false }); }}>清空筛选</button></form>
 {[...q].length > 300 && <p className="knowledge-error" role="alert">搜索词最多 300 个字。</p>}{pending && <p role="status">正在读取目录{params.offset ? `第 ${Math.floor(params.offset / 20) + 1} 页` : ''}…</p>}{error && <div className="knowledge-error" role="alert"><p>{error}</p><button type="button" data-retry onClick={() => { if (params.offset)
        reset();
    else
        setTick(t => t + 1); }}>重新读取目录</button></div>}
 {page && <><p className="knowledge-meta" role="status">{pending || error ? '上次读取的目录 · ' : ''}共 {page.total} 份 · 当前 {page.cards.length ? page.offset + 1 : 0}–{page.offset + page.cards.length} 份{!['in_sync', 'ready'].includes(page.indexStatus) ? ` · 索引状态：${page.indexStatus}，可阅读原文，检索可能未就绪` : ''}</p>{!page.cards.length && !pending && !error && <p>没有找到匹配资料。请清空筛选后重试。</p>}<ul className="catalog-cards">{page.cards.map(c => <li key={`${c.id}@${c.version}`}><h3><button type="button" data-source="wiki" onClick={e => onSelectSource({ kind: 'wiki', documentId: c.id, version: c.version }, e.currentTarget)}>{c.title}</button></h3><p className="knowledge-meta">{c.knowledgeType} · v{c.version} · {gradeText(c.evidenceLevel)} · {gradeText(c.approvalStatus)}</p></li>)}</ul><div className="knowledge-pagination"><button type="button" data-page="prev" disabled={pending || !!error || page.offset === 0} onClick={() => setParams({ ...params, offset: Math.max(0, page.offset - page.pageSize), expectedCatalogRevision: page.catalogRevision })}>上一页</button><button type="button" data-page="next" disabled={pending || !!error || !page.hasMore} onClick={() => setParams({ ...params, offset: page.offset + page.pageSize, expectedCatalogRevision: page.catalogRevision })}>下一页</button></div></>}
 </section>;
}
