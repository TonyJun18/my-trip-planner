# Proposal

## Why

Wonderplan 把「结构化饮食过滤器」（Halal / Vegan / 素食等）直接做进表单（comparisonmath 2026-11 横测，11-18 竞品分析 §三 G1）；我们现状：`prompts.py` 餐饮专家已支持口味/菜系偏好**自由文本**（`_FOOD_TMPL`：用户给「川菜/海鲜/本地小吃/素食」，转 1-2 关键词），PlanWizard 偏好 chips（`preferenceKeys` 10 项：food/nature/history/...）**无结构化饮食选项**——想表达「不吃猪肉」「素食」只能靠打字，且自由文本容易被忘记/拼错，导致餐饮检索质量不稳定。这是「结构化输入」第一块：把高频饮食约束做成 chips，预填为既有偏好关键词，零后端大改。

## What Changes

- PlanWizard 新增「饮食偏好」chips 组（独立于现有「兴趣偏好」组）：
  - 选项（初始 6 个高频）：素食 vegetarian / 清真 halal / 海鲜忌口 no-seafood / 不吃猪肉 no-pork / 无麸质 gluten-free / 无特别 none（默认选中 none，选具体项时取消 none）。
  - 每组 chip 关联一个**关键词映射**（复用 prompts 既有转换语义）：vegetarian →「素食」、halal →「清真」、no-seafood →「忌口 海鲜」（或「不吃海鲜」）、no-pork →「不吃猪肉」、gluten-free →「无麸质」。
  - 选中 chips 在提交时合并进既有 `preferences` 的饮食维度：新增 `dietary` 表单字段（数组），提交时随请求发送；后端 PlanRequest 解析后注入 `_FOOD_TMPL` 的口味偏好段（与既有 freeform 偏好合并，去重）。
- 后端小改（零迁移）：`PlanRequest` 增可选 `dietary: list[str]`（keyword 形式）；`agents.py` 组装 food 偏好文本时并入（复用 `preference key → 中文关键词` 映射表扩充）；若后端零改动也能达成（纯前端把 dietary 映射为 preferences 里的 freeform 文本），则采用后者（见 Design D2）。
- i18n：`zh-CN.js`/`en-US.js` 补键（dietary 组标题 + 6 项 label）。
- **不做**：过敏/疾病级医疗语义（免责：只做口味偏好，不做医疗建议）；后端新表/迁移；LLM 改动；食谱级定制。

## Capabilities

### New Capabilities

- `dietary-filter-chips`: 结构化饮食偏好 chips——素食/清真/海鲜忌口/不吃猪肉/无麸质，映射为既有口味关键词进餐饮检索。

### Modified Capabilities

<!-- 零后端大改取决于 D2 决策：若纯前端映射则无后端改动 -->

## Impact

- **前端**：`PlanWizard.vue`（dietary chips 组 + 提交并入）、`locales/*.js`（约 7 键 ×2）。
- **后端**（若 D2 走方案 B）：`schemas/__init__.py` PlanRequest 增可选字段 + `agents.py` 偏好组装一处。
- **零破坏**：`preferences` 既有 10 项不动；dietary 全部可选；无迁移。
- **依赖**：零新依赖。
- **测试**：纯前端改动以 build + i18n 校验为主；后端若有改动则 1 个测试文件（dietary 并入 → food 偏好文本含关键词）。