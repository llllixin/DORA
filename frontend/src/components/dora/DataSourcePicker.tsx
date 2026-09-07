import { useEffect, useRef, useState } from 'react';
import type { DataSource } from '../../types';
import { loadSampleDataset, uploadDataset } from '../../services/doraApi';

const SAMPLE = '门店经营数据.xlsx';
const PHASES = ['读取与清洗数据', '建立经营口径', '检测趋势 / 阈值 / 结构变化'];

function nowHHmm(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function DataSourcePicker({ onPick }: { onPick: (ds: DataSource) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const timers = useRef<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState(0);
  const [sel, setSel] = useState('');
  const [over, setOver] = useState(false);

  const clearTimers = () => {
    timers.current.forEach((id) => window.clearTimeout(id));
    timers.current = [];
  };

  useEffect(() => clearTimers, []);

  const run = async (name: string, kind: 'sample' | 'upload', file?: File) => {
    if (busy) return;
    clearTimers();
    setBusy(true);
    setPhase(0);
    setSel(name);
    timers.current.push(window.setTimeout(() => setPhase(1), 600));
    timers.current.push(window.setTimeout(() => setPhase(2), 1200));
    timers.current.push(
      window.setTimeout(async () => {
        let rows = kind === 'sample' ? 2847 : 0;
        try {
          if (kind === 'sample') {
            const r = await loadSampleDataset();
            rows = (r as { counts?: { metric_series?: number } }).counts?.metric_series ?? 2847;
          } else if (file) {
            const r = await uploadDataset(file);
            rows = (r as { rows?: number }).rows ?? 0;
          }
        } catch (err) {
          console.warn('[DataSourcePicker] 后端接口失败（离线回退本地）', err);
        }
        setBusy(false);
        onPick({ name, kind, at: kind === 'sample' ? '09:32' : nowHHmm(), rows, fields: 36 });
      }, 1900),
    );
  };

  const pickFile = (f: File | undefined | null) => {
    if (!f) return;
    if (inputRef.current) inputRef.current.value = '';
    void run(f.name, 'upload', f);
  };

  return (
    <div className="up-zone">
      <label
        className={'up-drop' + (over ? ' over' : '')}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); pickFile(e.dataTransfer.files?.[0]); }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xls,.csv,.tsv,.xlsm"
          onChange={(e) => pickFile(e.target.files?.[0])}
        />
        <div className="up-ico">⇪</div>
        <b>点击选择或拖入经营数据文件</b>
        <span>xlsx / xls / csv · 单个文件</span>
      </label>

      {busy ? (
        <div className="up-parse">
          <div className="up-spin" aria-hidden="true" />
          <div>
            <b>{sel}</b>
            <div className="up-phase">
              {PHASES.map((p, i) => (
                <span key={p} className={i < phase ? 'done' : i === phase ? 'active' : ''}>
                  {i < phase ? '✓' : i === phase ? '●' : '○'} {p}
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="up-or">或</div>
          <button className="btn up-sample" onClick={() => void run(SAMPLE, 'sample')}>
            载入内置样例数据（{SAMPLE} · 09:32 更新）
          </button>
        </>
      )}
    </div>
  );
}
