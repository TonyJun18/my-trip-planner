# Design

## Context

- 既有资产：`PlanWizard.vue` 偏好 chips 体系（`preferenceKeys` 10 项 + `prefLabelKeyMap` + `prefEmoji` + `togglePref` 互斥逻辑，L228-249）、`prompts.py _FOOD_TMPL`（L146-151：口味/菜系自由文本 → 关键词 → search_foods）。
- 缺口感：结构化饮食选项（用户无法一键表达「素食/清真」）。
- 约束：零迁移优先 / 不重构 LLM / 不与既有偏好冲突 / 免责（非医疗）。

## Goals / Non-Goals

- **Goals**：dietary chips 组 + 关键词映射 + 提交并入 + i18n。
- **Non-Goals**：医疗/过敏语义；新表/迁移；提示词重构；食谱级定制。

## Decisions

### D1. chips 选项 6 个（5 具体 + 1 none），none 与具体互斥
初始覆盖高频饮食约束（素食/清真/海鲜忌口/不吃猪肉/无麸质），none 默认选中保零变化。具体项之间可多选（用户可能同时素食+不吃海鲜）。互斥逻辑复用 `togglePref` 模式（splice + push）。

### D2. 后端按 key 解析实证 → 采用方案 B（PlanRequest 增 dietary 字段）
核验（2026-11-20）：`PlanWizard.vue` L341-343 提交契约「偏好传稳定 key（后端 preference_keys_to_keywords 按 key 解析，不再依赖语言 label）」——纯前端把中文关键词塞进 `preferences` 会被当作未知 key 静默丢弃。**方案 A（纯前端映射）不成立**，采用方案 B：
- `PlanRequest` 增可选 `dietary: list[str]`（key 形式：vegetarian/halal/no-seafood/no-pork/gluten-free）；
- `agents.py` 组装餐饮偏好段时并入（新增 `dietary_keys_to_keywords` 映射表：素食/清真/不吃海鲜/不吃猪肉/无麸质，与 `preference_keys_to_keywords` 同构）；
- 后端测试 1 文件（dietary 并入 → food 偏好文本含关键词）、无迁移。

### D2bis. none 映射 null，绝不产生「无特别」关键词
none 选中 = 与现状完全一致（不污染检索）；具体项全部取消自动恢复 none（零状态残留）。

### D4. 免责口径：仅口味偏好
UI 上加一行 hint（「饮食偏好将用于餐饮推荐，不构成医疗/过敏建议」），与「诚实口径」哲学一致——避免把素食 chips 误解为过敏保障。