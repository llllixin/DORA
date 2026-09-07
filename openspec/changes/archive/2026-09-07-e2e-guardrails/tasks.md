## 1. 引擎自动升级行为（e2）

- [x] 1.1 `evaluate_signals`：华东跌破阈值 → `sig-east-breach`(e2/problem)，未跌破仍 c1(change)，验证：`python3 -c` 用 Repository 替换 east 为跌破数据后 problems 含 e2 且 change 不含 c1；还原后恢复
- [x] 1.2 `INSIGHT_TEMPLATES`/`_semantics`/`EVIDENCE_META` 覆盖 e2，验证：`/api/insights/e2` 返回 route=action 且带 semantics

## 2. E2E 门禁脚本

- [x] 2.1 `tests/e2e_api_check.py`：四用例（Problem→Evidence→Action；Opportunity→Evidence/execute；Change→Watch 路由；Watch→跌破→Problem）自重置可重复跑，验证：`python3 -m tests.e2e_api_check`
- [x] 2.2 `tests/run_all.py`：串联 engine_check + ingest_check + e2e_api_check，验证：`python3 -m tests.run_all` 全绿

## 3. 约定与文档

- [x] 3.1 `.clinerules/project-conventions.md` 测试门禁节加入 `python3 -m tests.run_all`；`backend/README.md` 验证节同步
- [x] 3.2 `docs/开发过程记录.md` 追加迭代；`docs/版本路线图.md` 勾选 C5；`docs/开发问题与经验.md` 记 D019（跌破自动升级 + run_all 门禁取舍）
