## Why

行动回路是「数据 → 洞察 → 行动 → 验证」闭环的最后一环，但 Action 页的呈现与洞察页脱节：档案列表是裸按钮行（状态以文字挤在编号后：`已建档/执行中/待验证/已归档`），专家团只在档案底部一次性展示、与具体步骤无关，步骤全展开成平面列表且推进控件压在文案下方，扫读性差；「学习经验」还挂在档案列表最下方，与知识库页（同一批 lesson 数据的正式归属地）双份承载。用户 2026-09-11 实测提出：列表对齐洞察列表形态、状态做成 tag（执行中 / 已归档）、经验只在知识库；机会/问题板块改时间线，每一步可展开收起、控件右置、专家团落到每一步并可添加（对这一步负责）、每步能直接定位数据。

## What Changes

**1. 档案列表对齐洞察列表形态（展示层）**

- 每行按洞察列表行的信息层次：`Tag(问题/机会) + 状态 tag(执行中/已归档)` → 标题 → 来源/描述一行 → 状态行（沿用 `.list-status` pill，即洞察列表「未加入行动回路」同款形式）。
- 状态 tag 是**展示层二值映射**：内部四态 `open|running|waiting_verify → 执行中`、`resolved → 已归档`；内部状态机、API 契约与详情页细粒度状态**均不变**（无迁移/兼容风险）。
- 排序：执行中在前、已归档在后（稳定序），列表头显示「执行中 N · 已归档 M」；无档案时空态文案不变。

**2. 学习经验移入知识库（展示层收口，无数据迁移）**

- 删除档案列表最下方的「🧠 学习经验（N）」折叠块、`listLessons` 拉取与相关本地状态；经验查看的唯一落点是知识库页「经验」类目（既有 `knowledge_archive` entry_type=lesson，无需数据迁移）。
- 「沉淀经验 → 知识库」按钮与后端 `archive-as-lesson` 幂等链路保留，沉淀成功提示改为指向知识库；知识库条目的「处理过程」由占位提示按钮改为可展开/收起（去掉假交互）。

**3. 机会/问题板块改步骤时间线（展示层 + 新后端能力）**

- 纵向时间线（复用既有无引用 CSS `.timeline/.tl/.tldot/.tl-body/.tl-head`）：每步一个节点，节点色反映状态（done / 进行中 / 待办 / 受阻）。
- **每步可展开收起**（默认当前步展开）：折叠时只显示 `序号 + 状态 + 标题 + 右侧控件`；展开显示 `desc / why / note / result / 数据定位 / 负责专家团`。
- **推进控件移到步骤行右侧**（开始 / 完成 / 受阻），与「定位数据 →」「展开 ▸」同区，纵向扫读不再被按钮打断。
- **专家团落到每一步（per-step）并可添加**：新增后端持久化 `action_step.experts`（JSON 名单）+ `POST /api/action/cases/{id}/steps/{seq}/experts`（整体设置、幂等、去重、上限 8、resolved 档案冻结）。档案级 `orchestration.experts` 语义收窄为「系统建议」（候选池标记），不再是「谁负责」的唯一来源。
- **每步直接定位数据**：步骤展开区显示该步 `evidence` 定位串（引擎建档时已写入），「定位数据 →」打开该洞察证据链（复用现有 `onTrace`，不新增数据源、不伪造数据）。

**4. 非目标（Not Doing）**

- 不改引擎判定、`severity`/`consequence`（另一 change `insight-judgment-structure` 范围）、不改步骤状态机迁移规则、不改 `archive-as-lesson` 幂等语义。
- 不做专家注册表/权限/角色（E1 `expert-registry-domain` 另行规划）：后端只做结构性校验，不维护专家池白名单。
- 不预置每步专家（不 seed、不写镜像）：首屏为空态「未指定负责专家」，避免与引擎/镜像形成双源。
- 不改 `tag` 文案与 golden 基线；不改证据链抽屉本身。

## Capabilities

### New Capabilities

（无：本 change 全部落在既有 `business-action` 能力内，不新增 capability。）

### Modified Capabilities

- `business-action`: ① **ADDED** 新增需求「行动步骤可指定负责专家团（per-step 持久化 + API）」；② **MODIFIED**「行动档案与步骤可持久化存取」——步骤记录扩为承载 `experts` 名单；③ **MODIFIED**「档案可在界面真实执行与验证（真数据源）」——步骤区呈现为时间线（可展开收起、控件右置、每步数据定位入口）、档案列表按洞察列表形态并显示执行中/已归档 tag；④ **MODIFIED**「已归档档案可沉淀为经验库并展示处理过程」——经验查看落点收敛到知识库（Action 页不再承载经验列表、知识库条目处理过程可展开收起）。

## Impact

- **后端**：`models.py`（`ActionStep.experts` JSON 列）、`db.py`（幂等 DDL 补列，沿用 `_TEXT_ALTERS` 同款 init 补 DDL 模式）、`repository.py`（`set_action_step_experts` + `_action_step_dict` 新字段）、`schemas.py`（`StepExpertsRequest`）、`routers.py`（新端点）、`action/flow.py`（resolved 冻结 + 结构性校验）；无新表、无历史行破坏（旧行 `experts` 缺省 `[]`）。
- **前端**：`features/action/ActionPage.tsx`（列表行改写 + 时间线 + 每步专家/collapse + 移除经验块）、`services/doraApi.ts`（`setStepExperts`）、`types.ts`（`CaseStep.experts`）、`styles.css`（复用死 CSS + 少量新增 `tl-*` 工具类）、`data.ts` 离线镜像同步（steps 不带 experts，与后端一致为空态）。
- **契约**：`/api/action/cases/{id}` 的 `steps[]` 新增 `experts: string[]`（**增量、向后兼容**：前端可选字段，缺失按空态渲染）；新端点 `POST /api/action/cases/{id}/steps/{seq}/experts` 返回 `{ok, case}`，与既有 step 动作端点同形。
- **门禁**：`backend/tests/action_check.py` 新增一节（专家集设置/去重/上限/resolved 冻结/非法迁移 4xx）；`frontend && npm run build`；`python3 -m tests.run_all`；CDP 用例覆盖时间线展开收起、按钮右置、状态 tag 二值映射、经验块已移除。
- **文档**：`docs/持续优化路线.md`（backlog 项 + change id）、`docs/版本路线图.md`（当前打开的工作）、`docs/开发过程记录.md`（迭代 44）、`docs/开发问题与经验.md`（propose 阶段 D 系列即时记录）。
