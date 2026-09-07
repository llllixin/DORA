## 1. 前端死代码

- [x] 1.1 删除 `doraApi.ts` 的 `liveSet/isApiLive` 及赋值，验证：`grep` 无残留 + `npm run build`

## 2. 后端等价重构

- [x] 2.1 `seed.rule_items()` 由 `engine.RULE_DEFAULTS` 派生（单一默认源），验证：`python -m app.seed` 后 rule_config=6 且值不变
- [x] 2.2 `engine.py` docstring 更新为现状（Repository+规则配置化），验证：阅读无过期表述
- [x] 2.3 证据行 DB 化：新增 `_evidence_rows_from_repo`，`engine_evidence` 不再用 `dataset.rows_for_evidence`，验证：`python3 -m tests.engine_check` + evidence 各 id 冒烟与改动前等价

## 3. 回归与文档

- [x] 3.1 `python3 -m tests.run_all` 全绿 + `npm run build` + `python3 /tmp/dora_smoke.py` 绿
- [x] 3.2 文档：dev-log 迭代、路线图"收尾杂项"勾选、`docs/开发问题与经验.md` 记 D020（清理决策）
