# 多 Agent 编排不是堆 Agent：单一职责 + 并行采集 + 编排层补位

> 写给：正在用 LangGraph / LangChain / 自研框架做多 Agent 系统的后端工程师。
> 本文用一个真实项目（FastAPI + LangGraph 的智能行程规划）讲清楚：多 Agent 到底拆什么、并行什么、用什么兜底。

## 先看反模式：一个超长 prompt + 一个循环

很多人做的"多 Agent"其实是这样的：

- 一个 prompt 里写满"你是旅行规划专家、酒店专家、天气专家……"
- 一个 ReAct 循环让 LLM 自己决定调什么工具、调几次
- 最终靠"LLM 的自觉"完成所有事

结果是：prompt 500 行、每次调用贵、行为不可预期、出错不知道怪谁。**我们把 Agent 当人用，却忘了人不该被要求同时干所有事。**

## 正解：按"职责"拆，按"确定性"分

这个项目的拆法（代码在 `backend/app/agent/agents.py`）：

| Agent | 职责 | 是否调工具 | 是否走 LLM |
|---|---|---|---|
| AttractionSearchAgent | 偏好 → 关键词 → 景点 POI | ✅ search_attractions | ✅ |
| WeatherQueryAgent | 城市 → 天气预报 | ✅ query_weather | ❌（纯工具路径） |
| HotelAgent | 住宿需求 → 关键词 → 酒店 POI | ✅ search_hotels | ✅ |
| PlannerAgent | 整合团队产出 → 完整行程 | ❌ 不调任何工具 | ✅ |

三个关键决策：

**1. 每个 Agent 只做一件事，提示词压到 30 行以内。**

景点 Agent 的系统提示词核心就一句话："把偏好转换为 2-4 个中文关键词，调用工具获取真实景点，不要编造"。它不知道酒店、不知道天气、不知道预算——它不可能答错这些问题，因为它根本没被问。

**2. 能确定性的，就别让 LLM 干。**

天气是"城市名 → 数据"的确定性映射，直接做成纯工具路径，**零 token、零幻觉、零延迟**——这不是偷懒，是把 LLM 从它不擅长的事情上解放出来。

预算更典型：LLM 算数经常算错。项目里预算最终由 `compute_budget`（纯代码）校准覆盖，LLM 的估值只是参考：

```python
def compute_budget(stops: list[dict[str, Any]]) -> dict[str, Any]:
    """根据站点列表计算预算明细（纯计算）。"""
    by_type: dict[str, float] = {}
    total = 0.0
    for stop in stops:
        cost = float(stop.get("estimated_cost") or 0)
        stype = stop.get("type", "attraction")
        by_type[stype] = by_type.get(stype, 0.0) + cost
        total += cost
    return {
        "total_estimated": round(total, 2),
        "by_type": {k: round(v, 2) for k, v in by_type.items()},
        "currency": "CNY",
    }
```

**一句话原则：LLM 只做它擅长的"理解 + 编排"，数学和事实交给代码。**

**3. 编排层补位，不依赖 prompt 自觉。**

经验：Agent 不会主动想起"行程里还要吃饭"。项目里三个采集 Agent 并行结束后，编排层用代码补上餐饮搜索：

```python
# 编排层补齐餐饮（美食是行程必备要素）—— 不靠 LLM 自觉
foods = await search_foods(city, query="热门 必吃 美食", limit=6)
```

多 Agent 系统的稳定性，**主要来自编排层的代码，而不是每个 Agent 的自觉**。

## 并行：asyncio.gather，三路同时采集

三个采集 Agent 互相独立，直接并行：

```python
results = await asyncio.gather(
    attraction_agent(city, preferences, provider=provider),
    weather_agent(city, provider=provider),
    hotel_agent(city, hotel_pref, provider=provider),
)
```

- 三个 Agent 互不依赖 → 可以水平扩展（进程/多机）
- 整个采集阶段从"串行 3×N 秒"变成"并行 max(N) 秒"
- 任何一个 Agent 失败都不会阻塞其他两个（编排层拿到 partial 结果继续）

**这是"管道式多 Agent"和"协商式多 Agent"的分界线**：这个项目是前者——执行顺序固定、职责清晰、结果可预期。协商式（Agent 互相质疑、辩论）更强大但更难控，适合"这个方案对不对"的问题；对"帮我找景点排行程"这种执行型任务，管道式是最稳的选择。

## 这个模式怎么复用

任何"理解 + 采集 + 整合"类任务都能套：

1. **画职责表**：谁负责理解需求、谁负责查数据、谁负责出最终结果
2. **标确定性**：哪几步是"输入→数据"映射？做成纯工具，不进 LLM
3. **标并行性**：哪些采集互不依赖？并行起来
4. **找补位点**：什么信息 LLM 容易漏？编排层代码补上
5. **定整合者**：最终谁出结构化的完整结果？只让它整合，不给它工具

## 小结

- 多 Agent 的价值不在于"多个"，而在于**职责拆分 + 确定性兜底 + 编排层补位**
- 提示词极简 → 行为可预期 → 出错可定位
- 能代码化（确定性）的绝不给 LLM，能并行的绝不全串行

下一篇预告：[《让 Agent 稳定输出：Pydantic 强校验 + 失败自纠正》](./02-structured-output-validation.md)

---

*项目源码：github.com/TonyJun18/my-trip-planner（FastAPI + LangGraph + Vue3）*