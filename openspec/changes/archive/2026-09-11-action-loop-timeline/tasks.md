## 1. 后端：步骤负责专家（列 + 端点 + 状态机边界）

- [x] 1.1 `models.py` 的 `ActionStep` 增 `experts = Column(JSON, nullable=False, default=list)`；`db.py` 增加幂等补列清单（`ALTER TABLE action_step ADD COLUMN IF NOT EXISTS experts JSON NOT NULL DEFAULT '[]'`，沿用 `_TEXT_ALTERS` 同款 PG 方言守卫 + try/except 宽容）。验证：重启后端后 `cd backend && python3 -c "from app.repository import Repository; s=Repository().get_action_case('p1')['steps'][0]; print(s.get('experts'))"` 输出 `[]`（旧行不报错、不伪造专家）
- [x] 1.2 `repository.py`：`_action_step_dict` 增 `experts` 字段；新增 `set_action_step_experts(case_id, seq, experts)`（去重保序、写 `case.updated_at`、step 不存在返回 `None`）。验证：`python3 -c` 对 `o-test` 式临时档案设置 `["财务专家","财务专家","销售专家"]` → 读回 `["财务专家","销售专家"]`（去重保序）；对不存在 seq 返回 `None`
- [x] 1.3 `action/flow.py` 新增 `set_step_experts(repo, case_id, seq, experts)`：复用 `_get`（resolved 冻结）+ `_step`（seq 存在性），非法一律 `ActionFlowError`。验证：`python3 -m tests.action_check` 中 1.5 的冻结/404 断言通过
- [x] 1.4 `schemas.py` 增 `StepExpertsRequest{experts: list[str]}`；`routers.py` 增 `POST /action/cases/{case_id}/steps/{seq}/experts`（空名/非列表/超 8 个 → 400，case/step 不存在 → 404，成功 → `{"ok": True, "case": <detail>}`）。验证：`curl -s -X POST localhost:8000/api/action/cases/p1/steps/1/experts -H 'Content-Type: application/json' -d '{"experts":["经营分析专家"]}'` 返回 `ok=true` 且 steps[1].experts 命中；9 个专家与 `[""]` 均返回 400
- [x] 1.5 `tests/action_check.py` 新增一节「步骤负责专家」：往返一致 + 重放幂等 + 去重 + 上限 4xx + resolved 冻结 4xx + 不存在 seq 4xx + 断言不写库。验证：`cd backend && python3 -m tests.action_check` 全绿（贴 PASS 计数）

## 2. 前端：类型与 API 契约

- [x] 2.1 `types.ts` 的 `CaseStep` 增可选字段 `experts?: string[]`（向后兼容：缺失按空态）。验证：`cd frontend && npm run build` 通过；`grep -n 'experts?: string\\[\\]' src/types.ts` 命中 → 实测：`grep -n 'experts?: string' frontend/src/types.ts` → `132:  experts?: string[];`；`npm run build` → `✓ 47 modules transformed / ✓ built in 698ms`
- [x] 2.2 `services/doraApi.ts` 增 `setStepExperts(caseId, seq, experts)`（POST 到新端点；`mock`/离线模式返回不可用标记而非静默成功）。验证：`npm run build` 通过；离线（`VITE_API_MODE=mock`）触发时界面提示「离线演示：专家分配需后端在线」 → 实测：`grep -n setStepExperts frontend/src/services/doraApi.ts` → `380:export async function setStepExperts(`；`npm run build` ✅；离线分支用 CDP `Fetch.failRequest` 拦截 `/api/action/cases*` 等价复现 → 4/4 `[PASS]`（pill 全为「离线演示」+ 文案「步骤执行 / 专家分配需后端在线」+ 不渲染时间线/专家 chip）

## 3. 前端：档案列表对齐洞察列表（含经验移出）

- [x] 3.1 重写抽屉列表行：`Tag(kind) + 状态 pill + code` → 标题 → 来源 → `.list-status` 状态行（复用 `.insight-item` 同款行容器与 `.list-status` pill，`action` 色调=执行中、`none` 色调=已归档）；排序「执行中在前」；列表头显示「执行中 N · 已归档 M」。验证：CDP 脚本断言 5 行（4 执行中 + 1 已归档）、首个 resolved 行排在末尾、计数文本命中 → 实测：CDP `/tmp/dora_action_verify.mjs` → 6 行（5 执行中 + 1 已归档临时档案）、pill `["执行中"×5,"已归档"]`、已归档行在末尾、列表头 `"执行中 5 · 已归档 1"` 全 `[PASS]`
- [x] 3.2 删除抽屉最下方「🧠 学习经验」块与 `listLessons` 拉取/`lessons`/`showLessons` 状态；`archiveLesson` 保留，成功提示改为「✓ 已沉淀到知识库 → 经验（查看知识库）」。验证：`grep -n 'listLessons\\|showLessons' frontend/src/features/action/ActionPage.tsx` 无输出；CDP 断言 Action 页不含「学习经验」文本；沉淀后 notice 含「知识库」 → 实测：grep → `NONE (OK)`；CDP → 「Action 页不再承载经验块（无「学习经验」）」`[PASS]`、沉淀后 toast `"✓ 已沉淀到知识库 → 经验（可在「知识库」查看）"` `[PASS]`
- [x] 3.3 离线演示分支：状态 pill 显示「离线演示」而非状态值，并在小字中说明「步骤执行 / 专家分配需后端在线」。验证：`VITE_API_MODE=mock` 下 CDP 断言文案命中且不出现伪造的「执行中/已归档」 → 实测：CDP `/tmp/dora_action_offline.mjs`（拦截 `/api/action/cases*`）→ 4/4 `[PASS]`：pill 全为「离线演示」、文案命中、正文不含「执行中 /已归档」、无 `.tl` / `.expert-chip.user`

## 4. 前端：机会/问题板块 → 步骤时间线

- [x] 4.1 步骤区改时间线（复用既有 `.timeline/.tl/.tldot/.tl-body/.tl-head`）：节点色按状态（done/active/待办/受阻）、连接线由既有伪元素提供；`openSteps: Record<number, boolean>` 默认展开当前步（首个 `in_progress`；无则首个非 done；否则末步），换档案重置。验证：CDP 断言节点数 = 步骤数、默认展开态命中当前步、点击某步「收起」只影响该步 → 实测：CDP → 节点 5 = 步骤 5、默认仅展开 `tl active` 的「进行中 当前行动 · 提炼高客单动作 #2」、展开另一步后 `open=2`、对该步「收起」后 `open=1` 全 `[PASS]`
- [x] 4.2 推进控件（开始 / 完成 / 受阻）与展开控件移入 `.tl-actions`（步骤行右侧，与 `.step-trace` 同区），折叠态仍可见。验证：CDP 用 `getBoundingClientRect()` 断言右侧按钮组 `left` > 步骤标题 `left` 且同一行（`top` 差 < 24px） → 实测：CDP → `h4l=630 / al=1459`（右置）、`h4t=433 / at=428`（差 5px < 24）、按钮 `["完成","受阻","收起"]`、每节点（含折叠态）都有 `.tl-actions` `[PASS]`
- [x] 4.3 每步「负责专家团」：展开态显示该步 `experts` chips（`.expert-chip.user`），空态呈现「未指定负责专家」；候选池 = `capabilities['专家团']` ∪ 档案级 `orchestration.experts`（后者标「系统建议」）；添加/移除调用 `setStepExperts`（整体设置），失败仅提示、不做乐观更新。验证：CDP 添加一位专家 → 重新加载档案该 chip 仍在；`curl` 单查该档案 steps[seq].experts 与界面一致 → 实测：CDP → 添加后 chip `"👤 经营分析专家 用户指定 ×"` = 接口 `steps[2].experts=["经营分析专家"]`、移除后空态「未指定负责专家」+ 接口 `[]` 全 `[PASS]`；curl `POST /api/action/cases/p1/steps/1/experts {"experts":["经营分析专家"]}` → `ok=True | steps[1].experts=['经营分析专家'] | HTTP200`
- [x] 4.4 每步数据定位：展开态显示 `.step-evidence`（`step.evidence`，空则「暂无定位说明」）+ `.step-trace`「定位数据 →」调用既有 `onTrace(detail.id)`。验证：CDP 点击后证据链抽屉打开且该步定位串文本命中；对无 evidence 的步骤断言空态文案 → 实测：CDP → 界面 `门店经营动作对比` = 接口 `evidence`；点击后 `aside.drawer.open` 标题 `数据证据链 · 高客单门店形成集群`；resolved 档案空 evidence 显示 `暂无定位说明` 全 `[PASS]`
- [x] 4.5 新增 CSS 仅限带前缀的 `.tl-actions` / `.tl-more`（其余复用既有死 CSS）；确认类名无碰撞。验证：`grep -n '\\.tl-actions\\|\\.tl-more' frontend/src/styles.css` 命中；`grep -rn 'className="facts"\\|className="items"' frontend/src` 无新增（P013 防碰撞）；`npm run build` 通过 → 实测：`75:.tl-actions{...justify-content:flex-end...}` / `76:.tl-more{margin-top:6px}`；`className="facts"|"items"` → `NONE (OK)`；`npm run build` ✅

## 5. 前端：知识库处理过程可折叠

- [x] 5.1 `KnowledgePage.tsx` 条目「处理过程」改为默认收起、点击展开（移除只弹 notice 的「查看处理过程」假按钮），展开态保留 `content` 全文。验证：CDP 断言初始不可见 → 点击后文本命中；`grep -n '查看处理过程' frontend/src/features/knowledge/KnowledgePage.tsx` 无输出 → 实测：grep → `NONE (OK)`；CDP → 经验类目条目按钮 `"处理过程 ▸"` 且 `preVisible=false` → 点击后 `pre` 可见且文本 `[2026-09-11T08:57:27+00:00] re…`；知识库正文不含「查看处理过程」全 `[PASS]`

## 6. 门禁、文档与归档

- [x] 6.1 后端门禁：`cd backend && python3 -m tests.action_check`（新节）+ `python3 -m tests.run_all` 全绿（贴输出；golden 基线不变） → 实测：`action_check OK（第 1–7 节 + 生命周期不变式：…/步骤负责专家/无孤儿 全绿）`、`[experts] 每步负责专家：往返/去重/幂等/整体替换/上限/冻结/404 全绿`、`[experts] HTTP 200/400/404/422 断言已执行（后端在线）`；`run_all: ALL GREEN`（8 段，exit=0，golden 9 不变）
- [x] 6.2 前端门禁：`cd frontend && npm run build` 通过；文档一致性 `cd backend && python3 -m tests.check_docs` ALL GREEN → 实测：`✓ 47 modules transformed / ✓ built in 698ms`；`check_docs` 于 6.4 文档同步后跑（见归档提交）
- [x] 6.3 CDP 端到端用例（后端在线）：列表形态与状态 pill → 时间线展开收起 → 控件右置 → 每步添加专家（落库复核）→ 每步定位数据 → Action 页无经验块 + 知识库经验可展开 → 实测：CDP `/tmp/dora_action_verify.mjs` → **28/28 PASS**（含 resolved 档案冻结/空定位说明/沉淀 toast）+ 离线分支 `/tmp/dora_action_offline.mjs` → **4/4 PASS**；截图 `/tmp/dora_shots/{action_timeline,knowledge_fold,action_offline}.png`
- [x] 6.4 文档同步：`docs/持续优化路线.md` 登记/勾选该项（含 change id）、`docs/版本路线图.md`「当前打开的工作」、`docs/开发过程记录.md` 追加「迭代 44」、`docs/开发问题与经验.md` 补 P/D（含 propose 阶段已记决策的 apply 期修订） → 实测：`持续优化路线.md` §2 该项勾 [x] 并附验证/归档路径；`版本路线图.md` 迭代 44 入「已归档」列表 + 移出「当前打开的工作」；`开发过程记录.md` 追加「迭代 44」（目标/交付/测试证据/反思）；`开发问题与经验.md` 新增 **P014**（门禁前置状态）+ D041 状态改「已生效」并补 4 条 apply 期修订/补充
- [x] 6.5 归档：`openspec archive action-loop-timeline`（快照写入 `openspec/specs/business-action/spec.md`：需求来源表 + 1 条 ADDED + 3 条 MODIFIED 全文替换），归档后 `openspec validate --specs` 全绿 + 提交信息含【测试证据】+【反思】 → 实测：spec 先经 agent 合并同步（需求来源表补 1 行「行动步骤可指定负责专家团（per-step 持久化）」+ 1 ADDED + 3 MODIFIED 全文替换）→ `openspec validate --specs` → `Totals: 7 passed, 0 failed`；`openspec archive action-loop-timeline --skip-specs -y` → `Change 'action-loop-timeline' archived as '2026-09-11-action-loop-timeline'`（`--skip-specs` 因 delta 已同步、CLI 再应用会被拒）；同时序任务「待办/方向」文档指针未受影响
