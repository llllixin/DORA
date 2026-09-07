## 1. Case 3/4 升级路径 E2E

- [x] 1.1 `tests/watch_check.py` 第 4 节（HTTP）：sample 出厂 → POST /watch 创建 east_orders 委托 → GET 详情断言存在 change 事件（Case 3）→ 上传 east_breach.csv → GET 委托详情存在 escalate 事件且 engine_insight==e2、GET /insights problem 含 e2（Case 4）→ DELETE 委托 + sample 还原；验证：`python3 -m tests.watch_check` ALL GREEN（第 1–4 节）
- [x] 1.2 回归：`python3 -m tests.run_all` **6 段 ALL GREEN**；golden 9 不变

## 2. 验收收尾

- [x] 2.1 新建 `docs/V4_ACCEPTANCE_CHECKLIST.md`（A 自动 / B 边界审查记录 / C 人工核对 / D 收尾 + Sign-off 表；C 留待用户在界面确认）
- [x] 2.2 dev-log「迭代 26」+ 路线图 §3B V4-T5 标记、版本速览 V4 → 🔶 已实现、待人工验收 + archive（【测试证据】+【反思】）

【测试证据】watch_check（第 1–4 节）→ "watch_check OK（…第 4 节 升级 E2E 全绿）"；run_all → ALL GREEN（6 段，golden 9 不变，e2e 4 case 通过）；npm run build 通过。
【反思】Case 3/4 用 HTTP+上传把"委托→数据恶化→升级回脉搏"整链固化为门禁，比单测更能防回归；断言"存在性"而非总数，降低对 seed 数据形状的脆弱性；验收清单沿用 V3 结构（A/B 自动证据 + C 人工核对 + Sign-off），C 段必须用户本人在运行界面确认后再填 Sign-off（勿代填）。
