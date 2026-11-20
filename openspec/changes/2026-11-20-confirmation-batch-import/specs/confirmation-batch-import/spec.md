# confirmation-batch-import Specification

## Purpose

把「一次只能粘一封确认邮件」升级为「一次粘多封」：粘贴区整段文本按转发分隔符切段，逐段复用现有
`parse_email` 规则解析，结果合并去重后作为候选透出。零凭证、零 LLM、纯文本规则；
私有邮箱转发地址（域名/MX）明确不做。

## ADDED Requirements

### Requirement: 多封文本分段解析

系统 SHALL 提供 `parse_email_batch(text)` 纯函数：识别常见邮件转发分隔符（`--- Forwarded message ---`、
`---------- Forwarded message ----------`、多空行 + `发件人/From:` 行首）将文本切成多段；
无任何分隔符时 SHALL 整段视为一封（与现有单条路径行为一致）。
每段 SHALL 复用 `parse_email` 逐段解析，结果合并为单一 `EmailImportResult`。

#### Scenario: 转发分隔多封解析

- **WHEN** 粘贴文本含 `--- Forwarded message ---` 分隔的两封确认邮件（一封航司、一封酒店）
- **THEN** 返回合并结果：bookings 含两封的条目，candidates 合并
- **AND** 每段独立解析（一封的失败/空段不影响另一封）

#### Scenario: 无分隔符零破坏

- **WHEN** 粘贴单封邮件（无转发分隔符）
- **THEN** 行为与现有 `parse_email` 完全一致（整段一封）

### Requirement: 合并去重

批量结果 SHALL 对疑似重复条目去重：同 provider + 同 order_no（有码）视为重复；无码条目
同 kind + 同标题 + 同金额视为重复。重复条目 SHALL 只保留一封（保留最先出现的），并在
`dropped_lines` 计数（扩展语义：包含因合并去重丢弃的条目数）；`flagged_lines` 标注每条的来源段号。

#### Scenario: 重复条目去重

- **WHEN** 两封邮件都含 provider=ctrip、order_no=BK12345678 的酒店条目
- **THEN** 合并结果只有一条该酒店条目，`dropped_lines=1`

#### Scenario: 来源段标注

- **WHEN** 三封邮件解析出 3 条候选
- **THEN** 每条候选带 `source_segment`（1/2/3），`flagged_lines` 记录异常段

### Requirement: 批量端点兼容单条

`POST /trips/{id}/email/import` SHALL 接受可选 `batch: bool`（默认 false）；`batch=true` 时按
`parse_email_batch` 处理，`batch=false`（或缺省）时按现有单条 `parse_email` 处理——响应结构
（bookings/candidates/flagged_lines/dropped_lines）两者一致。批量解析 SHALL NOT 自动落库
（仍是「解析是候选、落库是决定」两段式）。

#### Scenario: batch=true 走分段

- **WHEN** owner 以 `batch=true` 提交含两封邮件的文本
- **THEN** 返回合并去重后的候选（含来源段标注），不落库

#### Scenario: batch=false 单条兼容

- **WHEN** owner 以旧契约（无 batch 字段）提交单封邮件
- **THEN** 行为与现状完全一致（单条路径零回归）

### Requirement: 前端批量提示与来源展示

ImportDialog 邮件 Tab SHALL 提示「可一次粘贴多封确认邮件（转发分隔自动识别）」；批量解析结果
SHALL 展示合并去重后的候选，并标注来源段（第 N 封）；去重丢弃数 SHALL 如实提示。

#### Scenario: 前端批量展示

- **WHEN** 用户在邮件 Tab 粘贴两封邮件并提交
- **THEN** 候选区展示合并结果，重复条目只剩一条，提示「已合并 N 条重复」

