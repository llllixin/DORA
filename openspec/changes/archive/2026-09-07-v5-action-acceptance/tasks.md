## 1. 闭环 E2E

- [x] 1.1 `tests/action_check.py` 第 4 节（HTTP）：Case4+1（watch→跌破→e2→建档 created→全 done→resolved note 入 archive→list 含 e2 resolved）＋ Case2（o1 推进→waiting→verify continue→running）；清理 e2+sample；`python3 -m tests.action_check` ALL GREEN（第 1–4 节）
- [x] 1.2 回归：`python3 -m tests.run_all` **7 段 ALL GREEN**；golden 9 不变

## 2. 验收收尾

- [x] 2.1 新建 `docs/V5_ACCEPTANCE_CHECKLIST.md`（A 自动/B 边界/C 人工核对/D 收尾 + Sign-off；C 待用户在界面确认）
- [x] 2.2 dev-log「迭代 33」+ 路线图 §3C V5-T5 标记、版本速览 V5 → 🔶 已实现待人工验收 + archive（【测试证据】+【反思】）

【测试证据】action_check（第 1–4 节）→ "action_check OK（…闭环 E2E 全绿）"：Case4+1（watch→跌破→引擎 e2→建档 created→全 done→verify resolved（note 入 archive）→再 verify 400）；Case2（o1 幂等返回既有→推进全 done→verify continue→running）；自清 e2/watch + sample 还原。run_all → ALL GREEN（7 段, golden 9 不变）。
【反思】E2E 断言"存在性+终态"（中间细节由第 3 节服务层覆盖）；HTTP 预期 4xx 用 urllib HTTPError 捕获断言，避免未捕获崩溃；sample 不重置 action 档案（seed 只 upsert 5 例）→ 测试自清自定义档案，o1 等 seed 由 sample 复位；watch→escalate 不自动建档、引擎 problem 才可建档的红线在端到端链路得到验证。
