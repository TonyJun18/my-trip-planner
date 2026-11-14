# Proposal

## Why

`docs/night-build-todo.md` 是夜间流水线的唯一任务源，但 197 行里混着可执行任务、佐证、素材、不排期与已完成的遗留记录；同一符号 `- [ ]` 承载五种语义，导致流水线提取脆弱、已完成项不闭环、调研信号无法转成可排期任务、长期悬空项反复被讨论。2026-11-13/14 两夜的调研（Reels 导入红海、43% 缺陷研究、BYO-AI 范式）已产出明确缺口，需要一次结构性治理把「证据 → 任务 → 验收 → 取舍」固化下来。

## What Changes

- 重排 `docs/night-build-todo.md` 为四层：§1 可执行队列（硬上限 6）、§2 候选池（P2/前置/需产品决策）、§3 关闭与不排期决策记录、§4 历史归档（append-only）。
- 定义状态图例（可执行 / 完成 / 关闭 / 备注）与任务卡契约（类型与安全区、证据、做什么、可测验收、规模与夜间拆分、依赖、风险）。
- 新增 4 个首批可执行任务：`task-early-arrival-check`、`task-byo-ai-import-kit`、`task-day-map-deeplink`、`task-import-recall-en`。
- 关闭/不排期：视频解析、文件分享、照片归位/自动日记、Explored 街道点亮、gallery-community-v3、DMO 白标；已完成项（多币种前端、property-qa、favorites、photo-batch）补勾闭环。
- 归档已完成但滞留的 OpenSpec change `trip-detail-schedule-timeline`。
- 新增审计报告 `docs/nightly/backlog-review-2026-11-14.md`（证据、取舍、风险）。

## Capabilities

### New Capabilities

（无——纯 docs/流程治理，不改运行时行为；按 OpenSpec 规则设置 `skip_specs: true`，不伪造 capability。）

### Modified Capabilities

（无）

## Impact

- **文档**：`docs/night-build-todo.md`（结构重排）、`docs/nightly/backlog-review-2026-11-14.md`（新增）、`docs/superpowers/specs|plans/2026-11-14-backlog-governance*`（设计/计划）。
- **OpenSpec**：新增 `backlog-governance` change（skip_specs）；归档 `trip-detail-schedule-timeline`。
- **代码**：零改动（不触碰 `backend/`、`frontend/`）。
- **流水线**：§1 保持 `- [ ] task-slug:` 格式，night-start 提取行为不变；历史区原样保留。
- **风险**：文档重排可能破坏人工阅读习惯；通过图例、审计报告与 append-only 历史区缓解。
