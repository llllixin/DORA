import { useEffect, useState } from 'react';
import { actionCases, capabilities } from '../../data';
import type { ActionCase, ActionCaseCard, ActionCaseDetail, CaseStep } from '../../types';
import { Tag } from '../../components/ui/Tag';
import {
  archiveAsLesson, blockStep, doneStep, fetchActionCase, listActionCases, setStepExperts, startStep, verifyAction,
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
/** 列表状态 = 展示层二值映射（D1）：不改状态机与接口；详情页仍显示细粒度状态。 */
const caseStateLabel = (status: string) => (status === 'resolved' ? '已归档' : '执行中');
const STEP_TONE: Record<string, 'green' | 'red' | 'blue'> = {
  done: 'green', blocked: 'red', in_progress: 'blue', pending: 'blue',
};
/** 时间线节点色（复用既有 .tl.done/.tl.active 死 CSS）。 */
const tlClass = (status: string) => (status === 'done' ? 'done ' : status === 'in_progress' ? 'active ' : '');

/** 默认展开「当前步」：首个 in_progress → 首个非 done → 末步（D3，纯展示层 state）。 */
function defaultOpenSeq(steps: CaseStep[]) {
  const active = steps.find((s) => s.status === 'in_progress');
  if (active) return active.seq;
  const todo = steps.find((s) => s.status !== 'done');
  if (todo) return todo.seq;
  return steps.length ? steps[steps.length - 1].seq : -1;
}

/** 候选专家池 = 前端能力目录 ∪ 档案级系统建议（D6；后端不校验白名单）。 */
function expertPool(d: ActionCaseDetail) {
  const caps = (capabilities['专家团'] ?? []).map(([name, desc]) => ({ name, hint: desc, system: false }));
  const extra = (d.orchestration?.experts ?? [])
    .filter((n) => !caps.some((c) => c.name === n))
    .map((name) => ({ name, hint: '档案级系统建议', system: true }));
  return [...caps, ...extra];
}

export function ActionPage({ joined, onTrace, onNotice }: Props) {
  const [cases, setCases] = useState<ActionCaseCard[]>([]);
  const [demo, setDemo] = useState(false);
  const [currentId, setCurrentId] = useState('');
  const [detail, setDetail] = useState<ActionCaseDetail | null>(null);
  const [verifyNote, setVerifyNote] = useState('');
  const [stepNote, setStepNote] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [lessonNote, setLessonNote] = useState('');
  const [learned, setLearned] = useState(false);
  const [openSteps, setOpenSteps] = useState<Record<number, boolean>>({});
  const [poolOpen, setPoolOpen] = useState<Record<number, boolean>>({});

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
        setOpenSteps({ [defaultOpenSeq(d.steps)]: true }); // 换档案重置展开态（D3）
        setPoolOpen({});
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

  /** 整体设置某步负责专家（D4/D5）：失败仅提示、不做乐观更新。 */
  const applyExperts = async (caseId: string, seq: number, next: string[], msg: string) => {
    try {
      const r = await setStepExperts(caseId, seq, next);
      if (r.case) setDetail(r.case);
      onNotice(msg);
      void reload();
    } catch (err) {
      onNotice(`✗ ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const archiveLesson = async (c: ActionCaseDetail) => {
    try {
      const r = await archiveAsLesson(c.id, lessonNote.trim() || '该问题已按档案处理并验证通过');
      onNotice(r.created ? '✓ 已沉淀到知识库 → 经验（可在「知识库」查看）' : '该档案经验已沉淀（幂等返回既有，可在「知识库」查看）');
      setLearned(true);
    } catch (err) {
      onNotice(`✗ ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const demoCases = joined
    .map((id) => actionCases[id])
    .filter((x): x is ActionCase => Boolean(x));

  // 列表排序：执行中在前（D1）；计数供列表头展示
  const sortedCases = [...cases].sort(
    (a, b) => Number(a.status === 'resolved') - Number(b.status === 'resolved') || a.code.localeCompare(b.code),
  );
  const runningCount = cases.filter((c) => c.status !== 'resolved').length;
  const archivedCount = cases.length - runningCount;

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
            <div key={it.id} className="insight-item" style={{ cursor: 'default' }}>
              <div className="itop">
                <Tag tone={it.tagCls as 'red' | 'green'}>{it.kind === 'problem' ? '问题' : '机会'}</Tag>
                <small style={{ opacity: 0.6 }}>{it.code}</small>
              </div>
              <div className="iname">{it.caseTitle}</div>
              <div className="idesc">{it.source}</div>
              <div className="list-status none">离线演示</div>
              <div style={{ marginTop: 6, fontSize: 11, opacity: 0.7 }}>
                演示数据不含步骤状态与负责专家；步骤执行 / 专家分配需后端在线。
              </div>
              <button className="btn" style={{ marginTop: 8 }} onClick={() => onTrace(it.id)}>打开证据链 →</button>
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
          {sortedCases.length > 0 && (
            <div className="list-head"><span>执行中 {runningCount} · 已归档 {archivedCount}</span></div>
          )}
          {sortedCases.map((it) => (
            <button key={it.id} className={'insight-item ' + (it.id === currentId ? 'active' : '')}
                    onClick={() => { setCurrentId(it.id); setDetail(null); }}>
              <div className="itop">
                <Tag tone={it.kind === 'problem' ? 'red' : 'green'}>{it.kind === 'problem' ? '问题' : '机会'}</Tag>
                <small style={{ opacity: 0.6 }}>{it.code}</small>
              </div>
              <div className="iname">{it.case_title}</div>
              <div className="idesc">{it.source}</div>
              <div className={'list-status ' + (it.status === 'resolved' ? 'none' : 'action')}>
                {caseStateLabel(it.status)}
              </div>
            </button>
          ))}
            <div style={{ borderTop: '1px solid #eee', marginTop: 8 }}>
              <div style={{ fontSize: 11, opacity: 0.7, marginTop: 6 }}>
                经验已收口到「知识库 → 经验」：沉淀后在知识库查看处理过程与结论。
              </div>
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

              <div className="timeline">
                {detail.steps.map((st) => {
                  const open = !!openSteps[st.seq];
                  const experts = st.experts ?? [];
                  const pool = expertPool(detail).filter((c) => !experts.includes(c.name));
                  const frozen = detail.status === 'resolved'; // resolved 冻结推进与专家设置（D5）
                  return (
                    <div key={st.seq} className={'tl ' + tlClass(st.status)}>
                      <div className="tldot">{st.seq + 1}</div>
                      <div className="tl-body">
                        <div className="tl-head">
                          <h4>
                            <Tag tone={STEP_TONE[st.status]}>{STEP_LABEL[st.status]}</Tag>
                            {' '}{st.title} <small style={{ opacity: 0.6 }}>#{st.seq}</small>
                          </h4>
                          <div className="tl-actions">
                            {!frozen && (st.status === 'pending' || st.status === 'blocked') && (
                              <button className="btn" onClick={() => act(() => startStep(detail.id, st.seq), `已开始「${st.title}」`)}>开始</button>
                            )}
                            {!frozen && st.status === 'in_progress' && (
                              <>
                                <button className="btn primary" onClick={() => act(() => doneStep(detail.id, st.seq, { note: stepNote || '完成', result: stepNote }), `已完成「${st.title}」`)}>完成</button>
                                <button className="btn" onClick={() => act(() => blockStep(detail.id, st.seq, stepNote || '受阻待处理'), `「${st.title}」已标记受阻`)}>受阻</button>
                              </>
                            )}
                            <button className="rowbtn" onClick={() => setOpenSteps((v) => ({ ...v, [st.seq]: !v[st.seq] }))}>
                              {open ? '收起' : '展开'}
                            </button>
                          </div>
                        </div>
                        {open && (
                          <div className="tl-more">
                            <p>{st.desc}</p>
                            {st.why && <p>为什么：{st.why}</p>}
                            {st.note && <div style={{ opacity: 0.85 }}>备注：{st.note}</div>}
                            {st.result && <div style={{ opacity: 0.85 }}>结果：{st.result}</div>}
                            <div className="os-title" style={{ marginTop: 8 }}>
                              <span>负责专家团</span>
                              {!frozen && experts.length < 8 && (
                                <button className="add-mini" onClick={() => setPoolOpen((v) => ({ ...v, [st.seq]: !v[st.seq] }))}>
                                  {poolOpen[st.seq] ? '收起候选' : '+ 添加专家'}
                                </button>
                              )}
                            </div>
                            <div className="expert-chips">
                              {experts.length === 0 && <span style={{ fontSize: 12, opacity: 0.7 }}>未指定负责专家</span>}
                              {experts.map((e) => (
                                <span className="expert-chip user" key={e}>
                                  <i>👤</i>{e}<em>用户指定</em>
                                  {!frozen && (
                                    <button style={{ border: 0, background: 'transparent', color: 'inherit', font: 'inherit', cursor: 'pointer' }}
                                            onClick={() => applyExperts(detail.id, st.seq, experts.filter((x) => x !== e), `✓ 已移除「${st.title}」的负责专家 ${e}`)}>×</button>
                                  )}
                                </span>
                              ))}
                            </div>
                            {poolOpen[st.seq] && !frozen && (
                              <div className="expert-chips" style={{ marginTop: 6 }}>
                                {pool.length === 0 && <span style={{ fontSize: 12, opacity: 0.7 }}>候选专家已全部加入</span>}
                                {pool.map((c) => (
                                  <button className="expert-chip" key={c.name}
                                          onClick={() => applyExperts(detail.id, st.seq, [...experts, c.name], `✓ 已把「${c.name}」指定给「${st.title}」`)}>
                                    <i>＋</i>{c.name}<em>{c.system ? '系统建议' : c.hint}</em>
                                  </button>
                                ))}
                              </div>
                            )}
                            <div className="os-title" style={{ marginTop: 8 }}>
                              <span>数据定位</span>
                              <button className="step-trace" onClick={() => onTrace(detail.id)}>定位数据 →</button>
                            </div>
                            <span className="step-evidence">{st.evidence || '暂无定位说明'}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

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
                      <input className="delegate-input" style={{ width: '100%' }} placeholder="沉淀结论（写入知识库「经验」；选填，默认=已验证通过）"
                             value={lessonNote} onChange={(e) => setLessonNote(e.target.value)} />
                      <button className="btn primary" onClick={() => archiveLesson(detail)}>沉淀经验 → 知识库</button>
                    </div>
                  ) : (
                    <div style={{ marginTop: 8, opacity: 0.85 }}>🧠 已沉淀到知识库「经验」（在「知识库」页查看处理过程与结论）</div>
                  )}
                </div>
              )}

              <div style={{ marginTop: 12 }}>
                <div className="os-title"><span>档案级专家团 · 系统建议</span></div>
                <div className="expert-chips">
                  {(detail.orchestration?.experts ?? []).length === 0 && <span style={{ fontSize: 12, opacity: 0.7 }}>暂无系统建议</span>}
                  {(detail.orchestration?.experts ?? []).map((e) => (
                    <span className="expert-chip" key={e}><i>👥</i>{e}<em>系统建议</em></span>
                  ))}
                </div>
                <small style={{ opacity: 0.7 }}>每步「谁负责」以步骤时间线内的负责专家为准；此处为引擎建档时的整体建议。</small>
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

