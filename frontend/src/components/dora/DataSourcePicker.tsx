import { useEffect, useRef, useState } from 'react';
import type { DataSource } from '../../types';
import { loadSampleDataset, mappedDataset, previewDataset, uploadDataset } from '../../services/doraApi';

const SAMPLE = '门店经营数据.xlsx';
const PHASES = ['读取与清洗数据', '建立经营口径', '检测趋势 / 阈值 / 结构变化'];
const METRIC_KEYS = ['margin', 'returns', 'orders', 'revenue', 'aov', 'east_orders', 'new_sku', 'high_value', 'supplier_price'];

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
  const [pvCols, setPvCols] = useState<string[] | null>(null);
  const [mapFile, setMapFile] = useState<File | null>(null);
  const [mKey, setMKey] = useState('margin');
  const [mValue, setMValue] = useState('');
  const [mLabel, setMLabel] = useState('');
  const [mDim, setMDim] = useState('');
  const [mapErr, setMapErr] = useState('');
  const [mapBusy, setMapBusy] = useState(false);

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

  const pickFile = async (f: File | undefined | null) => {
    if (!f || busy) return;
    if (inputRef.current) inputRef.current.value = '';
    setMapErr('');
    setMapBusy(false);
    setPvCols(null);
    setMapFile(null);
    try {
      const pv = await previewDataset(f);
      if (pv && Array.isArray(pv.columns) && pv.columns.length) {
        setPvCols(pv.columns);
        setMapFile(f);
        setMValue(pv.columns[0]);
        setMLabel(pv.columns[1] ?? pv.columns[0]);
        setMDim('');
        return;
      }
    } catch (err) {
      console.warn('[DataSourcePicker] 预览失败，走规范直传', err);
    }
    void run(f.name, 'upload', f);
  };

  const closeMap = () => {
    setPvCols(null);
    setMapFile(null);
    setMapErr('');
  };

  const confirmMapped = async () => {
    if (!mapFile || !mValue || !mLabel || !pvCols) return;
    if (!pvCols.includes(mValue) || !pvCols.includes(mLabel)) {
      setMapErr('数值列/标签列必须来自文件列');
      return;
    }
    setMapBusy(true);
    setMapErr('');
    try {
      const r = await mappedDataset(mapFile, {
        metric_key: mKey,
        label_column: mLabel,
        value_column: mValue,
        dimension_column: mDim || undefined,
      });
      setMapBusy(false);
      onPick({ name: mapFile.name, kind: 'upload', at: nowHHmm(), rows: r?.rows ?? 0, fields: 36 });
    } catch (err) {
      setMapBusy(false);
      setMapErr(err instanceof Error ? err.message : String(err));
    }
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
      ) : pvCols && mapFile ? (
        <div className="up-map">
          <div className="map-head">
            <b>{mapFile.name}</b> · 列映射确认（口径）
          </div>
          <div className="map-grid">
            <label className="map-field"><span>指标口径 metric_key</span>
              <select value={mKey} onChange={(e) => setMKey(e.target.value)}>
                {METRIC_KEYS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </label>
            <label className="map-field"><span>数值列 value</span>
              <select value={mValue} onChange={(e) => setMValue(e.target.value)}>
                {pvCols.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="map-field"><span>标签列 label</span>
              <select value={mLabel} onChange={(e) => setMLabel(e.target.value)}>
                {pvCols.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="map-field"><span>维度列 dimension（可选）</span>
              <select value={mDim} onChange={(e) => setMDim(e.target.value)}>
                <option value="">（无）</option>
                {pvCols.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          </div>
          {mapErr && <div className="map-err">{mapErr}</div>}
          <div className="map-actions">
            <button className="btn primary" disabled={mapBusy} onClick={confirmMapped}>
              {mapBusy ? '入库中…' : '确认入库并生成业务脉搏'}
            </button>
            <button className="btn" onClick={closeMap}>取消</button>
          </div>
          <div className="map-hint">将把 {mLabel || '?'} 作为标签、{mValue || '?'} 作为数值写入「{mKey}」指标口径。预览列：{pvCols.join(' / ')}</div>
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
