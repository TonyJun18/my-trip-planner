# task-share-gate-eval 评估记录（2026-10-24）

> 背景：PlanYourTrip（2026）把 collaborator 链接升级为「密码 + co-owner」，
> 分享链接从「拿到 URL 即拿到内容」变成「URL + 口令双因子」。
> 我们：`share_token` / `edit_token` 双令牌，已有 TTL（0/1/7/30 天）+ 一键吊销 + 410/403 生命周期门禁
> （task-share-token-lifecycle），但**令牌本身是唯一凭证**——转发即扩散，无法只给某几个人看。
> 结论：**采纳最小版「可选密码锁」；co-owner 分级角色不做**。

## 一、成本边界评估

| 候选 | 需要的改动 | 成本 | 判定 |
|---|---|---|---|
| **可选密码锁（PBKDF2）** | `share_tokens.password_hash` + 迁移 + 门禁接线 + unlock 端点 + 解锁签名 | **低（~半天）** | ✅ **已落地** |
| 到期 / 一键吊销 | TTL 字段 + revoke 端点 + 读取侧 410/403 | — | ✅ 早已落地（10-11 lifecycle），本条无需重做 |
| co-owner 分级角色（owner/editor/voter/viewer） | 权限矩阵 + 全部写接口鉴权改造 + 邀请成员表 | 高（~3-5 天） | ❌ 不做（与「免登录轻协作」定位冲突，见 collab-democracy 评估） |
| 访问审计（谁在何时看了什么） | 访客身份体系（现为 token+IP+UA 匿名） | 中高 | ❌ 不做（免登录前提下的假审计比没有更糟） |

## 二、落地内容（最小版）

- **模型/迁移**：`share_tokens.password_hash`（`String(255)`，NULL = 未设锁，旧数据零影响）；
  `alembic f2a3b4c5d6e7`（Revises `e5b6c7d8e9f0`）。
- **哈希**：直接复用 `app.core.security.hash_password / verify_password`（PBKDF2-SHA256，
  与账号密码同一套参数与常量时间比较），**不新增密码学实现**。
- **门禁顺序**：令牌定位（不存在 404）→ 生命周期（过期 410 / 吊销 403）→ 密码（未解锁 422）。
  与既有信任语义一致，密码锁只是「生命周期之后追加的一道门」，不改变任何已有行为。
- **统一入口**：`share_lifecycle.load_trip_checking_password(db, token, kind, unlocked)`；
  `trips.py::_guard_token_access` 与 `map_edit.py` 的令牌版拖拽共用它，避免两套门禁漂移。
- **端点**：
  - `POST /api/v1/trips/{trip_id}/share/password`（owner 设/清锁，`password=""` 即清除，<4 字符 400）；
  - `POST /api/v1/trips/share/unlock`（免登录，校验密码 → 返回 24h HMAC 访客签名）；
  - 生命周期响应新增 `password_protected: bool`（前端判断是否需要弹密码框）。
- **访客签名**：`token::exp::HMAC-SHA256(secret 派生自 JWT_SECRET)`，请求头 `X-Share-Unlock` 携带。
  签名绑定具体令牌（A 行程的签名解不开 B 行程），伪造/过期一律回到 422 重新输密码。
  **刻意不带明文密码、不写 Cookie**：URL 与 Header 都可控，签名过期即失效。
- **覆盖面**：所有持令牌的免登录入口都在门禁内——只读读取、live 快照、评论列表/发表、投票列表/投票、
  事件流、受邀编辑读取、受邀站点改名/重排、行中打卡/跳过/顺延、受邀地图拖拽。
- **测试**：`tests/test_share_gate.py` 10 例——兼容（无锁放行）、设/清锁与 lifecycle 同步、
  7 个入口统一 422、错密码 403 → 正确密码换签名后全通道放行、签名跨令牌无效/伪造无效、
  edit 令牌同语义（含地图拖拽）、密码过短 400、未开放分享/非 owner 404、未知令牌解锁 404。
  全套 463 测试通过。

## 三、诚实边界（未做，已记录）

1. **前端未接线**：`ShareView` 没有密码输入框 + `localStorage` 存签名 + 带 `X-Share-Unlock` 重试的流程；
   owner 侧也没有「设锁」入口。当前为 API-only——被设锁的链接在 UI 里会落到通用错误提示。
   下一步（约 2-3h）：ShareView 捕获 422 `share_password_required` → 弹密码框 → `/share/unlock` →
   存 localStorage → api 层统一附头重试。
2. **无暴力破解限速**：unlock 端点没有按 token/IP 计数的失败退避。密码长度下限 4 字符 + 24h 签名，
   在「分享给朋友」场景够用，但公开传播的链接可被在线枚举。若开放公网需在反代层加 rate limit。
3. **解锁状态不随吊销/改密失效**：改密后旧签名（≤24h）仍有效。可接受（收窄窗口的代价是访客反复输密码），
   若需要严格语义，在签名 payload 里加 `password_hash` 指纹即可，一处 `create_guest_unlock` 改动。

## 四、后续重启条件

- 出现「分享链接被转发到公开群」的真实事故或用户投诉 → 补前端交互 + 反代限速；
- 需要按人授权（不同人不同权限）时，才立项 co-owner 分级角色，届时先做成员表再做权限矩阵。
