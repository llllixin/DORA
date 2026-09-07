## 1. 后端门禁与规则函数

- [x] 1.1 `run_engine` 空数据门禁（无 metric_series → 空 pulse `last_updated='--'`、空 insights），验证：`python3 -c` 清空 series 后 `/api/insights` 空且 pulse 计数 0
- [x] 1.2 新增 `_below`（严格 <）与 `_breach(actual, threshold, inclusive=True)`（默认 <=）并接入 margin/east 判定，验证：engine_check 断言"等于目标不触发、等于阈值触发、inclusive=False 不触发等于"

## 2. 时间动态化

- [x] 2.1 pulse `last_updated` 取 `data_event.updated`（无事件 `--`），验证：空事件时 pulse last_updated=`--`
- [x] 2.2 `engine_evidence.updated` 从最新 `data_update` 取（无事件 `--`），验证：改最新事件时间后 evidence updated 跟随

## 3. 前端名称下沉 + watching 标注

- [x] 3.1 Pulse 状态栏改为 props `dataLabel`（App 由 `dataSrc` 下发，默认旧文案），验证：`npm run build` + 冒烟
- [x] 3.2 "持续关注"计数旁加 `?`（title 悬浮"当前为静态展示"）及样式，验证：build + 目视冒烟

## 4. 门禁回归与文档

- [x] 4.1 `python3 -m tests.run_all` 全绿 + 空数据场景跑 `/api/insights`、`/api/pulse`
- [x] 4.2 dev-log 迭代条目 + 路线图（范围脚注） + `docs/开发问题与经验.md` P010/D021
