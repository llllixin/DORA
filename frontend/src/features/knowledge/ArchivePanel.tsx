import { useEffect, useState } from 'react';
import type { KnowledgeEntry, KnowledgeStats } from '../../types';
import { knowledgeApi } from '../../services/queryApi';
import { errorText } from '../../services/queryContract';
import type { KnowledgeRoute } from './knowledgeRoute';
import { writeKnowledgeRoute } from './knowledgeRoute';
const filters = [['', '全部'], ['problem', '问题'], ['opportunity', '机会'], ['change', '变化'], ['lesson', '经验']] as const;
export function ArchivePanel({ route }: {
    route: KnowledgeRoute;
}) {
    const [value, setValue] = useState<{
        entries: KnowledgeEntry[];
        stats: KnowledgeStats;
    } | null>(null), [pending, setPending] = useState(true), [error, setError] = useState(''), [tick, setTick] = useState(0);
    useEffect(() => { const controller = new AbortController(); let alive = true; setPending(true); setError(''); knowledgeApi.getKnowledgeArchive(route.archiveType, controller.signal).then(v => { if (alive)
        setValue(v); }).catch(e => { if (alive)
        setError(errorText(e)); }).finally(() => { if (alive)
        setPending(false); }); return () => { alive = false; controller.abort(); }; }, [route.archiveType, tick]);
    const stats = value?.stats, total = stats ? Object.values(stats).reduce((a, b) => a + b, 0) : null;
    return <section className="knowledge-panel archive-panel"><h2>处理归档</h2><p className="knowledge-meta">保留行动的处理过程与结论，按问题、机会、变化、经验筛选复盘。</p><div className="knowledge-filters" role="group" aria-label="归档类型">{filters.map(([v, l]) => <button key={v} type="button" aria-pressed={route.archiveType === v} onClick={() => writeKnowledgeRoute({ ...route, archiveType: v, openKey: '' })}>{l}{stats ? `（${v ? stats[v] : total}）` : ''}</button>)}</div>
 {pending && <p role="status">正在读取归档…</p>}{error && <div role="alert" className="knowledge-error"><p>{error}</p><button type="button" data-retry onClick={() => setTick(v => v + 1)}>重新读取归档</button></div>}
 {value && <><p role="status" className="knowledge-meta">{pending || error ? '上次读取的归档 · ' : ''}{value.entries.length} 条当前视图 · 共 {total} 条知识</p>{!value.entries.length && !pending && !error && <div><p>{route.archiveType ? '还没有该类别的归档知识。' : '还没有归档知识。'}完成行动档案并「沉淀经验」后会自动出现在这里。</p>{route.archiveType ? <button type="button" onClick={() => writeKnowledgeRoute({ ...route, archiveType: '', openKey: '' })}>查看全部归档</button> : <a href="#page=knowledge&task=wiki">阅读 Wiki</a>}</div>}
 {value.entries.map(e => { const key = `${e.entry_type}-${e.source_id}-${e.id}`, open = route.openKey === key, id = `archive-content-${e.id}`; return <article className="archive-card" key={key}><h3>{e.title}</h3><p className="knowledge-meta">{filters.find(f => f[0] === e.entry_type)?.[1]} · {e.code} · {e.created_at.replace('T', ' ').slice(0, 16)}</p>{e.note && <p>结论：{e.note}</p>}<button type="button" data-archive-expand aria-expanded={open} aria-controls={id} onClick={() => writeKnowledgeRoute({ ...route, openKey: open ? '' : key })}>处理过程 {open ? '▾' : '▸'}</button><div id={id} hidden={!open}><pre>{e.content || '（无处理过程记录）'}</pre></div></article>; })}</>}
 </section>;
}
