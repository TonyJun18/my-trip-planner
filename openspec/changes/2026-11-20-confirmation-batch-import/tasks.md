# Tasks — confirmation-batch-import

> TDD 执行顺序：先失败测试（Red），再最小实现（Green）。验证命令见各任务。

## 1. 分段解析纯函数（parse_email_batch）

- [ ] 1.1 **失败测试** `backend/tests/test_email_import_batch.py`：`parse_email_batch`——①`--- Forwarded message ---` 分隔两封 → bookings 合并两封条目；②`---------- Forwarded message ----------` 同；③多空行 + `发件人:` 行首分段；④无分隔符 → 与 `parse_email` 等价（单段）；⑤空段不报错跳过。运行 `cd backend && .venv/bin/python -m pytest tests/test_email_import_batch.py -x` 确认 Red
- [ ] 1.2 最小实现：`email_import.py` 增 `_split_segments(text)`（转发分隔正则 + 空行组启发）+ `parse_email_batch`（逐段 parse_email，空段容错）。运行 1.1 确认 Green
- [ ] 1.3 回归：`.venv/bin/python -m pytest tests/test_email_import.py -q` 单条路径零回归

## 2. 合并去重 + 来源段标注

- [ ] 2.1 **失败测试**（append 1.1 文件）：①同 provider+order_no 两封重复 → 只一条 + `dropped_lines=1`；②无码同 kind+标题+金额重复 → 去重；③非重复（同 provider 不同 order_no）→ 保留两条；④每条候选带 `source_segment`；⑤flagged_lines 记录来源段。运行确认 Red
- [ ] 2.2 最小实现：合并逻辑（有码：provider+order_no；无码：kind+title+amount）+ `source_segment` 字段 + dropped_lines 扩展语义。运行 2.1 确认 Green
- [ ] 2.3 专项回归：`.venv/bin/python -m pytest tests/test_email_import.py tests/test_email_import_batch.py -q` 全绿

## 3. 批量端点（batch 标志）

- [ ] 3.1 **失败测试**（API 层）：`POST /trips/{id}/email/import` `batch=true` 两封 → 200 合并去重候选；`batch=false`/缺省单封 → 与现状一致；批量不落库（无 TripBooking 产生）；超长 422 保持。运行确认 Red
- [ ] 3.2 最小实现：`api/v1/email_import.py` 加可选 `batch` 字段；`schemas/email_import.py` 补可选字段。运行 3.1 确认 Green
- [ ] 3.3 后端全套回归：`cd backend && .venv/bin/python -m pytest -q` 零失败

## 4. 前端批量入口

- [ ] 4.1 `ImportDialog.vue` 邮件 Tab：placeholder 补「可一次粘贴多封，转发分隔自动识别」；候选区显示来源段（第 N 封）徽标 + 去重合并提示。验证：`cd frontend && npm run build` 通过
- [ ] 4.2 i18n：`zh-CN.js`/`en-US.js` 邮件组补键（batchHint、sourceSegment、mergedCount 等约 5 键），`npm run check:i18n` 通过
- [ ] 4.3 手动：粘贴两封真实确认邮件（含重复订单）→ 候选合并去重正确

## 5. 端到端验证

- [ ] 5.1 真机：ImportDialog 邮件 Tab 粘贴转发的两封确认邮件 → 解析合并 → 候选勾选并入行程；重复订单只出现一次
- [ ] 5.2 归档：`openspec archive confirmation-batch-import` + `docs/night-build-todo.md` 登记完成项