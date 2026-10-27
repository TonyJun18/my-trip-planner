# task-human-escalation-eval 评估记录 · 2026-10-28

> 候选评估：人工兜底最小版（backend+frontend）
> 对应 todo：`task-human-escalation-eval`
> 结论：**可行（最小版）** —— 派生标记 + 评审列表 API + backend 测试；前端入口留接线窗口

## 1. 问题背景

- 当前降级链以「结构化降级响应」收尾（Critic 失败 → `degraded` 通过；达最大评审轮 → 强制定稿 `finalized`），**无人工评审入口**。
- OTA 有真人定制师场景（低置信 / 反复修订失败），我们直接放弃。
- 需求：低置信（Critic 得分低 / 修订连续失败）行程打 escalated 标记 + 结构化失败摘要 + owner 可查评审队列（自托管者自行接人工）。

## 2. 现状盘点（代码核验）

| 信号 | 已有载体 | 消费者 |
|---|---|---|
| Critic 得分 / 是否通过 | `plan.quality.score / passed` | 前端质检卡（展示） |
| 达上限强制定稿 | `plan.quality.finalized=true` | 前端质检卡（展示） |
| 修订复核失败（无 fix） | `revise_service._revise_qa_loop` → `quality.passed=False` | ReviseOut 透出 |
| Critic 失败降级 | `critic_agent` → `{"status":"degraded"}` | 降级通过，绝不阻断 |
| driving 未通过但定稿 | `plan.driving.passed=false` + `plan.warnings` | 前端告警 |

**关键发现**：escalation 所需信号（finalized / passed=false / degraded）**已全部存在**于 `TripPlan.plan_data.quality`——只是**没有消费者**：没有查询端点、没有标记透出、owner 无从知晓自己的行程被强制定稿。

## 3. 方案对比

| 方案 | 成本 | 说明 |
|---|---|---|
| A. 新表 `trip_escalations` + 状态机 | 高 | schema 演进 + 迁移 + 生命周期管理（谁来关单？）——过度设计 |
| B. **派生标记（零 schema）** | 低 | escalation = 从 plan.quality 派生（finalized / passed=false / degraded）；列表 = 现查现算；无新表无迁移。自托管者接人工 = 拿到列表即可自行处理（API 已给） |
| C. 维持现状关单 | 零 | 但信号已存在而无消费者，浪费；且与「人工兜底」需求直接冲突 |

**选择 B**：零凭证、零迁移、零生命周期管理负担，正好嵌入现有「诚实标注」哲学（basis 标注，不假装有真人）。

## 4. 实现（最小版）

### 4.1 派生判定（纯函数，可测）

```python
# app/services/escalation_service.py
def escalate_from_quality(quality: dict | None) -> bool:
    """plan.quality → 是否需要人工复核。
    - finalized=true（达最大评审轮强制定稿）
    - passed=false（Critic 未通过 / 修订复核未通过）
    - degraded=true（Critic 调用失败降级通过——健康风险信号）
    """
    if not quality:
        return False
    if quality.get("finalized"):
        return True
    if quality.get("passed") is False:
        return True
    if quality.get("degraded"):
        return True
    return False
```

低置信阈值：`score < 80` 且 `passed=false` 已含在 passed 判定；不额外用分数阈值（避免把「通过但分不高」误报）。

### 4.2 评审列表 API（owner）

```
GET /api/v1/trips/escalations
→ { items: [ { trip_id, destination, title, quality, escalated_at(plan created_at), summary } ], total }
```

- 仅当前 owner；查该用户全部 Trip → 每个 trip 的最新 TripPlan → `escalate_from_quality` → 过滤
- 结构化失败摘要 = `quality.summary`（Critic 最后总结）+ `quality.issues[:5]`（问题清单）
- 路由顺序：放在 `/trips/gallery` 之后、`/{trip_id}` 之前（避免被路径参数吞）——与 `GET /trips/gallery` 同策略

### 4.3 escalated 标记透出（TripOut）

- `TripOut` 增加 `escalated: bool = False`；`trip_to_out` 时从最新 plan 的 quality 派生
- 详情页前端可直接消费展示「需人工复核」徽标

### 4.4 测试

- `escalate_from_quality` 纯函数：finalized / passed=false / degraded / 正常通过 / quality=None 五路径
- API：owner 列表含 escalated 行程、排除正常行程、他人不可见、无 plan 不报错

### 4.5 前端入口（接线窗口）

- 最小版后续接线：TripDetailView 质检卡在 `plan.quality.finalized || plan.quality.passed===false` 时显示「建议人工复核」提示条
- 本夜窗口：若 build 时间允许则加；否则记接线窗口（与 price-realism-eval 前端候选卡同款处理）

## 5. 风险与边界

- **不假装有人**：escalated 只表示「建议人工复核」，不自动发通知、不阻塞任何流程（与「绝不阻断」哲学一致）
- **派生而非存储**：quality 一旦更新（重新规划/修订）escalation 状态自然翻新——无需手动关单
- **owner 隔离**：评审列表严格 owner 过滤（与 trip_service 同语义）；不暴露他人行程
- **性能**：列表 = owner 的 trips N + 每 trip 最新 plan 一次查询（selectin 预载），数据量级（个人行程）可忽略
- **与 task-trip-rating-signal 边界**：rating 是「信任信号」（画廊透出），escalation 是「质检兜底」（owner 自省），不重叠

## 6. 验收对照

- [x] 评估记录（本文档）
- [x] escalated 标记（派生，TripOut 透出）
- [x] 评审列表 API（GET /trips/escalations，owner 隔离）
- [ ] 前端入口（接线窗口，视 build 窗口）
- [x] 测试覆盖（纯函数 + API）
- 后端 pytest 全绿 + 新分支本地 commit；不 push

## 7. 后续建议（不阻塞）

- 前端接线：TripDetailView 质检卡「建议人工复核」提示条 + 行程列表 escalated 徽标
- 自托管运营：escalations API 已可接任何外部工单/通知系统（Webhook/IM），无需额外后端
- 若未来要「真人工闭环」（评审 → 采纳/驳回 → 状态回写），再立新 todo 做 schema 演进（trip_escalations 表 + 状态机）