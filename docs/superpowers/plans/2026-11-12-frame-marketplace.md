# 实现计划：旅拍相框市场（Frame Marketplace）

日期：2026-11-12
依据：`docs/superpowers/specs/2026-11-12-frame-marketplace-design.md` + OpenSpec change `frame-marketplace`（proposal/design/specs/tasks 已全部就绪并通过 validate）

## 执行策略

- 以 OpenSpec `tasks.md` 为约束与检查清单，按组推进，每组内 TDD（先失败测试 → 最小实现 → 绿）
- 验证证据先行：每个任务完成后用命令输出自证，未验证不报告成功
- 分支：`feature/frame-marketplace`（在主工作区直接开分支——backend `.env` 为 untracked 文件，worktree 中缺失会破坏测试运行，故不使用 worktree）
- 验收底线：全量 `uv run pytest`（453+ 新增）全绿 + 前端 vitest 通过

## 顺序（对应 OpenSpec 任务组）

1. 数据模型 + alembic 迁移 + 种子数据（组 1）
2. 兑换权益：失败测试 → frame_entitlement_service → frames 路由 → gen_codes.py（组 2）
3. 数据投影：失败测试 → frame_projection_service + 2 个 GET 端点（组 3）
4. AI 配文：失败测试（FakeLLM）→ frame_copy_service + POST copy（组 4）
5. 前端渲染器纯函数 TDD → renderer/templates/export（组 5）
6. 模板商店页 + 生成器弹层 + i18n（组 6）
7. 整程总结图（组 7，Phase 2）
8. 集成验证：全量 pytest + vitest + 手动端到端对照 spec Scenario（组 8）

## 关键实现约定

- 模型放 `app/models/framemarket.py`，路由挂 `/api/v1` 新文件 `frames.py`
- 兑换码只存 SHA-256；权益 (user_id, pack_slug) 唯一；错误语义 404/409/410 + 同用户重放幂等 200
- 投影仅含 checked 站点；owner 限定；空投影诚实返回
- 配文 LLM 主路径 + 模板兜底 + source 标注；无自动发布副作用
- 照片仅浏览器内存；导出 1242×1656 (3:4)；轨迹手绘风格化（零地图瓦片）
