## Why

V3-T1..T4 已实现（抽象层/缓存/LLM/前端入口）。T5 把验收固化：模板金样本回归 + 判定不被污染断言成门禁，产出验收清单供人工审查，并同步文档与路线图。

## What Changes

- 新增 `backend/tests/golden_baseline.json`（V2/V3-template 基线快照：pulse + 9 条洞察的判定字段与 semantics）。
- 新增 `backend/tests/golden_check.py`：出厂重置 → 模板模式快照 → 与基线逐条比对（自动忽略 reasonSource/generatedAt 展示字段）。
- `tests/run_all.py` 加入 golden_check（门禁 5 段）。
- 新增 `docs/V3_ACCEPTANCE_CHECKLIST.md`：§3A.4 验收/审查清单（含各自动检查对应的命令与人工核对项）。
- 路线图 V3 状态更新为"已实现、待人工验收"。

## Capabilities

<!-- 测试/文档/门禁，skip_specs: true -->

## Impact

- 后端：`tests/golden_check.py` + `golden_baseline.json`、`tests/run_all.py`。
- 文档：`docs/V3_ACCEPTANCE_CHECKLIST.md`、dev-log、路线图、`docs/开发问题与经验.md`。
- 验证：`run_all` 全绿（含 golden）。
