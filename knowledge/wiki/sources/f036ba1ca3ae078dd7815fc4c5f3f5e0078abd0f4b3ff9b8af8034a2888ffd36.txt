import type { EngineChart as Chart } from '../../types';

/** 只负责坐标映射；业务计算和阈值均来自后端。 */
export function EngineChart({ data }: { data: Chart | null | undefined }) {
  if (!data || !data.labels.length || !data.series.length) return <p className="note">暂无可绘制的指标序列；请查看证据记录。</p>;
  const numbers = data.series.flatMap(s => s.values).filter((v): v is number => v !== null && Number.isFinite(v));
  if (!numbers.length) return <p className="note">暂无有效数值。</p>;
  const values = [...numbers, ...(data.threshold ? [data.threshold.value] : []), ...(data.kind === 'bar' ? [0] : [])];
  const low = Math.min(...values), high = Math.max(...values), pad = (high - low || 1) * .15;
  const min = low - pad, max = high + pad;
  const x = (i: number) => 70 + (data.labels.length === 1 ? 320 : i * 640 / (data.labels.length - 1));
  const y = (value: number) => 245 - (value - min) / (max - min) * 210;
  return <div className="chart-area" data-chart-source="engine">
    <svg viewBox="0 0 780 295" role="img" aria-label="当前指标数据图表">
      {Array.from({ length: 5 }, (_, i) => {
        const value = min + (max - min) * i / 4;
        return <g key={i}><line x1="60" x2="735" y1={y(value)} y2={y(value)} stroke="#e7eaf0" /><text x="52" y={y(value) + 4} textAnchor="end" fontSize="11">{Number(value.toFixed(2))}{data.unit}</text></g>;
      })}
      {data.threshold && <g><line x1="60" x2="735" y1={y(data.threshold.value)} y2={y(data.threshold.value)} stroke={data.threshold.color} strokeDasharray="6 4"/><text x="735" y={y(data.threshold.value) - 6} textAnchor="end" fontSize="12">{data.threshold.label} {data.threshold.value}{data.unit}</text></g>}
      {data.series.map(series => <g key={series.name}>
        {series.values.map((value, i) => {
          if (value === null || !Number.isFinite(value)) return null;
          const previous = series.values[i - 1];
          return <g key={i} data-value={value}>
            {data.kind === 'bar' ? <rect x={x(i)-12} y={Math.min(y(0), y(value))} width="24" height={Math.abs(y(value)-y(0))} fill={series.color} /> : <>
              {i > 0 && previous !== null && Number.isFinite(previous) && <line x1={x(i-1)} y1={y(previous)} x2={x(i)} y2={y(value)} stroke={series.color} strokeWidth="2"/>}
              <circle cx={x(i)} cy={y(value)} r="4" fill={series.color}/>
            </>}
            <title>{data.labels[i]} · {series.name}：{value}{data.unit}</title>
          </g>;
        })}
      </g>)}
      {data.labels.map((label, i) => <text key={label} x={x(i)} y="278" textAnchor="middle" fontSize="10">{label}</text>)}
    </svg>
    <div className="muted">{data.series.map(s => s.name).join(' / ')} · 数据来自当前指标；缺测处不连线</div>
  </div>;
}
