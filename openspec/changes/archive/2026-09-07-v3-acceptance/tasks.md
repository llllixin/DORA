## 1. 金样本回归

- [x] 1.1 生成 `tests/golden_baseline.json`（seed 后模板快照：pulse + 9 条洞察判定字段与 semantics），验证：文件存在且校验结构
- [x] 1.2 新增 `tests/golden_check.py`（支持 `--write` 重生成基线），验证：`python3 -m tests.golden_check` OK；篡改语义应失败（回归护栏）
- [x] 1.3 `run_all` 加入 golden_check，验证：`python3 -m tests.run_all` ALL GREEN（5 段）

## 2. 验收清单与收尾

- [x] 2.1 新增 `docs/V3_ACCEPTANCE_CHECKLIST.md`（§3A.4 映射：自动项命令 + 人工核对项 + sign-off）
- [x] 2.2 dev-log 迭代 + 路线图 V3-T5 标记 + V3 状态=已实现待验收 + `docs/开发问题与经验.md` D027
