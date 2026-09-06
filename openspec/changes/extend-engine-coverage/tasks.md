## 1. 引擎数据源扩展（dataset.py）

- [ ] 1.1 在 `backend/app/engine/dataset.py` 增加数据更新事件元数据（更新时间、新增行数 327、受影响指标清单），验证：`python3 -c "from app.engine import dataset as d; assert d.DS_UPDATE['rows_added']>0"`
- [ ] 1.2 增加华东高客单门店集群源数据（Top 高客单门店区域分布、华东占比、区域代表客单价/共性商品占比），验证：`python3 -c "from app.engine import dataset as d; assert len(d.STORE_CLUSTER['top_stores'])>0"`
- [ ] 1.3 扩展 `rows_for_evidence()` 支持 c2（更新写入行）与 o2（门店集群行）两类 kind，验证：`python3 -c "from app.engine import dataset as d; assert d.rows_for_evidence('data_event') and d.rows_for_evidence('store_cluster')"`

## 2. 引擎规则与洞察（engine.py）

- [ ] 2.1 `compute_snapshot()` 增加 `data_event` 与 `store_cluster` 两个指标块（占比较值由源数据计算），验证：`python3 -c "from app.engine.engine import compute_snapshot; s=compute_snapshot(); assert 'data_event' in s and 'store_cluster' in s"`
- [ ] 2.2 `evaluate_signals()` 增加两条规则：数据更新事件 → `sig-data-event`(c2/change)；华东占比 ≥ 机会阈值 → `sig-store-cluster`(o2/opportunity)，验证：`python3 -c "from app.engine.engine import run_engine; ids=[i['id'] for i in run_engine()['insights']]; assert 'c2' in ids and 'o2' in ids"`
- [ ] 2.3 `INSIGHT_TEMPLATES` 增加 c2/o2 条目，且 `_semantics()` 为 c2/o2 生成 causeA/causeB/next，验证：断言 `run_engine()['insights']` 中 c2/o2 均带非空 `semantics`
- [ ] 2.4 证据体系补齐：`EVIDENCE_META` 覆盖 c2/o2 的 kind，`engine_evidence()` 对 c2/o2 返回非占位 rawRows，验证：`curl http://localhost:8000/api/evidence/c2` 与 `/api/evidence/o2` 返回 200 且 rows 非空

## 3. 引擎自检与端点回归

- [ ] 3.1 扩展 `backend/tests/engine_check.py`：断言 c2、o2 存在于对应 type 列表、pulse 计数 opportunities==2 / changes==4 / watching==4，验证：`cd backend && python3 -m tests.engine_check`
- [ ] 3.2 端点回归：`/api/insights?type=change|opportunity` 含 c2/o2；`/api/insights/{c2|o2}` 与 `/api/evidence/{c2|o2}` 均由引擎产出（含 trigger/factors/semantics），验证：`curl --noproxy '*' -s http://localhost:5173/api/insights?type=opportunity | python3 -m json.tool` 含 o2 且无静态兜底标记
- [ ] 3.3 前端零改动确认：`cd frontend && npm run build` 通过，且 5173 页面 Pulse 计数 / Tab 数字自动跟随新计数

## 4. 文档与方向看板同步

- [ ] 4.1 `docs/开发过程记录.md` 追加本次迭代条目（时间/目标/文件/验证/边界）
- [ ] 4.2 `docs/版本路线图.md` 勾选 C1，并记录 c2/o2 已由引擎覆盖（残留待办仅剩证据深挖与 C2/C3…）
