# 开发任务清单治理（Backlog Governance）设计

- 日期：2026-11-14
- 状态：已获用户批准（「按照推荐来」）
- 范围：**仅 docs / 流程治理**，不实现任何功能任务、不改运行时行为
- 证据来源：`docs/nightly/competitive-analysis/2026-11-13.md`、`docs/nightly/evaluations/task-share-target-eval-2026-11-13.md`、`docs/nightly/evaluations/task-monday-closure-coverage-2026-11-13.md`、`docs/nightly/reports/2026-11-13.md`、`docs/nightly/reports/2026-11-14.md`，以及本设计执行前的代码核验（见 §2）

## 1. 背景

`docs/night-build-todo.md` 是夜间流水线的唯一任务源（`docs/night-build-manual.md` 铁律 1）。当前文件 197 行，存在五类结构问题：

1. **`- [ ]` 语义过载**：可执行任务、佐证备注、素材、不排期共用同一符号（例：L152 佐证、L172 素材、L197 素材），night-start 依赖「`- [ ] slug:`」启发式提取，语义脆弱。
2. **完成项未闭环**：已完成项没有勾选或没有归档。例：L166 记「多币种前端未接线」，实际 `frontend/src/components/AddExpenseDialog.vue` 已含币种/汇率表单；`trip-detail-schedule-timeline` 已实现并入 main，但 OpenSpec tasks 全未勾选、change 未归档。
3. **遗留项没有升格**：booking-ledger 的 4 个 Minor 埋在 L190 完成记录里；英文导入 0/10 埋在 L186 括号里——没有优先级、验收、风险字段，无法排期。
4. **调研信号未转任务**：2026-11-13 的 43% 缺陷研究指出「早到」占闭馆类缺陷 56.7%（381/672），但代码只校验「晚于闭馆」；BYO-AI 范式只有结论无任务；视频解析/文件分享既无任务也无关闭决策，会反复被调研重提。
5. **缺少取舍框架**：无优先级、依赖、工作量、夜间可执行性、风险，无法判断先做什么。

## 2. 执行前代码核验（避免重复立项）

| 核验项 | 结果 | 对方案的影响 |
|---|---|---|
| 当前分支后端全量测试 | `1118 passed / 0 failed`（2026-11-14 实测） | 11-14 报告的 2 例 frame_projection 失败在当前分支不复现；不立修复任务 |
| TimeGate 是否查「早到」 | `time_validation.check_plan_time_gate` 仅有 `arrival >= close - CLOSING_BUFFER_MINUTES`，**无 `arrival < open` 分支** | 立 `task-early-arrival-check` |
| 多币种前端 | `AddExpenseDialog.vue` 已接线币种/汇率/规则汇率兜底 | L166 遗留标记为「已完成」，不重开 |
| 单日多点导航深链 | `frontend/src` / `backend/app` 无 `google.com/maps`、`maps.apple`、`uri.amap.com` 链接 | 立 `task-day-map-deeplink` |
| 英文导入召回 | `backend/tests/test_import_recall.py` 对 `NOTE_EN` 只做 `≤0.3` 上限断言，基线 0/10 | 立 `task-import-recall-en` |
| repeat_gate 前端露出口 | 仅通过 `TripDetailQaCard` 的 warnings 间接露出，无独立面板 | 记入候选池（并入质量报告任务，不单独立项） |

## 3. 已确认决策

1. **治理方案 A：分层重构**（顶部可执行队列 + 中部历史 append-only + 底部决策记录）。
2. **首批可执行队列 4 个**：`task-early-arrival-check`、`task-byo-ai-import-kit`、`task-day-map-deeplink`、`task-import-recall-en`。
3. **关闭清单全部生效**：视频解析、文件分享、照片归位/自动日记、Explored 街道点亮、gallery-community-v3、DMO 白标，均写明理由与重开条件。
4. **booking-ledger 4 个 Minor 放 P2**，其中时区语义需产品决策，不进入首批。

## 4. 目标与非目标

### 目标

- 让 `docs/night-build-todo.md` 重新成为**可机械解析、可判断、可追溯**的队列。
- 把 2026-11-13/14 两夜的有效调研信号转成 4 个可执行、可验证的任务卡。
- 把长期悬空的「视频解析 / 文件分享 / 照片归位」等明确关闭，减少重复讨论。
- 让已完成项与 OpenSpec 状态对齐（补勾、归档）。

### 非目标

- 不实现 4 个任务（后续另起 OpenSpec change + TDD）。
- 不改 `frontend/`、`backend/` 运行时代码。
- 不合并任何夜间分支。
- 不引入新的自动化脚本/工具（避免「治理」变成新工程）。

## 5. 治理结构

### 5.1 文件布局

```
docs/night-build-todo.md
├── §0 使用说明与图例
├── §1 可执行队列（硬上限 6，当前 4）
├── §2 候选池（P2 / 需产品决策 / 有前置）
├── §3 关闭与不排期决策记录（含重开条件）
└── §4 历史归档（2026-10-02 ~ 2026-11-14，原样保留，只补勾）

docs/nightly/backlog-review-2026-11-14.md   ← 本次审计证据与取舍
```

### 5.2 状态图例

| 标记 | 语义 | 流水线行为 |
|---|---|---|
| `- [ ] task-slug:` | 可执行 | night-start 提取入队 |
| `- [x]` | 已完成 | 跳过 |
| `- [~]` | 已关闭 / 不排期 | 跳过；理由见任务行或 §3 |
| `- [ ]（备注）` / `- [ ]（素材·不排期）` | 佐证 / 素材 | 不提取（无 slug） |

### 5.3 任务卡契约（必填 7 项）

每个 §1 任务必须包含：

1. **类型与安全区**（backend / frontend / docs；夜间并行规则见手册 §3.5）
2. **证据出处**（文件 + 日期；禁止「竞品好像有」式立项）
3. **做什么**（改哪些文件/函数，避免 worker 自由发挥）
4. **可测验收**（测试文件 + 断言 + 命令）
5. **规模与夜间拆分**（S=1 槽；M=2 槽；L 不允许直接入队）
6. **依赖**
7. **主要风险与关闭条件**

### 5.4 维护规则

- 历史区 **append-only**：只允许补勾，不允许重写既有记录。
- 可执行队列硬上限 6；超出进候选池并写触发条件。
- 新任务必须先写「已核实不存在」证据；已完成项必须补勾或移入 §3。
- 决策记录必须带日期、理由、重开条件。
- 每夜竞品分析新增任务只能进候选池，由用户或队列腾位后晋升。

## 6. 首批任务卡

### 6.1 `task-early-arrival-check`

- **类型/安全区**：补功能 / backend
- **证据**：`docs/nightly/competitive-analysis/2026-11-13.md` §1.2——模式 1「到访时场馆关闭」672 起，其中早到 381 起（56.7%）；`backend/app/services/time_validation.py` 只查晚于闭馆。
- **做什么**：
  - `time_validation.py` 增常量 `EARLY_ARRIVAL_BUFFER_MINUTES = 30`；
  - `check_plan_time_gate` 在闭馆检查前增加：`hours` 可知且 `arrival < open - buffer` → `category=schedule` warning；
  - 后端 i18n `backend/app/i18n/translations.py` 增 zh/en：`timegate.msg.arrive_early`、`timegate.suggest.arrive_early`；
  - 复用现有 warning → `plan.time_gate.issues` → 前端 TimeGate 面板 / property_qa 汇总链路，前端零改动。
- **可测验收**：
  - `backend/tests/test_time_validation.py` 新增 4 例：早到 60min 告警；早到 15min 不告警；无营业时间沉默；显式 `open_hours` 覆盖类目规则。
  - zh/en 两侧键存在且可渲染。
  - `cd backend && .venv/bin/python -m pytest tests/test_time_validation.py -q` 全绿，全套零失败。
- **规模/夜间拆分**：S，1 槽。
- **依赖**：无。
- **主要风险**：告警噪音。缓解：30min 阈值、只对已知营业时间、显式优先；关闭条件：真实行程噪声评估中误报率 >30% 则回退阈值到 45min。

### 6.2 `task-byo-ai-import-kit`

- **类型/安全区**：补功能 / frontend（第二槽如需解析增强则 backend）
- **证据**：`docs/nightly/competitive-analysis/2026-11-13.md` §1.3 Meridian Dispatch「规划在 app 外（用户自己的 AI），行程在 app 内」；我们只有 app 内 AI，无「AI 草稿回填」引导。
- **做什么**：
  - `ImportDialog.vue` 新增「AI 草稿」tab：三步引导 + 可复制 prompt + 粘贴框；
  - prompt 约束输出为可解析条目（`地点名 | 类型 | 建议时长 | 备注`），带版本号；
  - 粘贴结果复用 `POST /trips/note/import`（零新端点）；候选必须人工勾选，**绝不自动落库**；
  - i18n zh/en 约 8 键。
- **可测验收**：
  - `buildByoPrompt(locale)` 纯函数单测（含版本号/输出格式/禁止解释段）；
  - 3 份 fixture（Markdown 列表 / JSON 数组 / 散文）至少 2 份能产出候选，失败时明确提示不静默；
  - build 通过 + `check:i18n` 键数一致；
  - 敌意源剥离回归（现有 note_import 测试不改红）。
- **规模/夜间拆分**：M，2 槽（prompt+UI / 解析容错+测试）。
- **依赖**：无（`skills/ai-travel-planner/references/itinerary-json-schema.json` 仅作参考，不作依赖）。
- **主要风险**：LLM 输出漂移、支持成本。缓解：prompt 版本化、候选确认、失败明确提示；关闭条件：连续 3 次真机测试候选命中 <50% 则降级为纯文案引导。

### 6.3 `task-day-map-deeplink`

- **类型/安全区**：补功能 / frontend
- **证据**：`docs/nightly/competitive-analysis/2026-11-13.md` §1.1 Dream Trip「导出 calendar / 单日 Google Maps」；我们只有 ICS，无单日导航。
- **做什么**：
  - 新增 `frontend/src/utils/mapLinks.js` 纯函数：输入当日 stops（`lat/lng`），输出 Google / Apple / 高德链接；
  - Google：origin=首站、destination=末站、waypoints=中间站，最多 9 站，超限降级为「复制清单」；
  - Apple / 高德：单点导航（多站不支持），按顺序给「下一站」；
  - `TripDetailDayCard.vue` 日头增「导航」菜单；`ShareView` 复用同一组件即自动生效；
  - i18n 4-5 键。
- **可测验收**：
  - `mapLinks` vitest：URL 编码、waypoints 顺序、9 站上限、缺坐标跳过、单站禁用；
  - `npm run build` 通过；i18n 双侧一致。
- **规模/夜间拆分**：S，1 槽。
- **依赖**：无。
- **主要风险**：坐标体系差异（高德 GCJ-02 vs Google WGS84）与地区可达性。缓解：国内默认高德、海外默认 Google、不谎称精准；文案注明「以地图实际路线为准」；关闭条件：若判定必须做坐标纠偏则拆独立评估。

### 6.4 `task-import-recall-en`

- **类型/安全区**：补功能 / backend
- **证据**：`backend/tests/test_import_recall.py` 英文攻略基线 **0/10**，当前仅上限断言 `≤0.3`；`docs/night-build-todo.md` L186；Dream Trip 支持 18 语言。
- **做什么**：
  - `note_import.py`、`social_import.py` 地名收尾词表补英文（Temple/Shrine/Park/Garden/Market/Tower/Crossing/Street/Museum/Castle/Beach/Bridge/Square/Gallery/Zoo/Aquarium/Cathedral/Palace/District…）；
  - 行级启发：编号行 / 首字母大写短语 / 描述词截断（`free`、`must-see`、`ticket`、`yen` 等）；
  - 保持中文规则不变。
- **可测验收**：
  - `test_import_recall.py` 英文下限改为 `≥0.8`（8/10），中文 `≥0.9` 不回归，社交/邮件不回归；
  - 新增负例：`"The market was great"`、`"a park bench"`、`"we took the train"` 不产生候选；
  - 全套 pytest 零失败。
- **规模/夜间拆分**：M，2 槽（note 规则 / social+负例+回归）。
- **依赖**：无。
- **主要风险**：为拉召回引入噪音。缓解：双向阈值 + 负例集 + 候选上限；关闭条件：英文召回提升但负例误报 >2 条则回退并记降级。

## 7. 关闭与不排期决策

见 `docs/night-build-todo.md` §3。核心口径：

| 项 | 决策 | 重开条件 |
|---|---|---|
| Reels/视频内容解析 | 关闭 | 有视频理解模型预算或平台开放 API |
| 文件（图片/视频）分享 | 暂缓 | 有对象存储且接受成本 |
| 照片归位 / 自动日记 | 不排期 | 引入原生壳（Capacitor 等） |
| Explored 街道点亮 | 不排期 | 同上 |
| gallery-community-v3 | 不排期 | 真实发布 ≥20 条 |
| DMO 白标 | 不追 | 有 DMO 合作意向 |
| 多币种前端 / property-qa / favorites / photo-batch | 已完成关闭 | — |

## 8. OpenSpec 映射

- change 名称：`backlog-governance`。
- 本 change **不产生产品行为变更**，按 OpenSpec 自身规则设置 `skip_specs: true`（docs/tooling 场景），不伪造 capability。
- 同时归档已完成但滞留的 `trip-detail-schedule-timeline`（先核验实现与 spec 一致，再 archive）。
- 实现计划：`docs/superpowers/plans/2026-11-14-backlog-governance.md`。

## 9. 验证方式（docs-only）

1. `openspec validate backlog-governance --strict` 通过。
2. `openspec status --change backlog-governance --json` 无缺失 artifact。
3. 结构校验（grep/shell）：
   - §1 中每个 `- [ ] task-` 行都含 7 个字段关键字；
   - §1 任务数 ≤6；
   - §3 每条关闭项都有「理由 + 重开条件」；
   - 历史区行数与原文一致（append-only 校验）。
4. `git diff --stat` 仅含 docs/openspec 文件，无 `backend/`、`frontend/` 运行时代码。
5. 归档后 `openspec list` 不再显示 `trip-detail-schedule-timeline`。

## 10. 交付物

- `docs/superpowers/specs/2026-11-14-backlog-governance-design.md`（本文）
- `docs/superpowers/plans/2026-11-14-backlog-governance.md`
- `openspec/changes/backlog-governance/{proposal,design,tasks}.md` + `.openspec.yaml`
- `docs/nightly/backlog-review-2026-11-14.md`
- 重排后的 `docs/night-build-todo.md`
- `openspec/changes/archive/2026-11-14-trip-detail-schedule-timeline/`（归档）
