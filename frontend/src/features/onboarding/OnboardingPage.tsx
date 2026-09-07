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
          <Tag tone="ai">数据源</Tag>
          <span>后端在线：上传按「引擎规范格式」真实解析入库、样例由服务端提供；离线或无后端时回退本地演示，行为与之前一致。</span>
        </div>
      </div>
    </div>
  );
}
