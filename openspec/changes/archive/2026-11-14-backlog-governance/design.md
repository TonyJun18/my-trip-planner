# Design

## Context

见 `proposal.md` 与 `docs/superpowers/specs/2026-11-14-backlog-governance-design.md`。当前约束：

- `docs/night-build-manual.md` 铁律 1/2 规定任务只来自 `docs/night-build-todo.md`，night-start 以 `- [ ] slug:` 启发式提取可执行项；任何重排不得改变该提取行为。
- 2026-11-14 实测当前分支后端 `1118 passed`；本 change 不触碰 `backend/`、`frontend/`。
- OpenSpec 对「无 spec 级行为变更」的 change 要求 `skip_specs: true`，禁止伪造 capability。

## Goals / Non-Goals

**Goals:**

- 任务文件具备单一可执行队列、显式状态、决策记录与 append-only 历史。
- 4 个首批任务卡达到「夜间 worker 可直接执行」的粒度（文件、断言、命令、槽数齐全）。
- 关闭清单可追溯，减少重复讨论。
- OpenSpec 状态与仓库实际一致（归档滞留 change）。

**Non-Goals:**

- 不实现 4 个任务（后续独立 change）。
- 不新增自动化脚本或 CI 检查；结构校验用一次性 shell/grep 证据。
- 不重写历史条目，不合并分支。

## Decisions

### D1：分层重构，而不是全量重写

**选择**：在现有文件顶部插入 §0-§3，原 197 行整体下移为 §4 历史归档，只补勾不改写。

**理由**：night-start 依赖 `- [ ] slug:` 提取；全量重写会破坏历史 diff 与审计链。分层方案同时满足「可机械解析」与「可追溯」。

**备选**：只增量追加（问题不解决）；全量重写（风险高）。

### D2：§1 硬上限 6，当前只放 4

**理由**：夜间 4-9 个 worker 槽位，但任务需 review 后合并；队列过长会诱发并行冲突与半成品堆积。候选池承接其余信号。

### D3：任务卡 7 字段

类型/安全区、证据、做什么、可测验收、规模与拆分、依赖、风险与关闭条件。

**理由**：前两类问题（重复立项、验收空泛）都源于缺字段；证据字段强制「先核验再立项」。

### D4：关闭项用 `- [~]`，备注用 `- [ ]（…）`

**理由**：`- [~]` 不匹配 night-start 的 `- [ ] task-` 提取；同时与备注区分，避免再次语义过载。OpenSpec tasks.md 不使用 `[~]`（其解析器视为未完成）。

### D5：OpenSpec 用 `skip_specs: true`

**理由**：本 change 无运行时行为变更，符合 OpenSpec 官方指引；capability 留给真正的产品功能 change。

### D6：归档 `trip-detail-schedule-timeline`

**理由**：该 change 已实现入 main（`schedule_service`、三读路径注入、前端时间轴均在案），tasks 未勾属于流程债。归档前用 `openspec validate --strict` 与代码 grep 核验，不修改实现。

## Risks / Trade-offs

- [文档重排破坏手动阅读] → 保留 §4 原文，新增 §0 图例与审计报告交叉引用。
- [night-start 仍把历史区 `- [ ]` 备注当任务] → 备注行不含 `task-` slug；§0 明确提取规则，验证时 grep 统计。
- [4 个任务卡粒度过粗，worker 自由发挥] → 每卡写明文件/函数/测试名/命令；M 任务拆 2 槽。
- [关闭清单误伤未来需求] → 每条写重开条件；候选池保留触发条件。
- [归档 trip-detail 暴露 spec 漂移] → 先 validate；若失败，只修 spec 文档不改代码，并在审计报告记录。
- [任务卡证据过期] → 统一引用 2026-11-13/14 文档与本次代码核验；后续立项需重新核验。

## Migration Plan

1. 新增审计报告（证据与取舍）。
2. 备份式重排 `docs/night-build-todo.md`：原文整体下移，新段落置顶。
3. 归档 `trip-detail-schedule-timeline`。
4. `openspec validate backlog-governance --strict` + 结构 grep。
5. 回滚策略：`git checkout -- docs/night-build-todo.md` + `git revert` 归档提交；无数据迁移。
