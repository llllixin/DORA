## 1. 修复

- [x] 1.1 `doraApi.ts refreshReasoningApi`：显式 `timeoutMs = 30000`；验证：`npm run build` 通过，代码审查无其它 2600 默认调用误伤 reason refresh

## 2. 收尾

- [x] 2.1 dev-log「迭代 32」+ 提交（【测试证据】+【反思】）

【测试证据】npm run build 通过；refreshReasoningApi 现传 timeoutMs=30000（原默认 2600）。真实 DeepSeek 批量实测 ~4.9s << 30s → 不再误杀；后端并发单飞仍防连点重复打 LLM。
【反思】Bug1（P011 分析期已标记）在接真实 LLM 后立刻兑现——教训：前端超时必须与外部依赖实测上界对齐，接 key 后应把「重新解释」点一遍纳入验收；前端假失败但后端已写缓存会造成 UI 自相矛盾（toast 失败 + 徽标已变 AI），此类状态需靠超时对齐消除。

