## 1. 证据源与引擎指向

- [x] 1.1 `dataset.rows_for_evidence()` 新增 `new_sku` kind（用 `NEW_SKU_WEEKS/NEW_SKU_VALUES` 生成周/销量/增量行），验证：`python3 -c "from app.engine import dataset as d; r=d.rows_for_evidence('new_sku'); assert r and '新品销量' in r[0]"`（若首行列名设计不同，断言改为检查首个数据单元格含销量数值）
- [x] 1.2 引擎 `sig-new-sku` 的 `evidence_kind` 改为 `new_sku`；`EVIDENCE_META` 增加 `new_sku` 条目，验证：`python3 -c "from app.engine.engine import run_engine; c=next(i for i in run_engine()['insights'] if i['id']=='c3'); assert c['evidence']['kind']=='new_sku'"`

## 2. 自检与端点回归

- [x] 2.1 `engine_check` 增加 c3 证据断言（kind=new_sku 且首行含新品销量），验证：`cd backend && python3 -m tests.engine_check`
- [x] 2.2 端点回归：`curl /api/evidence/c3` rawRows 首行为新品销量数据，验证：curl 输出非 margin 行

## 3. 文档与看板

- [x] 3.1 `docs/开发过程记录.md` 追加迭代条目；`docs/版本路线图.md` 备注 c3 已修并将审计余项（死代码/阈值双源/过期 docstring）列入"收尾杂项"
- [x] 3.2 `docs/开发问题与经验.md` 新增 P 系列条目（c3 证据占位错配于审查中发现）
