import { useEffect, useState } from 'react';
import type { SourceSelection } from '../../services/queryTypes';
import { readKnowledgeRoute, knowledgeHref } from './knowledgeRoute';
import { QuestionPanel } from './QuestionPanel';
import { WikiCatalog } from './WikiCatalog';
import { ArchivePanel } from './ArchivePanel';
import { SourceReader } from './SourceReader';
import './knowledge.css';
export function KnowledgePage() {
    const [route, setRoute] = useState(() => readKnowledgeRoute(location.hash)), [reader, setReader] = useState<{
        selection: SourceSelection;
        trigger: HTMLElement;
    } | null>(null);
    useEffect(() => { const change = () => { setRoute(readKnowledgeRoute(location.hash)); setReader(null); }; window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, []);
    const select = (selection: SourceSelection, trigger: HTMLElement) => setReader(previous => ({ selection, trigger: previous?.trigger ?? trigger }));
    return <section className="page active knowledge-page"><div className="knowledge-heading"><div className="eyebrow">KNOWLEDGE</div><h1 id="knowledge-title" tabIndex={-1}>知识库</h1><p>提出经营问题，核对资料原文，回看处理过程。</p></div>
  <nav className="knowledge-tasks" aria-label="知识库任务">{([['ask', '问答'], ['wiki', 'Wiki'], ['archive', '处理归档']] as const).map(([task, label]) => <a key={task} data-task={task} href={knowledgeHref({ ...route, task })} aria-current={route.task === task ? 'page' : undefined}>{label}</a>)}</nav>
  {route.task === 'ask' && <QuestionPanel onSelectSource={select}/>} {route.task === 'wiki' && <WikiCatalog onSelectSource={select}/>} {route.task === 'archive' && <ArchivePanel route={route}/>}
  {reader && <SourceReader {...reader} onSelectSource={select} onClose={() => setReader(null)}/>}
 </section>;
}
