# Tasks

## 1. 数据模型与迁移（Phase 1 基础）

- [ ] 1.1 新建 `app/models/framemarket.py`：FrameTemplate / FramePack / RedemptionCode（code_hash 唯一）/ FrameEntitlement（(user_id, pack_slug) 唯一约束），注册进 `app/models/__init__.py`；验证：pytest 收集无误
- [ ] 1.2 alembic 迁移：4 张新表 + `trip_days.day_note`（可空）；验证：`uv run alembic upgrade head` 与 `downgrade -1` 往返成功
- [ ] 1.3 种子数据迁移：2 套免费模板 + 2 个付费包各 3 套模板（slug/theme/layout_config/price_cents）；验证：upgrade 后 SQL 查询目录行数正确

## 2. 兑换权益服务与 API（TDD：先写失败测试）

- [ ] 2.1 先写失败测试 `tests/test_frame_entitlement.py`：有效码首次兑换、同一用户重放幂等 200、他人已用 409、码不存在 404、吊销 410、权益按用户隔离、事件流记录 frame_pack_redeemed；运行确认全部失败
- [ ] 2.2 实现 `app/services/frame_entitlement_service.py`（SHA-256 比对、幂等写入、错误码语义）；运行 2.1 测试确认通过
- [ ] 2.3 新路由 `app/api/v1/frames.py`：GET /frames/catalog（免登录，带 locked 标注）、GET /frames/entitlements、POST /frames/redeem；注册进 main 路由；验证：pytest 通过 + /docs 可见新端点
- [ ] 2.4 兑换码生成脚本 `scripts/gen_codes.py`（明文输出即弃、哈希入库、支持指定包与数量）；验证：生成 10 个测试码 → 兑换 1 个成功 → 重放/他兑/错码语义符合 spec

## 3. 数据投影 API（TDD）

- [ ] 3.1 先写失败测试 `tests/test_frame_projection.py`：单日投影仅含 checked 站点（坐标/名称/天气/备注/day_note）、空日返回空投影标识、非 owner 403/404、总结图投影聚合各日 + 全程统计且空日跳过；运行确认失败
- [ ] 3.2 实现 `app/services/frame_projection_service.py` + GET /trips/{trip_id}/frames/{day_id}/data + GET /trips/{trip_id}/frames/summary/data；运行 3.1 确认通过

## 4. AI 配文服务（TDD，FakeLLM）

- [ ] 4.1 先写失败测试 `tests/test_frame_copy.py`：FakeLLM 成功路径 source=llm、LLM 失败降级 source=template、兜底失败返回趣事原文+固定话题、channel xhs/moments 区分；运行确认失败
- [ ] 4.2 实现 `app/services/frame_copy_service.py` + POST /trips/{trip_id}/frames/{day_id}/copy（owner 限定）；运行 4.1 确认通过

## 5. 前端渲染器与模板注册表

- [ ] 5.1 新建 `frontend/src/frames/`：renderer.js 绘制管线（drawBackground/drawPhotoGrid/drawRoute 球面投影+虚线+编号节点/drawMeta/drawLockWatermark）、templates.js 注册表与后端 slug 对齐、export.js（PNG 下载 + 配文复制）；验证：vitest 覆盖纯函数部分（槽位布局计算、坐标投影、水印换行）通过
- [ ] 5.2 布局/轨迹/水印纯函数单测先于实现（TDD）；验证：先红后绿

## 6. 前端页面与入口

- [ ] 6.1 模板商店页 `FrameStoreView`（路由 /frames）：免费/付费分栏、示例小样、兑换码入口（错误文案区分 404/409/410）、未登录引导注册；验证：本地 dev 手动走通兑换→解锁→locked 标注刷新
- [ ] 6.2 单日卡生成器弹层：选模板 → 本地选照片（File API 内存处理）→ 填/改趣事（Stop.notes / day_note）→ 实时预览 → 导出 PNG + 复制配文；入口在今日视图打卡完成态与行程详情每日一行，无打卡数据置灰提示；验证：手动走通全流程，Network 面板确认无照片上传请求
- [ ] 6.3 i18n：新增键 zh/en 双语 + Element Plus locale 联动；验证：切换语言无缺键

## 7. 整程总结图（Phase 2）

- [ ] 7.1 渲染器多日布局 + 全程轨迹串联 + 统计水印；入口在行程详情定稿态；验证：手动生成一张总结图，空日自动跳过
- [ ] 7.2 总结图配文复用 frame_copy（channel 扩展）；验证：vitest/pytest 相关用例通过

## 8. 集成验证（系统级）

- [ ] 8.1 全量测试 `uv run pytest` 453+ 新增全部通过（FakeLLM，不耗 token）；前端 `npm run test` 通过
- [ ] 8.2 端到端手动验收：兑换 → 解锁 → 生成单日卡（照片/轨迹/趣事/配文）→ 导出 → 未购模板水印预览 → 整程总结图；对照 specs/.../spec.md 每条 Scenario 核对

## Workflow follow-up

- OpenSpec archive 流程归档本 change（代码、测试、规范对齐后）
- 更新 README 功能清单与 API 一览（frames 相关条目）
- 如存在 `.superpowers-memory/`：更新 CURRENT_STATE.md 并追加 session journal
