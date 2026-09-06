import { useEffect } from 'react';
import type { DataSource } from '../../types';
import { DataSourcePicker } from './DataSourcePicker';
import { Tag } from '../ui/Tag';

export function DataSourceModal({
  current,
  onClose,
  onApply,
  onClear,
}: {
  current: DataSource;
  onClose: () => void;
  onApply: (ds: DataSource) => void;
  onClear: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="dsm-mask" onMouseDown={onClose}>
      <div className="dsm-panel" role="dialog" aria-modal="true" aria-labelledby="dsTitle" onMouseDown={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="关闭">×</button>
        <div className="eyebrow">DATA SOURCE · UPDATE</div>
        <h2 id="dsTitle">更新数据</h2>
        <p className="sub">重新上传、换回样例或清除数据。数据更新后 Dora 会重新执行「理解 → 口径 → 判断 → 洞察」，变化会回到业务脉搏。</p>

        <div className="dsm-current">
          <span className="muted">当前数据</span>
          <b>{current.name}</b>
          <Tag tone={current.kind === 'sample' ? 'ai' : 'blue'}>{current.kind === 'sample' ? '内置样例' : '用户上传'}</Tag>
          <span className="muted">· {current.at} 更新 · {current.rows} 行 · {current.fields} 字段</span>
        </div>

        <DataSourcePicker onPick={onApply} />

        <div className="dsm-danger">
          <button className="btn" onClick={onClear}>🗑 清除数据，回到首次引导</button>
        </div>
      </div>
    </div>
  );
}
