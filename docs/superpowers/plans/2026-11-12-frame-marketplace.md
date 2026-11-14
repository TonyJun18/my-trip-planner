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

## 交付结果（2026-11-14）

### 测试证据
- 后端全量：`cd backend && uv run python -m pytest tests/ -q` → **1118 passed**（含 5 个 frames 专项文件 23 项 + 端到端 1 项）。
- 前端：`npm run test` → **20 passed**（布局纯函数 15 + 水印/配文 5）；`npm run build` 成功；`node scripts/check-i18n.mjs` → 1239 keys × 2 语言无缺失。
- 迁移：`alembic upgrade head` → `downgrade -1` → `upgrade head` 往返成功；种子 8 模板（2 免费）/ 2 付费包。

### 浏览器烟测（Playwright + 系统 Chrome，1440×1000）
- 商店页：2 个付费包、2 套免费模板示例 canvas 正常渲染（PNG data 131KB / 119KB）。
- 单日卡生成器：打开正常，6 套付费模板带 locked 徽标，隐私提示存在，预览 canvas 98KB。
- 选本地照片后画布变化（98,282 → 139,646 bytes）；导出 PNG 104,718 bytes。
- **选图与导出期间后端请求数 = 0**（照片不出设备的网络层证据）；无页面未捕获异常、无非预期 HTTP 错误。

### 归档
- `openspec archive frame-marketplace --yes` → `openspec/changes/archive/2026-11-14-frame-marketplace`，spec 合入 `openspec/specs/frame-marketplace/spec.md`（6 requirements）。
- README 已补「旅拍相框市场」功能段与 8 条 frames API；测试数基线更新为 1117/1118。

### 遗留（非阻塞）
- 付费模板的前端渲染理论上可被调试绕过（已在 design.md 记为接受风险；后续服务端高清导出可收紧）。
- 邮件的兑换码发放与退款/权益吊销运营流程在站外（爱发电等）完成，站内只做兑换与对账语义。
