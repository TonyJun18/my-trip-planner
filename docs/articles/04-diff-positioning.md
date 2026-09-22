# 为什么 AI 行程工具应该把「修订」做成一等公民

> 写给：正在做 AI 行程规划、AI 表单/生成类产品的产品经理和工程师。
> 一句话结论：AI 生成一次行程不难，难的是**让用户能放心地改**。谁先把「修订」做得像 Git diff 一样可预览、可回滚、可解释，谁就拿到了 Tripnotes.ai 停运留下的市场窗口。

## 先说一个反直觉的观察

过去一年 AI 行程工具的评测里，被吐槽最多的往往不是"生成得不够好"，而是**"改不动"**：

- 某头部工具实测：生成后想加一个景点，搜索失效、删了之后推荐列表变空、编辑功能直接损坏；
- 多数工具把"重新生成"当成唯一的修订手段——你只能承认"我不喜欢这版"，然后赌下一版更好；
- 修订完成后没有任何痕迹：用户不知道 AI 改了什么、为什么改、改完预算变成多少。

我们把大量精力花在"让第一次生成更聪明"上，却忽略了：**用户拿到行程后，第一件事永远是改**。目的地可能临时换、同伴可能突然多一个、某家餐厅周一闭店——修订不是边缘场景，是主场景。

竞品分析也印证了这一点：Wonderplan 的编辑功能实测损坏、Mindtrip 可定制但无实时定价、Layla 的修订集中在"换活动/改酒店"。而 Tripnotes.ai 停运（2026 年被 Dorsia 收购后关站），留下一个"AI 行程 + 可编辑笔记 + 分享地图"的定位真空——**没有人在认真做"可修订"这件事**。

## 把修订做成产品：四个设计决策

我们在 my-trip-planner（FastAPI + LangGraph + Vue3，开源在 github.com/TonyJun18/my-trip-planner）里把"修改行程"作为一等公民来做，核心是四个设计决策：

### 1. 对话式修订：AI 只出 diff，代码执行

用户不说"帮我重新规划"，而是直接用一句话提要求：

> "第三天西湖改成半天，晚上加一个楼外楼晚餐，预算控制在人均 300"

后端接口 `POST /trips/{trip_id}/revise` 调用 `PlanReviseAgent`，只做一件事：**把用户消息 + 当前行程 → 结构化 diff**（`op: replace/add/remove/reorder` + 目标站点 + 新字段），由 `revise_service` 的代码逐个应用。

```python
# backend/app/agent/agents.py —— PlanReviseAgent 的输出契约（ReviseDiff 强校验）
# 每个动作都是一个原子操作
{
  "actions": [
    {"op": "replace", "day_number": 3, "target": {"name": "西湖"}, "fields": {"estimated_duration_minutes": 240}},
    {"op": "add", "day_number": 3, "target": {}, "fields": {"name": "楼外楼", "stop_type": "food", "estimated_cost": 300}, "index": 2}
  ],
  "summary": "已把第三天西湖调整为半天，新增楼外楼晚餐"
}
```

**为什么不让 AI 直接改库？** 因为 LLM 的"行为"不可信，但它的"意图"可信。让 AI 产生增删改查的指令，由确定性代码校验和执行——指令错了可以拒绝，但永远不会产生半残缺的脏数据。这正是"LLM 只做理解，代码做执行"的项目哲学。

### 2. 原子性：要么全改，要么不改

`revise_service._apply_diff` 分两阶段执行：**先完整预检**（定位站点、校验类型、校验位置索引），全部通过才写入；任一动作非法（找不到目标、非法字段、非法类型）→ 抛 `AppError`，整个事务回滚，一行都不落库。

```python
# backend/app/services/revise_service.py —— 预检失败即整体拒绝
for action in actions:
    day = _find_day(trip, action.get("day_number"))
    if op in ("replace", "remove", "reorder"):
        stop = _find_stop(day, action.get("target"))
        if stop is None:
            raise AppError(f"Day {action.get('day_number')} 找不到目标站点", code="revise_target_not_found")
    ...
# 全部合法 → 才实际执行（_replace_stop / _build_stop / _renumber）
```

这解决了一个隐蔽但高发的问题：**AI 修订常见的"部分成功"**——改了 A 没改 B，用户拿到一个更坏的行程。原子性是用户敢反复修订的心理基础。

### 3. 修订后的强制校验：预算重算 + 自驾约束门

修订不是"改完就完"。站点变了，预算要跟着变、自驾路线要重新校验。这两件事都交给代码，不交给下一个 LLM：

```python
# backend/app/services/revise_service.py —— 修订落库前
await _recompute_budget(db, trip)   # compute_budget 纯代码重算预算（LLM 估值不可信）
_enforce_driving_constraints(trip)  # DrivingGate：超距/超时站点组合 → 整体拒绝
```

`DrivingGate`（`check_plan_driving`）与规划编排共用同一套确定性校验：修订若引入"上午在杭州、下午在南京"这种超距组合，直接返回 `400 revise_driving_violation`，并附带具体问题列表。**AI 出错的代价被代码兜住了**——这就是"可执行"的含义：修订不只是文本，而是会真实改变行程、且改变必须通过约束校验。

### 4. 修订可解释：diff 预览 + 质检报告 + trace

前端 `TripDetailView.vue` 把后端返回的 diff 渲染成人类可读的改动列表（"修改/新增/删除/调整顺序" + 目标站点 + 字段），用户提交修订前看到**这次到底会改什么**：

```
本次改动 2 项
○ 修改 Day 3「西湖」：时长 → 240 分钟
○ 新增 Day 3 第 2 位「楼外楼」（餐饮，预估 ¥300）
```

行程生成阶段同样透明：`TravelCriticAgent` 对每版行程做四维质检（schedule/budget/geography/logistics），给出分数、critical/warning/info 问题清单和建议，前端 `QualityCard.vue` 展示"行程质检报告"；`T-A-O` trace 记录每个 Agent 做了什么、观察到什么、状态如何，前端可回看"哪个专家在做什么"。

用户不是面对一个黑盒：**每一步都能看到理由，每一个改动都能预览。**

## 一套可复用的模式

不管你做的是行程、旅行笔记还是任何"AI 生成 → 用户微调"的产品，这套设计可以直接迁移：

| 决策 | 落地方式 | 收益 |
|---|---|---|
| AI 只出操作指令 | 定义 `{op, target, fields}` diff 结构，代码执行 | 意图可信、行为可校验 |
| 先预检后执行 | 全部动作合法才落库（事务） | 消灭"部分成功"脏数据 |
| 修订后强校验 | 代码重算派生数据 + 约束门 | 修订不会破坏边界条件 |
| 修订可解释 | diff 预览 + trace + 质检报告 | 用户信任，愿意反复改 |
| 有界质检循环 | 最多 N 轮评审，超限强制定稿 | 不无限烧 token、不卡死 |

**最关键的迁移心态**：把"用户修改"当成产品的一等公民，意味着你要为修改设计**可预览、可回滚、可解释**的接口——这和 Git 的 diff/commit 哲学同构：AI 生成的行程是"提交"，用户的每次对话式修订是"新提交"，而 Review 能力（diff 预览 + 质检）决定了用户敢不敢点提交。

## 小结

- 修订是 AI 行程工具的主场景，不是边缘场景；谁把修订做成一等公民，谁就拿到 Tripnotes.ai 留下的窗口。
- 核心是把「AI 出 diff、代码执行」做成产品：原子应用消灭部分成功，预算/自驾约束门守住边界，diff 预览 + trace 让修订可解释。
- 这套模式不限于旅行：任何"生成 → 编辑"类产品都值得把"修订"从功能升级为**产品哲学**。

---

*项目源码：github.com/TonyJun18/my-trip-planner（FastAPI + LangGraph + Vue3）*
*相关文章：[《多 Agent 编排不是堆 Agent》](./01-multi-agent-orchestration.md) · [《让 Agent 稳定输出：Pydantic 强校验 + 失败自纠正》](./02-structured-output-validation.md) · [《Agent 的容错工程》](./03-resilience-engineering.md)*