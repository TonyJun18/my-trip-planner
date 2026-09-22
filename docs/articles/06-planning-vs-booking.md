# AI 旅行规划正在变成预订漏斗——独立工具的机会在「规划层」

> 写给：AI 行程/规划类产品的产品经理和工程师，以及想在 AI 旅行赛道找差异化的小团队。
> 一句话结论：2026 年资本把 AI 旅行卷向了「可预订」（agentic 订票、OTA 收购），独立工具的生存空间不在预订闭环，而在**免费、透明、可修订、可自托管的规划层**——规划层不是过渡形态，而是可以长期做深的产品层。

## 先说三个行业事件

过去一年 AI 旅行规划赛道的三条新闻，拼在一起就是完整的信号：

**1. Tripnotes.ai 停运（2023-12 → 2026 确认）。** 曾经靠 ChatGPT 行程规划病毒式传播的明星产品，被 Dorsia（会员制餐厅预订）收购后关站——创始团队并入收购方做高端餐厅预订去了。它留下的"AI 行程 + 可编辑笔记 + 分享地图"定位，至今没有谁真正接住。

**2. Mindtrip 上线 agentic 机票预订（2026-05）。** 行业首个 Agent 直接订机票的引擎（Sabre Mosaic + PayPal 结账，含 BNPL）。Mindtrip 有 600 万 POI、群组实时协作、Pro 订阅——但它选择把重心押在"规划完直接订"。

**3. Expedia Group 收购 Layla（2026-07）。** 对话式 AI 旅行代理 Layla（含其家族产品 TripPlanner AI）并入 Expedia。Layla 的招牌是实时定价 + PriceLock 价格追踪 + 人类专家代订，8M+ 行程——它走的是"免费规划引流 → 预订/服务收费"的漏斗。

三条加在一起：**赛道正在被资本整理成"预订漏斗"**——AI 规划是入口，订机票/酒店/活动才是商业闭环。Mindtrip 自己做预订、Layla 被 OTA 收编、Tripnotes 直接关站转行。独立小工具想靠"生成行程"本身活下来，越来越难。

## 预订层是重资产，规划层是轻资产

把 AI 旅行产品按商业模型拆成两层，差异一目了然：

| 维度 | 规划层（Plan） | 预订层（Book） |
|---|---|---|
| 核心资产 | 行程生成、修订、质检、协作 | 实时库存/票务、支付、价格预测 |
| 数据要求 | POI/天气/距离（开放或低成本） | 航司/酒店 GDS、实时价格、退改规则 |
| 信任成本 | 中（错了用户自己改） | 高（订错了要赔） |
| 履约 | 无（用户自行决定） | 有（支付、出票、售后、客服） |
| 典型玩家 | 我们、Wanderlog、Stippl | Hopper、Layla/Expedia、Mindtrip |
| 小团队可行性 | ✅ 可行 | ❌ 极难（重资产、合规、资金） |

Hopper 是预订层的极端样本：靠价格预测（AI 说"现在买还是等"）积累 1 亿用户，再用增值付费变现——护城河是多年票务数据，独立团队短期内不可能复制。

**所以独立工具的正解是：把规划层做深，而不是向上够预订层。** 规划层的"深"不是多生成几种行程模板，而是三件事：**可修订、可验证、可信任**。

## 我们的做法：把规划层做深的三根支柱

我们（my-trip-planner，FastAPI + LangGraph + Vue3，开源于 github.com/TonyJun18/my-trip-planner）没有做任何预订功能，全部资源压在规划层的三根支柱上。以下代码引用均与仓库实际一致。

### 支柱一：可修订——AI 出 diff，代码执行

预订层产品怕用户改（改了要重算价格库存），规划层产品应该**欢迎用户改**。我们把"改行程"做成一等公民：

```python
# backend/app/services/revise_service.py
async def revise_trip(db, trip_id, message, *, owner=None, provider="auto"):
    # 1) AI 只生成结构化 diff（PlanReviseAgent，无工具、失败可自纠正）
    revise = await plan_revise_agent({...}, current_plan, provider=provider)
    # 2) 代码原子应用（存在性/类型/位置校验，任一失败整体回滚）
    _apply_diff(trip, diff)
    # 3) 落库 + 预算代码重算（LLM 估值不可信）
    await _recompute_budget(db, trip)
    await db.commit()
```

用户说"第三天西湖改成半天，晚上加楼外楼"，AI 产出 `{op, target, fields}` 指令集，**代码**负责执行——意图可信、行为可校验、失败可回滚。这是所有竞品里唯一带回滚保障的修订路径（详见姊妹篇《为什么 AI 行程工具应该把「修订」做成一等公民》）。

### 支柱二：可验证——价格真实度与质检闭环

规划层最容易被骂"假大空"的就是预算和推荐质量。我们用两条路对抗：

**价格真实度**：酒店参考价用代码确定性估算，不靠 LLM 瞎报：

```python
# backend/app/services/budget_service.py
def estimate_hotel_cost(name, city=None, *, rating=None) -> float:
    base = _HOTEL_CITY_BASE.get(_match_city(city), _HOTEL_FALLBACK)  # 城市基准价
    multiplier = 1.0
    for kw, m in _HOTEL_TIER:            # "五星"×2.8、"经济"×0.7 ……
        if kw in name:
            multiplier = m
            break
    ...
```

城市基准价 × 档位倍率 × 评分修正——**可解释、可测试、不依赖外部价格源**，前端标注"参考价，以实际询价为准"。

**质检闭环**：Planner 产出后由 `TravelCriticAgent`（无工具质检专家）按日程/预算/地理/完整性四维评分，不过审带反馈重生成（最多 2 轮后强制定稿，质检失败自动降级放行）。配合前端实时 T-A-O（Thought-Action-Observation）轨迹，**用户能看到每个 Agent 在干什么、为什么这么生成**——黑盒是规划层最大的信任杀手，透明是免费工具最便宜的护城河。

### 支柱三：可协作——把多人决策留在规划层

多人出行是高频刚需，但群组共编 (co-edit) 复杂度高。我们做轻量协作：分享链接 + 评论 + 站点 👍/👎 投票（凭 share_token 免登录、投票幂等可翻转、同行程归属校验）：

```python
# backend/app/services/collab_service.py
async def _belongs_to_trip(db, stop_id, trip_id) -> Stop:
    """校验站点属于该行程（防止跨行程投票）。"""
    stmt = (select(Stop).join(TripDay, TripDay.id == Stop.day_id)
            .where(Stop.id == stop_id, TripDay.trip_id == trip_id))
    ...
```

一行 `share_token` + 一组轻接口，就把"群里十个链接来回发"变成"一个链接大家投票定行程"——规划层的协作不需要拼实时协同编辑，先把决策问题解决。

## 可复用的模式

| 决策 | 落地方式 | 收益 |
|---|---|---|
| 不做预订闭环 | 只做规划层（生成/修订/质检/协作） | 避开重资产，专注体验 |
| 价格用代码估算 | 城市基准价 × 档位倍率（budget_service） | 可解释、可测试、无外部依赖 |
| 修订走 diff + 原子应用 | AI 出指令、代码执行（revise_service） | 可信、可回滚、可解释 |
| 质检做成闭环 | TravelCritic 四维评审 ≤2 轮（graph） | 输出质量有闸门，不无限烧 token |
| 协作做轻量版 | share_token + 评论 + 投票（collab_service） | 多人决策可闭环，不碰协同编辑复杂度 |

**最关键的迁移心态**：先想清楚你的产品在哪一层。如果你在规划层，就把"修订、验证、协作"做到竞品做不到的深度；如果决定做预订层，请准备好库存、支付、客服和资金——那不是小团队用 prompt 能补齐的。

## 小结

- 2026 年 AI 旅行赛道正在变成预订漏斗：Tripnotes 关站、Mindtrip 自己做 agentic 订票、Layla 并入 Expedia。
- 预订层是重资产（库存/支付/售后），独立工具的正解是把规划层做深：**可修订（diff+原子应用）、可验证（价格估算+质检闭环）、可协作（轻量投票）**。
- 规划层不是"等被收购的过渡形态"——免费、透明、可自托管本身就是长期差异化；Tripnotes 留下的窗口，接住它的是把"规划"做成产品的人。

---

*项目源码：github.com/TonyJun18/my-trip-planner（FastAPI + LangGraph + Vue3，MIT License）*
*相关文章：[《多 Agent 编排不是堆 Agent》](./01-multi-agent-orchestration.md) · [《让 Agent 稳定输出：Pydantic 强校验 + 失败自纠正》](./02-structured-output-validation.md) · [《Agent 的容错工程》](./03-resilience-engineering.md)*
*姊妹篇《为什么 AI 行程工具应该把「修订」做成一等公民》作为系列文章④随夜间流水线同步发布（本分支未包含，合并后链接补齐）。*