# Design — action-loop-timeline

## Context

见 `proposal.md`（Why / What Changes）。影响本设计的技术现状：

- **Action 页现状**（`features/action/ActionPage.tsx`，285 行）：左抽屉 = 档案列表（裸 `button.suggest` 行 + `CASE_LABEL` 文字状态）+ 最下方「🧠 学习经验（N）」折叠块（数据来自 `listLessons`）；右主区 = 档案头 + 平面步骤列表（全部展开、控件在文案下方）+ 卡片底部档案级「专家团」。
- **后端现状**：`action_step` 已有 `evidence`（引擎建档逐条写入，`builder._steps_for`）、`why/note/result`，**无 experts**；`repository.set_action_step_status` 是唯一的步骤写入口；`flow._get` 已把 resolved 档案冻结（任何推进 4xx）；`db.init_db` 已有「create_all 之外补 DDL」的幂等模式（`_TEXT_ALTERS`）。
- **CSS 现状（关键）**：`styles.css` 存在**无任何 tsx 引用**的成套死 CSS，正是本需求形态：`.timeline/.tl/.tldot/.tl-body/.tl-head`（`.tl.done/.tl.active` 节点色、`.tl:not(:last-child):before` 连接线、`.tl-head{display:flex;justify-content:space-between}` 天然右置槽位）、`.step-trace`（可点定位按钮）、`.step-evidence`（定位串 chip）、`.expert-chip.user`/`.data-chip.user`（「用户添加」态）、`.add-mini`（+ 添加）。
- **洞察列表形态（对齐目标）**：`InsightPage.tsx:85` 每行 = `.itop`（Tag + 置信度）→ `.iname` → `.idesc` → `.list-status`（`action|watch|none` 三色调 pill，如「未加入行动回路」）。
- **离线路径**：`data.ts` 的 `actionCases[].steps` 只有 `{title,desc,evidence}`（**无 status**），离线分支（`ActionPage.tsx:127-150`）只列档案 + 打开证据链。

## Goals / Non-Goals

**Goals:**

1. 档案列表与洞察列表形态一致，状态以 pill 形式二值化（执行中 / 已归档），内部状态机零改动。
2. 机会/问题板块 → 步骤时间线：节点化、可展开收起、控件右置、每步负责专家（可添加/移除、落库）、每步数据定位入口。
3. 经验的查看落点唯一化（知识库），去掉 Action 页重复承载与知识库假按钮。

**Non-Goals:**

- 不改状态机迁移规则、不改 `archive-as-lesson` 幂等语义、不改证据链抽屉。
- 不在离线演示分支伪造步骤状态与专家（理由见 D8）。
- 不新增数据源：定位能力只复用 `step.evidence` + 既有 `onTrace`。
- 不做专家池白名单（E1 专家注册表另行规划）、不做权限/角色。

## Decisions

### D1 列表形态：单列 + `.list-status` pill + 二值映射

行结构 `Tag(kind) + 状态 pill(执行中/已归档) + code` → 标题 → 来源 → 描述；复用 `.insight-item` 同款行容器与 `.list-status` pill（`action` 色调=执行中、`none` 色调=已归档），排序 `执行中在前`（`status !== 'resolved'` 先），列表头显示「执行中 N · 已归档 M」，并保留既有抽屉折叠（`drawerOpen`）。

- **映射函数**：`caseStateLabel(status) = status === 'resolved' ? '已归档' : '执行中'`——展示层函数，**不参与**状态机/接口。
- **备选否决**：① 直接显示四态（用户明确要求二值）；② 抽屉内分「执行中 / 已归档」两栏分组（抽屉仅 300px，分组把列表切碎，且「跟洞察列表一样」=单列 + 每行状态标记）；③ 改后端 status 枚举为二值（动状态机与既有门禁，收益为零）。

### D2 时间线复用死 CSS，新增类名带前缀

直接复用 `.timeline/.tl/.tldot/.tl-body/.tl-head/.step-trace/.step-evidence/.expert-chip(.user)/.add-mini`（它们当前无引用，等于为这套 UI 预留）；新增仅限右侧按钮组容器 `.tl-actions` 与展开态区块 `.tl-more`，命名带 `tl-` 前缀。

- **依据**：P013（CSS 全局命名空间，通用单词类名会静默碰撞）→ 新类名必须带组件前缀；复用既有类名是**有意**行为，且顺带清掉死 CSS 的「无主」状态。
- **备选否决**：全部用 inline style（既有 ActionPage 大量 inline，但时间线节点/连接线无法用 inline 表达伪元素与状态色，且会与既有 CSS 重复两套）。

### D3 展开态是纯展示层 state

`openSteps: Record<number, boolean>`（key = `seq`）。默认展开「当前步」= 第一个 `in_progress`；无 `in_progress` 时展开第一个非 `done`；全 `done` 时展开末步。切换档案（`currentId` 变化）重置。不入后端、不入 localStorage（D007 的 localStorage 仅用于「加入回路」这类跨页标记，展开态是瞬时视图偏好，持久化只会制造"上次看到一半"的困惑）。

### D4 每步专家：整体设置的幂等端点

- 列：`action_step.experts`（JSON，缺省 `[]`）；`_action_step_dict` 增加 `experts`；`repository.set_action_step_experts(case_id, seq, experts)` 返回该步 dict。
- 端点：`POST /api/action/cases/{case_id}/steps/{seq}/experts`，请求体 `{"experts": [...]}` → **整体替换**，返回 `{ok, case}`（与 start/done/blocked/verify 同形，调用方一次拿到权威状态）。
- 校验：元素为非空字符串（`strip()` 后判空）、`dict.fromkeys` 去重保序、`len ≤ 8`；违规 4xx；`case/step` 不存在 404。
- **备选否决**：① `add`/`remove` 双端点（非幂等、重放会重复追加、断言需处理顺序）；② `PATCH` 语义（与本仓「POST 动作端点」风格不一致）；③ 专家存储进 `orchestration`（档案级 JSON，会与「系统建议」语义打架）。

### D5 冻结与校验边界在 flow / router，不在前端

`flow` 层复用 `_get` 的 resolved 冻结（新增 `set_step_experts` 走同一入口）；`resolved 4xx`、`seq 不存在`、`空名/超限` 全部由后端判定并在界面提示原因——前端**不**乐观更新（失败即不显示未落库的专家，守「判断/规则在后端」的架构原则 1）。

### D6 候选专家池 = 前端能力目录 ∪ 档案级系统建议

候选 = `capabilities['专家团']`（`data.ts` 静态能力目录，与 PulsePage 同源）∪ `detail.orchestration.experts`，后者在 UI 上标「系统建议」；已在该步名单中的显示为 `.expert-chip.user`（用户指定）。后端**不**校验白名单（它不掌握池）。

- **退出条件**：`expert-registry-domain`（E1）落地后，池改由后端权威下发、后端校验成员合法性。

### D7 每步数据定位 = `step.evidence` + 打开证据链

展开态显示 `.step-evidence` chip（`step.evidence`；为空时呈现「暂无定位说明」）+ `.step-trace`「定位数据 →」按钮调用既有 `onTrace(detail.id)`（打开该档案的证据链抽屉）。**不**新造数据源、不编造定位串。

- **备选否决**：为每步新增 `data_locator` 后端字段（`evidence` 已是引擎按步写入的定位说明，新增字段=同一事实两个源）。

### D8 经验收口到知识库；离线分支不伪造

- 删除：`lessons` / `showLessons` / `lessonNote` 之外的 `listLessons` 拉取与抽屉经验块；`archiveLesson` 保留（写 `knowledge_archive` lesson），成功后提示「✓ 已沉淀到知识库 → 经验」。
- 知识库条目「处理过程」改为可折叠（默认收起，点击展开），替换现有只弹 notice 的假按钮。
- **离线演示分支保持列表形态**（不加步骤时间线）：`data.ts` 的演示 steps **没有 status**，前端推导状态 = 伪造；违背「演示要诚实标注」（D003）。离线分支仅把状态 pill 换成「离线演示」并在文案说明「步骤执行/专家分配需后端在线」。
- **退出条件**：若离线演示需要完整回放 → 由镜像补齐 `status/experts` 字段（同一 change 内改镜像不划算，另立候选）。

### D9 迁移：加列即迁移，历史行天然可用

新增列走 `db.init_db` 的幂等补列（`ALTER TABLE action_step ADD COLUMN experts JSON ...`，缺省 `[]`），`create_all` 负责新表；旧行读回空列表 → 界面空态。**无数据回填、无破坏性变更**；回滚 = 后端回退版本（前端把 `experts` 当可选字段，缺失按空态渲染，不报错）。

## Risks / Trade-offs

- [二值化掩盖 `waiting_verify`（待验证）这一关键中间态] → 详情页仍显示细粒度状态 + 列表头计数；若用户希望列表能看到「待验证」，退出条件 = 把 pill 扩成三值（一行映射改动）。
- [每步专家为空态，首屏看起来"没编排"] → 空态显式呈现「未指定负责专家」+ 候选池（含「系统建议」标记）；`orchestration.experts` 仍在详情可见，信息不丢。
- [后端不校验专家池 → 可能写入不存在的专家名] → 可接受（人填的责任声明）；E1 落地后收紧（D6 退出条件）。
- [死 CSS 复用后与其它页面耦合] → 这些类名当前无引用，仅本页使用；新类名带 `tl-` 前缀（P013）。
- [时间线 + 展开态让主区变高] → 折叠态只有 `节点 + 标题 + 右侧控件`，比现状（全展开）更短；展开态按需。
- [删掉 Action 的经验块后用户找不到经验] → 沉淀提示直接指向知识库；知识库页已有「经验」筛选与条目内容。

## Migration Plan

1. 后端先加列 + 补列 DDL（幂等，旧行缺省空）→ 跑 `action_check`（新节）确认往返与冻结。
2. 前端加 `CaseStep.experts?`（可选）并先让界面容忍缺失（空态渲染），再接时间线与每步专家 UI。
3. 列表行改写与经验块移除可独立提交（纯展示层，无后端依赖），便于回滚定位。
4. **回滚**：前端回退到「裸按钮列表 + 平面步骤 + 抽屉经验块」不需要后端回退（新端点/新字段无人消费即静默）；后端回退只需忽略 `experts` 列。

## Open Questions

无（列表二值映射与离线分支形态已在 D1/D8 定案并写进 tasks；若评审希望列表可见「待验证」，属 D1 退出条件内的一行改动，不改变 spec 与任务拆分）。
