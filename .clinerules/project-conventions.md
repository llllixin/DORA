# Dora 项目开发约定（binding）

## 提交与仓库
- 仓库：git（main）；身份为仓库本地 `tomara <tomara@mac>`；远端 GitHub。
- 每个功能点/文档变更单独提交；提交信息用中文描述做了什么（示例：`feat: ...`、`docs: ...`）。
- 禁止提交：node_modules、dist、__pycache__、*.tsbuildinfo、vite.config.js/.d.ts、.env、根目录 .DS_Store。

## 动手前
- 改文件前先读目标文件当前内容（可能被格式化改写）；用唯一锚点做小步编辑。
- 沿用现有代码风格与命名（后端 camelCase 契约、frontend features/ 分层）。

## 验证底线（任务勾"完成"的必要条件）
- 前端改动：`cd frontend && npm run build` 通过。
- 后端改动：模块可 import；相关端点 curl 200；引擎改动跑 `python3 -m tests.engine_check`。
- 端口：后端 8000、前端 5173；vite.config.ts 改动后必须重启 dev server 并用 curl 验证代理（/api → 8000），确认不是 SPA fallback。

## 文档同步（每次 change/迭代收尾必做）
- docs/开发过程记录.md：追加一条迭代（时间/目标/文件改动/验证/边界）。
- docs/开发问题与经验.md：新踩坑 → P 系列；新取舍 → D 系列（写清退出条件）。

## OpenSpec
- 变更前先 propose（proposal + specs delta + design + tasks），review 后再 apply。
- 不在 propose 阶段写业务代码；apply 阶段按 tasks 逐条实现并勾选。
- 方向把控：大版本/里程碑状态以 docs/版本路线图.md 为单一事实源，OpenSpec change 归档后同步刷新。
