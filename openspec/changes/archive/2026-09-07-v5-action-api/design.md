## Context

见 proposal.md。T1 repo 已有 step 状态写原语与 verify(resolved|running)；T2 builder 造档案。T3 把"合法性"提升到服务层（flow.py），并暴露 REST。

## Goals / Non-Goals

**Goals:** flow 状态机 + /api/action/cases REST + action_check 第 3 节 + 冒烟；旧 /actions 暂时不动。

**Non-Goals:** 前端接线（T4）；删除旧静态 /actions（T5 随 e2e 切新 API 后下线）；自动创建新步骤（continue 只回 running，后续动作由用户/工具继续推进）；SSE。

## Decisions

- **合法性唯一真源 = flow.py**：repo 只校验枚举合法值，业务迁移规则在服务层（reject 非法并 4xx）。
- **case 状态推导**：start → running（open→running）；每次 done 后重算：全部步骤 done → waiting_verify，否则 running；blocked → running（等待处理）。已 resolved 冻结一切迁移。
- **verify 语义（D031-3）**：resolved 仅当 case=waiting_verify（全 done）且必带 note（追加 archive 形成验证记录，不改判定/reasonSource）；continue 允许 running/waiting_verify（人工继续观察），置回 running。
- **note 落 archive 而非加列**：避免 create_all 无法加列的迁移负担；archive 追加 `[ISO] outcome: note` 行，兼作验证日志。
- **新 REST 与旧静态并存**：`/api/action/cases*` 真数据；`/api/actions*` 保持静态吐 ACTIONS（供 e2e Case1/2 与旧 sync 继续工作）；T4 前端换新端点后 T5 下线旧端点并改 e2e。

## Risks / Trade-offs

- 旧 /actions 与新 /action/cases 双源并存期，前端列表可能短暂双份（syncRemoteData 仍读 /actions 静态）→ T4 一次性切换，避免中途撕裂。
- continue 不自动开新步 → 语义是"回到观察/人工推进"，不做自动闭环（诚实边界）。
