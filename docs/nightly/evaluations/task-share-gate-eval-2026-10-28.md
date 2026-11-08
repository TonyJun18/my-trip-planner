# task-share-gate-eval 评估记录 · 2026-10-28

> 分享链接访问控制（候选评估 + 最小版实现）
> 来源：night-build-todo.md「2026-10-23 竞品分析追加」末条 + 2026-10-27 用户视角短板 A5 优先级上调

## 1. 评估背景

- **竞品实证**：PlanYourTrip 密码 collaborator 链接 → co-owner；WeTrip 等链接含邀请语义。
- **我们现状**：公开 `share_token` / `edit_token` 免登录访问，无密码保护；TTL / 吊销已有（share_lifecycle），缺「密码保护」最小可用项。
- **用户视角（2026-10-27 A5）**：公开链接转发不可控是用户可感知的防御性缺口 → 优先级上调为本批候选评估首项。

## 2. 方案评估：密码保护的三种实现路线

| 路线 | 成本 | 安全收益 | 结论 |
|---|---|---|---|
| A. 链接内嵌随机密码（`/share/{token}?pwd=xxx`） | 低 | 密码进 URL → 转发即泄露；无「输入密码」交互门槛 | ❌ 不采用（与分享链接转发可控性目标冲突） |
| B. **访问密码 + 短期免验凭证（本实现）** | 中 | 密码只在 header 传输；验证通过签发 HMAC 免验凭证（12h），访客一次输密码、后续免验；可组合 TTL/吊销 | ✅ 采用 |
| C. 令牌可撤销 + 重新签发（替代密码） | 低 | 已有 revoke 能力；但体验差（一次泄露即永久换链） | 作为密码保护之外的第二道防线保留 |

## 3. 设计决策

1. **密码存 PBKDF2 哈希，与登录密码同格式**（复用 `app.core.security.hash_password`）——不存明文，密码永不出现在响应体。
2. **密码与 TTL、吊销正交**：三套门禁独立叠加（share_tokens 表 `password_hash` 列新增，旧数据无哈希 → 完全向后兼容，不加密码不影响既有分享链接）。
3. **share / edit 令牌密码相互独立**（各管各的 `kind='share' | 'edit'`）。
4. **读取侧统一门禁**：`trip_service.get_trip_by_share_token / get_trip_by_edit_token`、`collab_service`（评论/投票）、`live_service`（行中）、`map_edit_service`（拖拽编辑）全部走 `share_lifecycle.verify_token_access`——单一门禁入口，无旁路。
5. **免验凭证**：`issue_gate_token` HMAC 签名（`exp.sig.token.kind`），绑定 token + kind + 过期时间，默认 12h；验证通过后前端可存内存/本地，后续请求带 `X-Share-Gate` header。
6. **错误语义**：未提供/密码错误 → `403 share_password_required`（前端据此弹密码框）；令牌不存在 → 404（不泄露存在性）。

## 4. API 契约

| 端点 | 方法 | 权限 | 说明 |
|---|---|---|---|
| `/api/v1/trips/{trip_id}/share/password` | POST | owner | `kind` = share / edit；`password` 非空设置、空串清除（幂等） |
| `/api/v1/trips/share/{token}/verify` | POST | 免登录 | 验证密码 → 签发 `X-Share-Gate` 免验凭证（12h） |
| 读取侧（share/edit 全链路） | — | 免登录 | 请求头 `X-Share-Password`（一次性）或 `X-Share-Gate`（免验凭证） |

响应中 `has_password`（布尔）出现在 lifecycle 查询中；密码本身绝不回传。

## 5. 实现状态

- **服务层/模型（工作区遗留，2026-10-28 00:30 前 worker 已写入，本夜核验质量后接管）**
  - `ShareToken.password_hash` 列（models/trip.py）
  - `share_lifecycle.verify_token_access / set_token_password / issue_gate_token / _verify_gate_token / GATE_TTL_SECONDS`
  - `trip_service`、`collab_service`、`live_service`、`map_edit_service` 读取侧全部透传 password / gate_token
  - `schemas/share_gate.py`（SharePasswordIn/Out、ShareVerifyIn/Out）
  - `trips.py` 读取侧 `_share_gate_headers` 依赖注入
- **本夜补齐**
  - `POST /{trip_id}/share/password`（owner 设置/清除）
  - `POST /share/{token}/verify`（访客验证 + 签发免验凭证）
  - `tests/test_share_gate.py` 9 例（设置/清除/owner 隔离/读取门禁/编辑独立/协作门禁/verify/免验凭证绑定）
  - 本文档

## 6. 测试结果

- `tests/test_share_gate.py`：9 passed（6.5s）
- 全套：520 + 9 = **529 passed**（本夜核验时 520 全绿，含遗留工作区改动）

## 7. 未覆盖 / 后续（记入 issues）

- ~~**前端**：分享管理面板尚未提供「设置密码」UI 与「输入密码」交互~~ → **2026-11-08 已闭环**：
  - owner 侧：分享设置弹窗每个令牌卡片新增「访问密码」行（状态标签 / 密码框 / 设置 / 清除），
    改完立即刷新生命周期；明文不进任何持久化。
  - 访客侧：`ShareView` 收到 `403 share_password_required` 时显示密码卡 →
    `POST /trips/{share|edit}/{token}/verify` 换 `gate_token` → 自动重试加载；
    密码错误就地提示；gate 存 `localStorage`（按 token），`http` 拦截器对
    `/trips/share|edit/{token}*` 自动附带 `X-Share-Gate`，WS 用 `?gate=`。
  - **安全细节**：密码门禁命中时**不走离线缓存降级**（缓存里是旧快照，会绕过密码）。
- **受邀编辑侧 verify 缺失（本次补）**：原实现只有 share 侧 verify，`kind='edit'` 设密码后
  受邀者无处解锁。新增 `POST /trips/edit/{token}/verify`（kind 绑定，凭证不可串用）+ 测试。
- ~~**WS 通道**：share/edit 的 WebSocket 订阅未做密码门禁~~ → **2026-11-08 已闭环**，
  并顺带修掉一个更底层的路由缺陷：
  - `ws.router` 原先被并进 `api_router`，真实路径成了 `/api/v1/ws/*`，而前端 `WS_BASE`、
    vite proxy、nginx `location /ws/`、README 契约全是 `/ws/*` → **所有 WS 握手 403、
    实时推送静默退化为轮询**（planner / collab / chat 三处）。现改为在 `app/main.py`
    根路径 include，并为 chat 补 `/ws/chat/{session_id}` 根路由。
  - `?gate=` 免验凭证已接入前端 `subscribeTripCollab`；不带 gate 的受保护令牌仍被拒（实测）。
- **审计写持锁事故（本次修）**：`share_lifecycle.touch_token_usage` 原先在调用方 session 里
  `flush()` 不提交；WS 端点为整条连接持有请求 session → `share_tokens` 行锁常驻 →
  同令牌的 `/verify` 与所有鉴权读永久排队（实测 `curl` 无响应、`pg_stat_activity` 出现
  `idle in transaction` + `Lock:transactionid`）。改为 `db.session_factory` 起独立 session
  写完立即 commit（失败仅 debug 日志），并在 WS 鉴权后 `db.commit()` 结束只读事务。
  回归测试：`test_usage_audit_does_not_hold_row_lock`（NOWAIT 抢锁 + 审计已落库）。
- **免验凭证吊销**：目前 gate_token 只能等 12h 自然过期；若需「改密码即吊销所有已发免验凭证」，可在 password_hash 变化时递增 salt 版本（本期未做，收益有限）。