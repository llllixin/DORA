import { useEffect, useRef, useState } from 'react';
import { knowledgeApi } from '../../services/queryApi';
import { errorText } from '../../services/queryContract';
import type { QueryPacket, QueryOptions } from '../../services/queryTypes';
import { QueryResult } from './QueryResult';
import type { SelectSource } from './QueryResult';
export function QuestionPanel({ onSelectSource }: {
    onSelectSource: SelectSource;
}) {
    const [question, setQuestion] = useState(''), [include, setInclude] = useState(false), [pending, setPending] = useState(false), [error, setError] = useState(''), [stale, setStale] = useState(false);
    const [result, setResult] = useState<{
        packet: QueryPacket;
        question: string;
        options: QueryOptions;
    } | null>(null);
    const request = useRef<AbortController | null>(null), key = useRef(0);
    useEffect(() => () => { key.current++; request.current?.abort(); }, []);
    async function submit(search = false) {
        if (request.current)
            return;
        const text = question.trim();
        if ([...text].length < 1 || [...text].length > 300) {
            setError('请输入 1 至 300 个字的问题。');
            return;
        }
        const controller = new AbortController();
        request.current = controller;
        const current = ++key.current, options = { includeSimulated: include };
        setPending(true);
        setError('');
        setStale(!!result);
        try {
            const packet = await (search ? knowledgeApi.searchKnowledge({ query: text, ...options }, controller.signal) : knowledgeApi.answerQuestion({ question: text, ...options }, controller.signal));
            if (current === key.current) {
                setResult({ packet, question: text, options });
                setStale(false);
            }
        }
        catch (e) {
            if (current === key.current) {
                setError(errorText(e));
                setStale(!!result);
            }
        }
        finally {
            if (current === key.current) {
                request.current = null;
                setPending(false);
            }
        }
    }
    function cancel() { key.current++; request.current?.abort(); request.current = null; setPending(false); setError('已停止等待，服务端可能仍在处理。'); setStale(!!result); }
    return <div className="question-panel"><section className="knowledge-panel"><h2>问一个经营问题</h2><form onSubmit={e => { e.preventDefault(); void submit(); }} noValidate>
  <label htmlFor="knowledge-question">你的问题</label><textarea id="knowledge-question" rows={3} value={question} onChange={e => setQuestion(e.target.value)} aria-describedby="question-hint question-error" aria-invalid={!!error || undefined} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!e.nativeEvent.isComposing && e.keyCode !== 229)
            void submit();
    } }}/>
  <div className="question-help"><p id="question-hint">可问指标定义、最新载入数据或处理记录。Enter 提问，Shift+Enter 换行。</p><span>{[...question.trim()].length} / 300</span></div>
  <label className="knowledge-checkbox"><input type="checkbox" id="include-simulated" checked={include} onChange={e => setInclude(e.target.checked)}/>包含模拟资料</label>
  <div className="knowledge-actions"><button className="knowledge-primary" type="submit" data-action="answer" disabled={pending}>提问</button><button type="button" data-action="search" disabled={pending} onClick={() => void submit(true)}>检索资料</button>{pending && <button type="button" data-action="cancel" onClick={cancel}>停止等待</button>}</div>
  <p id="question-error" className={error ? 'question-error knowledge-error' : ''} role={error ? 'alert' : undefined}>{error}</p>
 </form><div className="knowledge-examples" aria-label="示例问题">{['利润率是什么？', '最新全国利润率是多少？'].map(q => <button type="button" key={q} onClick={() => setQuestion(q)}>{q}</button>)}</div></section>
 {pending && <div className="knowledge-panel knowledge-loading" role="status"><p>正在等待结果，可以停止等待；服务端可能仍在处理。</p><div aria-hidden="true"/></div>}
 {result && <QueryResult {...result} stale={stale} onSelectSource={onSelectSource}/>}
 </div>;
}
