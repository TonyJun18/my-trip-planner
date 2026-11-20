# Design

## Context

- 既有资产：`email_import.parse_email`（`services/email_import.py:196`，纯规则单条解析：`_detect_kind`/`_extract_code`/`_extract_amount`/`_extract_datetime`/`_extract_route`/`_extract_hotel_name`/`_extract_activity_name` + `EmailImportResult(bookings, candidates, flagged_lines, dropped_lines)`）；
- 既有先例：11-09 截图批量导入（≤12 张串行 OCR、按站点名合并去重）——「批量 + 合并去重」已有成熟范式。
- 缺口：文本邮件单条、无批次形态、无来源标注。
- 约束：零凭证 / 零 LLM / 纯文本规则 / 不自动落库（两段式）/ 单条路径零回归。

## Goals / Non-Goals

- **Goals**：多封分段解析、合并去重、来源段标注、batch 端点兼容、前端批量入口。
- **Non-Goals**：私有邮箱转发（域名/MX）；Gmail OAuth；自动落库；附件/图片 OCR 联动。

## Decisions

### D1. 分段识别用转发分隔符正则 + 空行组启发
主分隔符：`^---* Forwarded message ---*$`（大小写不敏感）与 `^---------- Forward message ----------$`（Gmail/Outlook 变体）；兜底：三连空行 + 行首 `发件人|From:`。无命中 → 单段（零破坏）。空段容错跳过。

### D2. 去重规则：有码用码、无码用「kind+title+amount」
与 booking 幂等键（provider+order_no）对齐；无码用弱指纹（同 kind+同标题+同金额）——宁可漏合不误合（误合并会吞掉真实订单）。`dropped_lines` 计数扩展：原语义（超上限丢弃）保留，新增「因重复去重丢弃」。

### D3. 端点加可选 `batch` 标志，不做新端点
`POST /email/import` 请求体加 `batch: bool = false`——单条路径零改动、批量走同一端点。响应结构不变（契约面最小）。

### D4. 前端来源段标注做轻量徽标
候选区每条加「第 N 封」小徽标（`source_segment`），重复合并提示「已合并 N 条重复」。不引入分组折叠等重交互。