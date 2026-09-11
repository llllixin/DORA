import { useEffect, useState } from 'react';
import type { KnowledgeEntry, KnowledgeStats } from '../../types';
import { Tag } from '../../components/ui/Tag';
import { listKnowledge } from '../../services/doraApi';

const FILTERS: { value: '' | 'problem' | 'opportunity' | 'change' | 'lesson'; label: string; tone: 'red' | 'green' | 'blue' | 'ai' }[] = [
  { value: '', label: '全部', tone: 'blue' },
  { value: 'problem', label: '问题', tone: 'red' },
  { value: 'opportunity', label: '机会', tone: 'green' },
  { value: 'change', label: '变化', tone: 'blue' },
  { value: 'lesson', label: '经验', tone: 'ai' },
];

export function KnowledgePage() {
  const [type, setType] = useState<'' | 'problem' | 'opportunity' | 'change' | 'lesson'>('');
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [stats, setStats] = useState<KnowledgeStats>({ problem: 0, opportunity: 0, change: 0, lesson: 0 });
  /** 处理过程展开态（action-loop-timeline）：默认收起，点击展开；key = 条目唯一键。 */
  const [openKey, setOpenKey] = useState('');

  const load = async (t: typeof type) => {
    const r = await listKnowledge(t);
    setEntries(r.entries);
    setStats(r.stats);
  };

  useEffect(() => {
    void load(type);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type]);

  const toneFor = (et: string) =>
    et === 'problem' ? ('red' as const) : et === 'opportunity' ? ('green' as const) : et === 'lesson' ? ('ai' as const) : ('blue' as const);
  const labelFor = (et: string) =>
    et === 'problem' ? '问题' : et === 'opportunity' ? '机会' : et === 'change' ? '变化' : '经验';

  return (
    <section className="page active">
      <div className="head">
        <div>
          <div className="eyebrow">KNOWLEDGE · ARCHIVE DB</div>
          <div className="h1">Dora 知识 / 归档库</div>
          <p className="sub">行动闭环结束后，处理过程与结论自动按类型入库（问题 / 机会 / 变化 / 经验），可筛选复盘。</p>
        </div>
        <span className="status"><span className="dot" />{entries.length} 条当前视图 · 共 {stats.problem + stats.opportunity + stats.change + stats.lesson} 条知识</span>
      </div>
      <div className="delegate" style={{ marginBottom: 12 }}>
        <div className="suggests" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {FILTERS.map((f) => (
            <button key={f.value} className={'freq-chip ' + (type === f.value ? 'active' : '')}
                    onClick={() => setType(f.value)}>
              {f.label}（{f.value === '' ? stats.problem + stats.opportunity + stats.change + stats.lesson : stats[f.value]}）
            </button>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {entries.length === 0 && (
          <div className="card action-empty">
            还没有该类别的归档知识。完成行动档案并「沉淀经验」后会自动出现在这里。
          </div>
        )}
        {entries.map((e) => {
          const rowKey = `${e.entry_type}-${e.source_id}-${e.id}`;
          const open = openKey === rowKey;
          return (
            <div key={rowKey} className="card" style={{ padding: 14 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <Tag tone={toneFor(e.entry_type)}>{labelFor(e.entry_type)}</Tag>
                <b>{e.title}</b>
                <small style={{ opacity: 0.6 }}>{e.code} · {e.created_at.replace('T', ' ').slice(0, 16)}</small>
              </div>
              {e.note && <div style={{ marginTop: 8, opacity: 0.9 }}>结论：{e.note}</div>}
              <div style={{ marginTop: 6 }}>
                <button className="rowbtn" onClick={() => setOpenKey((v) => (v === rowKey ? '' : rowKey))}>
                  处理过程 {open ? '▾' : '▸'}
                </button>
                {open && (
                  <pre style={{ whiteSpace: 'pre-wrap', font: 'inherit', opacity: 0.85, margin: '4px 0 0' }}>{e.content || '（无处理过程记录）'}</pre>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
