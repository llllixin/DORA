## 1. 建档引擎

- [x] 1.1 `app/action/__init__.py` + `builder.py`：`create_case_from_insight(repo, insight) -> {case, created}`；判定校验（type∈{problem,opportunity} 且 id 在当前 run_engine 结果集）；幂等（已有→created=False）；4 步模板 + code 生成（PRB-/UPC- + sha1[:4]）；默认编排；验证：见 1.2
- [x] 1.2 `tests/action_check.py` 第 2 节「建档引擎」：e2（注入跌破）建档 created=True/kind problem/code 前缀 PRB-/4 步首 done → 重复建档 created=False；change c1 拒绝；伪造 id 拒绝；p1（已有静态 seed）返回既有 created=False；清理还原；`python3 -m tests.action_check` ALL GREEN（第 1+2 节）

## 2. 收尾

- [x] 2.1 回归：`python3 -m tests.run_all` **7 段 ALL GREEN**；golden 9 不变
- [x] 2.2 dev-log「迭代 29」+ 路线图 §3C V5-T2 标记 + archive（【测试证据】+【反思】）

【测试证据】action_check（第 1+2 节）→ "action_check OK（…第 2 节 建档引擎 全绿）"：e2（注入跌破）created=True / kind=problem / code PRB-前缀 / 4 步首 done；重复建档 created=False；change c3 拒绝；伪造 w-fake 拒绝；p1（静态 seed）返回既有 created=False；清理还原。run_all → ALL GREEN（7 段, golden 9 不变）。
【反思】"引擎判定集内才可建档"的实现=建档案时跑一次 run_engine 快照校验（type∈{problem,opportunity} 且 id 命中）——把 D031 红线落到执行路径而非文档；幂等双保险（builder 先查档案，repo.create 抛同 id 兜底）；新档案 code 确定性（PRB-/UPC- + sha1[:4]），静态 seed code 不受影响。
