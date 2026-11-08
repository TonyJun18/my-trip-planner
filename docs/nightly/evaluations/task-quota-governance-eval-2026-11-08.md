# 评估记录 · 登录用户额度治理（task-quota-governance-eval）

- 日期：2026-11-08
- 类型：候选评估 + 最小版实现（backend + frontend）
- 来源：docs/nightly/competitive-analysis/2026-10-30.md（免费 AI 帮助限额观察）、2026-11-07.md（Hilton CIO tokenomics）、2026-11-08.md（Wanderlog 免费档 AI 5–10 条封顶）
- 结论：**评估通过，采用方案 B（计数 + 软提示，零表零迁移）已落地**；方案 C（硬配额/限流）与 D（匿名 IP 限流）记录为「需用户立项」，不在本版实现。

## 1. 问题与行业事实

我们当前对「一个登录用户能规划多少次」**完全没有约束**：`grep -rln "rate_limit\|RateLimit\|slowapi" backend/app` 在本次改动前**零命中**。10-15 的 guest-trial 评估只拦住了「匿名」滥用，登录用户仍是敞口——一次登录可以用脚本刷规划，每次规划是多 Agent 多轮 LLM 调用。

2026-11 的行业侧已经给出两个明确的参照：

| 参照 | 事实 | 含义 |
|---|---|---|
| **Wanderlog** | 免费档 AI 助手**按条数封顶**（2026-02 实测每趟 5 条；2026-10-05 新会话显示「10 free messages left」）；**无限 AI 是 Pro（$39.99/年）**；但**行程数与协作人数永不限制**（help center 明确） | 限制 LLM 调用，不限制用户的数据与协作 |
| **Hilton CIO**（Skift，2026-11-07） | 公开谈「tokenomics」——建 AI Trip Planner 时如何治理 LLM 成本 | 连巨头都在算这笔账 |

我们的成本压舱石已经存在（灵感推荐 / 时间校验 / 体力系数 / 预算估算全是规则库，$0 LLM），但「规划」这条主链天然要花 token，且没有刹车。

## 2. 成本结构（一次规划 ≈ 多少次调用）

按 `agent/agents.py` 的编排：6 个采集 Agent 并行（景点/天气/酒店/餐饮/大交通/折扣）→ 1 次 Planner 整合 → Critic 质检（不过审最多再 2 轮重生成）→ 定稿阶段确定性步骤（预算/时间/体力/PlanB 全是规则库，零 LLM）。即**单次规划 ≈ 8–11 次 LLM 调用**，用户改一次行程再 +2–4 次。

所以「日 10 次规划」≈ 100 次调用量级——对自托管单实例是可承受的参考线，而不是计费门槛。

## 3. 方案矩阵

| 方案 | 内容 | 成本 | 风险 | 结论 |
|---|---|---|---|---|
| **A 不治理** | 现状，无任何计数 | 0 | 登录用户脚本刷规划；provider 账单不可控 | 不选 |
| **B 软提示**（本版） | `GET /planner/quota` 返回「最近 24h 次数 + 参考上限 + 最早释放时间」；前端在提交按钮下方显示一行弱提示，**达到上限转琥珀色但仍可提交** | 1 个 service（约 90 行）+ 1 个只读端点 + 1 个 schema + 前端 1 个 ref + 2 处 i18n；**零表、零迁移、零新依赖** | 只是提示，防不住恶意刷量 | ✅ **采用**（先把「量」变成可见事实） |
| **C 硬配额/限流** | 配额表（用户/日或滚动窗口）+ 429 + 前端拦截 + 管理员配置 | 新表 + 迁移 + 错误语义 + 前端状态机 | 自托管用户被自己的额度卡住；阈值没有实测依据就容易误伤 | 需用户立项（本版预留：`quota_service.SOFT_LIMIT` 单点可调，加硬判定只需一个 `if`） |
| **D 匿名/IP 限流** | 与 10-15 guest-trial 重启同源（IP+配额表+过期清理） | 中 | 与 B/C 重复建设 | 随 guest-trial 一起立项 |

## 4. 已实施（最小版）

**后端**

- `app/services/quota_service.py`
  - `summarize(used, limit, window_hours, resets_at)` —— 纯函数，`remaining` 下限 0、`soft_limit_reached = used >= limit`；
  - `snapshot(db, owner, now=None)` —— 单条聚合查询 `count(id)` + `min(created_at)`，只统计**本人 + 滚动 24h 窗口**内的 `plan_tasks`；`resets_at = 最早一次 + window`（滚动窗口语义，不依赖时区）；
  - 常量 `WINDOW_HOURS = 24`、`SOFT_LIMIT = 10`（行业参照区间 5–10 的上沿，自托管更宽松）。
- `app/schemas/agent.py::PlanQuotaOut`（used / limit / window_hours / remaining / soft_limit_reached / resets_at）。
- `GET /api/v1/planner/quota`（登录必需）——**只读，不拦截**；提交端点 `POST /planner/plan` 未加任何 gate（本版边界，见 §5）。

**前端**

- `api/modules/planner.js::getPlanQuota`（`silent: true`）。
- `api/http.js`：响应拦截器支持 `config.silent` —— 旁路请求（有则显示、无则静默）不再弹全局错误提示；401 的会话清理逻辑不变。
- `PlanWizard.vue`：`onMounted` 静默拉取（**未登录不发请求**——否则 401 拦截器会把访客直接踢到 `/login`）；提交成功后本地 +1（避免二次请求）；提交按钮下方一行文案——常态弱色、达阈值转琥珀色并明说「仍可继续，本实例不额外收费」。

**验收**

| 项 | 结果 |
|---|---|
| `tests/test_quota_service.py` | **9 passed**：summarize 三态（低于/达到/超过 + 负数与自定义窗口）、快照 owner 隔离与窗口边界（23h 计、25h 不计）、`resets_at` 计算、空用户、API 401、API 反映真实次数、达阈值置位、**额度耗尽后 `POST /planner/plan` 仍 202 入队**（monkeypatch 执行器，不跑真 Agent） |
| 前端 | `npm run build` 4.38s 通过；`npm run check:i18n` 923 键 × 2 语言无重复无缺失 |
| 全量回归 | 见本日后端全量 pytest 结果（见提交说明 / 夜报） |

## 5. 边界与后续触发条件

1. **本版明确不拦截**：软阈值只驱动文案。理由——硬限流是产品策略（自托管 vs SaaS、免费 vs 付费），必须由用户决策；且当前没有真实用量分布，阈值会拍脑袋。
2. **升级为硬限流的触发条件**（满足任一即立项）：① 任一账号 24h 规划 > 50 次；② provider 月账单超过预设预算；③ 对外开放注册（不再只服务自托管者）。落地路径：`quota_service` 增加 `enforce()` → planner 端点 `if snapshot["soft_limit_reached"]: raise RateLimitedError(429)`，前端复用同一份数据把按钮换成「额度已满，X 后释放」。
3. **不做「按次收费」**：与本项目「规划层中立、不碰钱」的立场冲突（见 `task-booking-neutrality-eval-2026-11-08.md`）。
4. **口径一致性**：`SOFT_LIMIT` 是参考线而非承诺，前端文案已写明「参考上限 / soft cap」，不出现「免费额度」这类承诺性表述。
