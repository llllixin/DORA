import { useEffect, useState } from 'react';
import { actionCases } from '../../data';
import type { ActionCase, ActionCaseCard, ActionCaseDetail, CaseLesson } from '../../types';
import { Tag } from '../../components/ui/Tag';
import {
  archiveAsLesson, blockStep, doneStep, fetchActionCase, listActionCases, listLessons, startStep, verifyAction,
} from '../../services/doraApi';

type Props = {
  joined: string[];
  onTrace: (id: string) => void;
  onNotice: (m: string) => void;
  onExecute: (id: string) => void;
  onAddExpert: () => void;
  onAddData: () => void;
};

const STEP_LABEL: Record<string, string> = {
  pending: '待办', in_progress: '进行中', done: '已完成', blocked: '受阻',
};
const CASE_LABEL: Record<string, string> = {
  open: '已建档', running: '执行中', waiting_verify: '待验证', resolved: '已归档',
};

export function ActionPage({ joined, onTrace, onNotice }: Props) {
  const [cases, setCases] = useState<ActionCaseCard[]>([]);
  const [demo, setDemo] = useState(false);
  const [currentId, setCurrentId] = useState('');
  const [detail, setDetail] = useState<ActionCaseDetail | null>(null);
  const [verifyNote, setVerifyNote] = useState('');
  const [stepNote, setStepNote] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [lessons, setLessons] = useState<CaseLesson[]>([]);
  const [showLessons, setShowLessons] = useState(false);
  const [lessonNote, setLessonNote] = useState('');
  const [learned, setLearned] = useState(false);

  const loadList = async () => {
    try {
      const list = await listActionCases();
      if (list.length) {
        setDemo(false);
        setCases(list);
        setCurrentId((cur) => cur || list[0].id);
      } else {
        setCases([]);
        setDemo(true);
      }
    } catch {
      setCases([]);
      setDemo(true);
    }
  };

  useEffect(() => {
    void loadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!currentId) return;
    let alive = true;
    void (async () => {
      const d = await fetchActionCase(currentId);
      if (alive && d) {
        setDetail(d);
        setLearned(false);
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  const reload = async () => {
    const d = await fetchActionCase(currentId);
    if (d) setDetail(d);
    void loadList();
  };

  useEffect(() => {
    if (demo) return; // 离线演示不轮询
    const timer = window.setInterval(() => {
      void reload();
    }, 20000); // F7：20s 轻量轮询（正式推送留阶段 2 SSE/异步）
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId, demo]);

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try {
      await fn();
      onNotice(msg);
      void reload();
    } catch (err) {
      onNotice(`✗ ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const loadLessons = async () => {
    try {
      setLessons(await listLessons());
    } catch {
      setLessons([]);
    }
  };

  useEffect(() => {
    void loadLessons();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const archiveLesson = async (c: ActionCaseDetail) => {
    try {
      const r = await archiveAsLesson(c.id, lessonNote.trim() || '该问题已按档案处理并验证通过');
      onNotice(r.created ? '✓ 已沉淀经验并加入经验库' : '该档案经验已沉淀（幂等返回既有）');
      setLearned(true);
      void loadLessons();
    } catch (err) {
      onNotice(`✗ ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const demoCases = joined
    .map((id) => actionCases[id])
    .filter((x): x is ActionCase => Boolean(x));

  if (demo) {
    return (
      <section className="page active">
        <div className="head">
          <div>
            <div className="eyebrow">ACTION LOOP · CASE</div>
            <div className="h1">把问题 / 机会推进成可验证的行动档案</div>
            <p className="sub">离线演示：显示本地演示档案（data.ts）。启动后端后这里显示真实行动档案。</p>
          </div>
          <span className="status"><span className="dot" />{demoCases.length} 份行动档案（离线演示）</span>
        </div>
        <div className="card" style={{ padding: 16 }}>
          {demoCases.length === 0 && <div className="action-empty">还没有行动档案。前往「洞察」加入问题 / 机会。</div>}
          {demoCases.map((it) => (
            <div key={it.id} style={{ borderBottom: '1px solid #eee', padding: '8px 0' }}>
              <Tag tone={it.tagCls as 'red' | 'green'}>{it.kind === 'problem' ? '问题' : '机会'}</Tag>
              <b> {it.caseTitle}</b> <small style={{ opacity: 0.6 }}>{it.code}</small>
              <button className="btn" onClick={() => onTrace(it.id)}>打开证据链 →</button>
            </div>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="page active">
      <div className="head">
        <div>
          <div className="eyebrow">ACTION LOOP · CASE</div>
          <div className="h1">把问题 / 机会推进成可验证的行动档案</div>
          <p className="sub">档案来自引擎判定的洞察；步骤执行与验证结果都会回写档案。</p>
        </div>
        <span className="status"><span className="dot" />{cases.length} 份行动档案</span>
      </div>
      <div style={{ display: 'flex', gap: 14, marginTop: 14, alignItems: 'flex-start' }}>
        <div className="card" style={{ padding: drawerOpen ? 12 : 8, width: drawerOpen ? 300 : 60, flexShrink: 0, transition: 'width .18s ease' }}>
          <div style={{ display: drawerOpen ? 'block' : 'none' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '6px 4px 8px' }}>
              <b>档案列表</b>
              <button className="rowbtn" onClick={() => setDrawerOpen(false)}>收起 «</button>
            </div>
          {cases.length === 0 && <div className="action-empty">还没有行动档案。前往「洞察」把问题 / 机会加入行动回路。</div>}
          {cases.map((it) => (
            <button key={it.id} className="suggest" style={{ width: '100%', textAlign: 'left', marginBottom: 6 }}
                    onClick={() => { setCurrentId(it.id); setDetail(null); }}>
              <Tag tone={it.kind === 'problem' ? 'red' : 'green'}>{it.kind === 'problem' ? '问题' : '机会'}</Tag>{' '}
              {it.case_title} <small style={{ opacity: 0.6 }}> · {it.code} · {CASE_LABEL[it.status]}</small>
            </button>
          ))}
            <div style={{ borderTop: '1px solid #eee', marginTop: 8 }}>
              <button className="rowbtn" onClick={() => setShowLessons((v) => !v)}>🧠 学习经验（{lessons.length}）{showLessons ? '▾' : '▸'}</button>
              {showLessons && lessons.map((l) => (
                <div key={l.case_id} style={{ fontSize: 12, marginTop: 6 }}>
                  <b>{l.code} · {l.title}</b>
                  <div style={{ opacity: 0.75 }}>结论：{l.resolution}</div>
                </div>
              ))}
            </div>
          </div>
          {!drawerOpen && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center' }}>
              <button className="rowbtn" onClick={() => setDrawerOpen(true)} title="展开">»</button>
              {cases.map((it) => (
                <button key={it.id} className="rowbtn" title={it.code}
                        onClick={() => { setCurrentId(it.id); setDetail(null); setDrawerOpen(true); }}>
                  {it.code.slice(0, 1)}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="card" style={{ flex: 1, minWidth: 0, padding: 16 }}>
          {!detail && <div className="action-empty">选择左侧档案查看详情（或从洞察加入行动回路）。</div>}
          {detail && (
            <>
              <div className="problem-head">
                <Tag tone={detail.tag_cls === 'red' ? 'red' : 'green'}>{detail.tag}</Tag>
                <b>{detail.case_title}</b>
                <span className="pid">{detail.code}</span>
              </div>
              <div style={{ margin: '6px 0' }}>
                <small>{detail.source}</small> · <small>状态 · {CASE_LABEL[detail.status]}</small>
              </div>
              <button className="btn" onClick={() => onTrace(detail.id)}>打开证据链 →</button>

              {detail.steps.map((st) => (
                <div key={st.seq} style={{ borderTop: '1px solid #eee', padding: '8px 0' }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Tag tone={st.status === 'done' ? 'green' : st.status === 'blocked' ? 'red' : st.status === 'in_progress' ? 'blue' : 'blue'}>
                      {STEP_LABEL[st.status]}
                    </Tag>
                    <b>{st.title}</b>
                    <small style={{ opacity: 0.6 }}>#{st.seq}</small>
                  </div>
                  <p style={{ margin: '4px 0' }}>{st.desc}</p>
                  {st.why && <small style={{ opacity: 0.7 }}>为什么：{st.why}</small>}
                  {st.note && <div style={{ opacity: 0.85 }}>备注：{st.note}</div>}
                  {st.result && <div style={{ opacity: 0.85 }}>结果：{st.result}</div>}
                  {(st.status === 'pending' || st.status === 'blocked') && (
                    <button className="btn" onClick={() => act(() => startStep(detail.id, st.seq), `已开始「${st.title}」`)}>开始</button>
                  )}
                  {st.status === 'in_progress' && (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button className="btn primary" onClick={() => act(() => doneStep(detail.id, st.seq, { note: stepNote || '完成', result: stepNote }), `已完成「${st.title}」`)}>完成</button>
                      <button className="btn" onClick={() => act(() => blockStep(detail.id, st.seq, stepNote || '受阻待处理'), `「${st.title}」已标记受阻`)}>受阻</button>
                    </div>
                  )}
                </div>
              ))}

              {detail.status === 'waiting_verify' && (
                <div style={{ border: '1px solid #cfe3ff', borderRadius: 8, padding: 10, marginTop: 8 }}>
                  <b>验证这一步（结果决定关闭）</b>
                  <input className="delegate-input" style={{ width: '100%' }} placeholder="填写验证说明（如：利润率回到 18.6%，验证通过）"
                         value={verifyNote} onChange={(e) => setVerifyNote(e.target.value)} />
                  <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                    <button className="btn primary" onClick={() => act(() => verifyAction(detail.id, 'resolved', verifyNote), '✓ 已归档（resolved）')}>归档 · 问题解决</button>
                    <button className="btn" onClick={() => act(() => verifyAction(detail.id, 'continue', verifyNote || '继续观察'), '已选择继续观察（continue）')}>继续观察</button>
                  </div>
                </div>
              )}

              {detail.status === 'resolved' && (
                <div style={{ border: '1px solid #cde8cd', background: '#f4fbf4', borderRadius: 8, padding: 10, marginTop: 8 }}>
                  <b>✓ 已归档</b>
                  <pre style={{ whiteSpace: 'pre-wrap', margin: '6px 0 0', font: 'inherit' }}>{detail.archive}</pre>
                  {!learned ? (
                    <div style={{ marginTop: 8 }}>
                      <input className="delegate-input" style={{ width: '100%' }} placeholder="沉淀结论（经验库，供自我学习；选填，默认=已验证通过）"
                             value={lessonNote} onChange={(e) => setLessonNote(e.target.value)} />
                      <button className="btn primary" onClick={() => archiveLesson(detail)}>沉淀经验 → 经验库</button>
                    </div>
                  ) : (
                    <div style={{ marginTop: 8, opacity: 0.85 }}>🧠 已沉淀进经验库（可在抽屉「学习经验」查看处理过程）</div>
                  )}
                </div>
              )}

              <div style={{ marginTop: 12 }}>
                <div className="os-title"><span>专家团</span></div>
                <div className="expert-chips">
                  {(detail.orchestration?.experts ?? []).map((e) => (
                    <span className="expert-chip" key={e}><i>👥</i>{e}<em>系统已选</em></span>
                  ))}
                </div>
              </div>
              <div style={{ marginTop: 8 }}>
                <input className="delegate-input" style={{ width: '100%' }} placeholder="当前步骤备注 / 结果（选填，用于“完成 / 受阻”）"
                       value={stepNote} onChange={(e) => setStepNote(e.target.value)} />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

