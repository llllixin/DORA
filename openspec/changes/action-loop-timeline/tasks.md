## 1. 后端：步骤负责专家（列 + 端点 + 状态机边界）

- [ ] 1.1 `models.py` 的 `ActionStep` 增 `experts = Column(JSON, nullable=False, default=list)`；`db.py` 增加幂等补列清单（`ALTER TABLE action_step ADD COLUMN IF NOT EXISTS experts JSON NOT NULL DEFAULT '[]'`，沿用 `_TEXT_ALTERS` 同款 PG 方言守卫 + try/except 宽容）。验证：重启后端后 `cd backend && python3 -c "from app.repository import Repository; s=Repository().get_action_case('p1')['steps'][0]; print(s.get('experts'))"` 输出 `[]`（旧行不报错、不伪造专家）
- [ ] 1.2 `repository.py`：`_action_step_dict` 增 `experts` 字段；新增 `set_action_step_experts(case_id, seq, experts)`（去重保序、写 `case.updated_at`、step 不存在返回 `None`）。验证：`python3 -c` 对 `o-test` 式临时档案设置 `["财务专家","财务专家","销售专家"]` → 读回 `["财务专家","销售专家"]`（去重保序）；对不存在 seq 返回 `None`
- [ ] 1.3 `action/flow.py` 新增 `set_step_experts(repo, case_id, seq, experts)`：复用 `_get`（resolved 冻结）+ `_step`（seq 存在性），非法一律 `ActionFlowError`。验证：`python3 -m tests.action_check` 中 1.5 的冻结/404 断言通过
- [ ] 1.4 `schemas.py` 增 `StepExpertsRequest{experts: list[str]}`；`routers.py` 增 `POST /action/cases/{case_id}/steps/{seq}/experts`（空名/非列表/超 8 个 → 400，case/step 不存在 → 404，成功 → `{"ok": True, "case": <detail>}`）。验证：`curl -s -X POST localhost:8000/api/action/cases/p1/steps/1/experts -H 'Content-Type: application/json' -d '{"experts":["经营分析专家"]}'` 返回 `ok=true` 且 steps[1].experts 命中；9 个专家与 `[""]` 均返回 400
- [ ] 1.5 `tests/action_check.py` 新增一节「步骤负责专家」：往返一致 + 重放幂等 + 去重 + 上限 4xx + resolved 冻结 4xx + 不存在 seq 4xx + 断言不写库。验证：`cd backend && python3 -m tests.action_check` 全绿（贴 PASS 计数）

## 2. 前端：类型与 API 契约

- [ ] 2.1 `types.ts` 的 `CaseStep` 增可选字段 `experts?: string[]`（向后兼容：缺失按空态）。验证：`cd frontend && npm run build` 通过；`grep -n 'experts?: string\\[\\]' src/types.ts` 命中
- [ ] 2.2 `services/doraApi.ts` 增 `setStepExperts(caseId, seq, experts)`（POST 到新端点；`mock`/离线模式返回不可用标记而非静默成功）。验证：`npm run build` 通过；离线（`VITE_API_MODE=mock`）触发时界面提示「离线演示：专家分配需后端在线」

## 3. 前端：档案列表对齐洞察列表（含经验移出）

- [ ] 3.1 重写抽屉列表行：`Tag(kind) + 状态 pill + code` → 标题 → 来源 → `.list-status` 状态行（复用 `.insight-item` 同款行容器与 `.list-status` pill，`action` 色调=执行中、`none` 色调=已归档）；排序「执行中在前」；列表头显示「执行中 N · 已归档 M」。验证：CDP 脚本断言 5 行（4 执行中 + 1 已归档）、首个 resolved 行排在末尾、计数文本命中
- [ ] 3.2 删除抽屉最下方「🧠 学习经验」块与 `listLessons` 拉取/`lessons`/`showLessons` 状态；`archiveLesson` 保留，成功提示改为「✓ 已沉淀到知识库 → 经验（查看知识库）」。验证：`grep -n 'listLessons\\|showLessons' frontend/src/features/action/ActionPage.tsx` 无输出；CDP 断言 Action 页不含「学习经验」文本；沉淀后 notice 含「知识库」
- [ ] 3.3 离线演示分支：状态 pill 显示「离线演示」而非状态值，并在小字中说明「步骤执行 / 专家分配需后端在线」。验证：`VITE_API_MODE=mock` 下 CDP 断言文案命中且不出现伪造的「执行中/已归档」

## 4. 前端：机会/问题板块 → 步骤时间线

- [ ] 4.1 步骤区改时间线（复用既有 `.timeline/.tl/.tldot/.tl-body/.tl-head`）：节点色按状态（done/active/待办/受阻）、连接线由既有伪元素提供；`openSteps: Record<number, boolean>` 默认展开当前步（首个 `in_progress`；无则首个非 done；否则末步），换档案重置。验证：CDP 断言节点数 = 步骤数、默认展开态命中当前步、点击某步「收起」只影响该步
- [ ] 4.2 推进控件（开始 / 完成 / 受阻）与展开控件移入 `.tl-actions`（步骤行右侧，与 `.step-trace` 同区），折叠态仍可见。验证：CDP 用 `getBoundingClientRect()` 断言右侧按钮组 `left` > 步骤标题 `left` 且同一行（`top` 差 < 24px）
- [ ] 4.3 每步「负责专家团」：展开态显示该步 `experts` chips（`.expert-chip.user`），空态呈现「未指定负责专家」；候选池 = `capabilities['专家团']` ∪ 档案级 `orchestration.experts`（后者标「系统建议」）；添加/移除调用 `setStepExperts`（整体设置），失败仅提示、不做乐观更新。验证：CDP 添加一位专家 → 重新加载档案该 chip 仍在；`curl` 单查该档案 steps[seq].experts 与界面一致
- [ ] 4.4 每步数据定位：展开态显示 `.step-evidence`（`step.evidence`，空则「暂无定位说明」）+ `.step-trace`「定位数据 →」调用既有 `onTrace(detail.id)`。验证：CDP 点击后证据链抽屉打开且该步定位串文本命中；对无 evidence 的步骤断言空态文案
- [ ] 4.5 新增 CSS 仅限带前缀的 `.tl-actions` / `.tl-more`（其余复用既有死 CSS）；确认类名无碰撞。验证：`grep -n '\\.tl-actions\\|\\.tl-more' frontend/src/styles.css` 命中；`grep -rn 'className="facts"\\|className="items"' frontend/src` 无新增（P013 防碰撞）；`npm run build` 通过

## 5. 前端：知识库处理过程可折叠

- [ ] 5.1 `KnowledgePage.tsx` 条目「处理过程」改为默认收起、点击展开（移除只弹 notice 的「查看处理过程」假按钮），展开态保留 `content` 全文。验证：CDP 断言初始不可见 → 点击后文本命中；`grep -n '查看处理过程' frontend/src/features/knowledge/KnowledgePage.tsx` 无输出

## 6. 门禁、文档与归档

- [ ] 6.1 后端门禁：`cd backend && python3 -m tests.action_check`（新节）+ `python3 -m tests.run_all` 全绿（贴输出；golden 基线不变）
- [ ] 6.2 前端门禁：`cd frontend && npm run build` 通过；文档一致性 `cd backend && python3 -m tests.check_docs` ALL GREEN
- [ ] 6.3 CDP 端到端用例（后端在线）：列表形态与状态 pill → 时间线展开收起 → 控件右置 → 每步添加专家（落库复核）→ 每步定位数据 → Action 页无经验块 + 知识库经验可展开
- [ ] 6.4 文档同步：`docs/持续优化路线.md` 登记/勾选该项（含 change id）、`docs/版本路线图.md`「当前打开的工作」、`docs/开发过程记录.md` 追加「迭代 44」、`docs/开发问题与经验.md` 补 P/D（含 propose 阶段已记决策的 apply 期修订）
- [ ] 6.5 归档：`openspec archive action-loop-timeline`（快照写入 `openspec/specs/business-action/spec.md`：需求来源表 + 1 条 ADDED + 3 条 MODIFIED 全文替换），归档后 `openspec validate --specs` 全绿 + 提交信息含【测试证据】+【反思】
