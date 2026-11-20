# dietary-filter-chips Specification

## Purpose

在规划表单提供结构化饮食偏好 chips（素食/清真/海鲜忌口/不吃猪肉/无麸质），把高频饮食约束从
自由文本变成一键选择，并映射进既有餐饮检索的口味偏好关键词。零后端大改优先、零迁移、
纯前端可达则后端不动。

## ADDED Requirements

### Requirement: 结构化饮食 chips 组

PlanWizard SHALL 提供独立的「饮食偏好」chips 组（与既有「兴趣偏好」组并列）：
选项包括 素食 vegetarian / 清真 halal / 海鲜忌口 no-seafood / 不吃猪肉 no-pork / 无麸质 gluten-free，
以及默认项「无特别 none」。初始状态 SHALL 选中 none；选择任一具体项 SHALL 自动取消 none；
再次点击已选项取消。

#### Scenario: 默认无特别

- **WHEN** 用户打开 PlanWizard（未触碰饮食组）
- **THEN** none 选中，其余未选

#### Scenario: 单选互斥 none

- **WHEN** 用户点击「素食」
- **THEN** 素食选中、none 取消；再点素食 → 素食取消、none 恢复选中

### Requirement: 多选与关键词映射

用户 SHALL 能同时选择多个具体饮食项（none 与具体互斥，具体项之间可多选）。每个具体项 SHALL
映射为既有餐饮检索口味关键词：vegetarian →「素食」、halal →「清真」、no-seafood →「不吃海鲜」、
no-pork →「不吃猪肉」、gluten-free →「无麸质」。提交时 SHALL 把选中项映射为关键词，并入
餐饮偏好（与用户自由文本合并、去重）。

#### Scenario: 多选映射合并

- **WHEN** 用户选「素食 + 不吃海鲜」且自由文本写了「川菜」
- **THEN** 提交的餐饮偏好含「素食、不吃海鲜、川菜」（无重复，none 不映射）

#### Scenario: none 不产生关键词

- **WHEN** 用户保持 none（或取消所有具体项）
- **THEN** 餐饮偏好不含饮食关键词（与现状一致，零变化）

### Requirement: 后端并入偏好

后端规划请求 SHALL 接收饮食关键词（零迁移优先：并入既有 preferences/freeform 文本；若需
PlanRequest 字段则可选）。`_FOOD_TMPL`（或等价组装）的「口味/菜系偏好」段 SHALL 包含映射后的
饮食关键词，与用户自由文本同权（餐饮 agent 按关键词检索真实餐厅）。

#### Scenario: 检索含饮食约束

- **WHEN** 行程请求含 dietary 关键词「清真」
- **THEN** 餐饮检索 agent 的口味偏好输入含「清真」，检索关键词含清真/清真美食

### Requirement: i18n 双侧齐

新增键（组标题 + 6 项 label + 提示文案）SHALL 在 `zh-CN.js` 与 `en-US.js` 双侧存在且对齐；
`npm run check:i18n` 零失败。

#### Scenario: 语言切换不丢失

- **WHEN** 用户选中「素食」后切换语言 zh→en
- **THEN** 选中态保留（内部 key 不变），label 变为 Vegetarian

