# Proposal

## Why

Everway 的行前整理核心差异之一是「把各渠道确认单转发到行程私有地址 → AI 归集成一份全组共享行程」（2026-11-20 竞品分析 §三 G2）。我们现状：`email_import.parse_email`（`services/email_import.py:196`）是**单条**粘贴文本解析（零凭证同构），一次只能粘一封确认邮件；用户订了机票+酒店+门票，要分别复制粘贴三封，且**无「多封合并归集」批次形态**——与 11-09 screenshot 批量 OCR 导入（≤12 张串行合并去重）形成断档：图片能批量，文本邮件不能。

私有邮箱地址归集（forward to private address）需邮件接收基础设施（域名 + MX + 收取），超出零凭证边界明确不做（本 change 显式 Non-Goal）。最小版 = 粘贴区多封确认邮件（分隔符/多段）→ 逐段复用 `parse_email` → 候选合并去重。

## What Changes

- 批量解析纯函数 `parse_email_batch(text, separator_hints=None)`：按分隔规则把整段文本切成多封邮件段 → 逐段调 `parse_email` → 结果合并（bookings 并集 + 疑似重复智能去重：同 provider+同 order_no/同标题+同金额 视为重复，只保留一封）。
- 分隔规则（确定性）：常见邮件转发分隔（`--- Forwarded message ---` / `---------- Forwarded message ----------` / 空行组 + 「发件人/From:」行首）识别分段；无分隔符则整段当一封（零破坏单条路径）。
- 端点多信封：`POST /trips/{id}/email/import` 请求体接受 `text` 内含多封（现有单条路径零改动），或新增 `batch: true` 标志走分段解析；响应结构不变（bookings/candidates/flagged_lines/dropped_lines），`dropped_lines` 语义扩展为「因合并去重被丢弃的条目数」。
- 前端：ImportDialog 邮件 Tab 提示「可一次粘贴多封」，批量结果候选合并展示（来源标注第 N 封）。
- **不做**：私有邮箱转发地址（域名/MX/收取）；Gmail OAuth；自动落库（仍是「解析是候选、落库是决定」两段式）。

## Capabilities

### New Capabilities

- `confirmation-batch-import`: 多封确认邮件批量粘贴解析与合并去重——分段识别、逐段解析、重复合并、候选合并透出。

### Modified Capabilities

<!-- 无：email_import 既有能力保持单条路径兼容 -->

## Impact

- **后端**：`services/email_import.py`（`parse_email_batch` 纯函数 + 分段识别器）、`api/v1/email_import.py`（batch 标志可选）、`schemas/email_import.py`（可选字段）。测试：`tests/test_email_import.py` 增批次用例 + 新 `tests/test_email_import_batch.py`。
- **前端**：`ImportDialog.vue` 邮件 Tab（批量提示 + 候选来源标注）、i18n 键。
- **零破坏**：单条路径兼容（无分隔符 = 原行为）；`parse_email` 签名不动。
- **依赖**：零新依赖（纯文本分段 regex）。