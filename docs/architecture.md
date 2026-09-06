# Dora Architecture

```text
Data Ingest
  ↓
Metric Snapshot
  ↓
Rule Evaluation
  ↓
Signal
  ↓
Insight (Problem / Opportunity / Change)
  ↓
Evidence + Confidence
  ↓
Action Loop / Continuous Watch
  ↓
Verification / Escalation
  ↺
```

Frontend owns presentation and interaction. Backend owns business judgment, persistence, scheduling and AI orchestration.

## Domain boundaries

- Pulse: prioritized business attention entry.
- Insight: explainable business judgment.
- Action: executable problem/opportunity case.
- Watch: delegated goal + trigger + escalation.
- Evidence: traceable basis for each important judgment.
- Agent: intent/context/tool/evidence/reasoning/action orchestration.
