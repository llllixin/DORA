import type { DataSource } from '../../types';
import { DataSourcePicker } from '../../components/dora/DataSourcePicker';
import { Tag } from '../../components/ui/Tag';

const FLOW: [string, string][] = [
  ['上传 / 解析', '导入经营数据文件'],
  ['建立口径', '指标口径与范围确认'],
  ['生成业务脉搏', 'Dora 主动发现值得关注的'],
];

export function OnboardingPage({ onReady }: { onReady: (ds: DataSource) => void }) {
  return (
    <div className="boot">
      <div className="boot-card">
        <div className="boot-head">
          <div className="boot-logo">D</div>
          <div>
            <div className="eyebrow">DORA · COLD START</div>
            <h1>欢迎使用 Dora，先把经营数据带进来</h1>
            <p className="sub">
              目前还没有任何业务数据。数据就绪后，Dora 会自动完成「理解数据 → 建立经营口径 →
              判断什么值得关注 → 形成问题 / 机会 / 变化」，并生成今天的业务脉搏。
            </p>
          </div>
        </div>

        <div className="boot-flow">
          {FLOW.map(([t, d], i) => (
            <span key={t}>
              <b>STEP {i + 1}</b>
              {t} <em className="muted">· {d}</em>
            </span>
          ))}
        </div>

        <DataSourcePicker onPick={onReady} />

        <div className="boot-note">
          <Tag tone="ai">演示模式</Tag>
          <span>上传任意文件后，本演示会以内置「门店经营」样例运行完整流程；真实文件解析将随后端上线接入。</span>
        </div>
      </div>
    </div>
  );
}
