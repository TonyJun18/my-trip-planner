# 让 Agent 稳定输出：Pydantic 强校验 + 失败自纠正

> 写给：被 LLM 输出"时好时坏"折磨过的工程师。
> 多 Agent 系统的第一行工程原则：**LLM 输出不可信，schema 才可信。**
> 本文用真实代码讲：怎么让 Agent 稳定产出结构化 JSON，失败了自己改对。

## 问题：LLM 不是 API，是"概率性 JSON 生成器"

让 LLM 直接输出行程 JSON，你会遇到：

- 字段缺失（漏了 `budget`、漏了 `days[0].stops`）
- 类型错乱（`duration_minutes` 给了字符串 "两个小时"）
- 日期格式漂移（`2026年10月1日`、`10/1`、`2026-10-01` 混着来）
- 坐标越界（纬度 91 的"景点"，地图直接崩）
- 多余的 Markdown 代码块包裹（```json ... ```）

**LLM 永远不会保证输出 schema。** 期望它"prompt 里写了就遵守"是赌运气。正确做法是：**输出进 schema 校验，校验失败让 LLM 自己改。**

## 第一层：把 schema 定义清楚（Pydantic v2）

`backend/app/schemas/plan.py`——每个字段的类型、边界、取值范围都写死：

```python
from pydantic import BaseModel, Field
from datetime import date as _Date
from typing import Literal

class StopSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=200)
    type: Literal["attraction", "food", "hotel"] = "attraction"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    estimated_cost: float = Field(default=0.0, ge=0)
    duration_minutes: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=1000)

class DaySchema(BaseModel):
    model_config = ConfigDict(extra="ignore")
    day_number: int = Field(ge=1)
    date: _Date | None = None
    theme: str | None = Field(default=None, max_length=200)
    stops: list[StopSchema] = Field(default_factory=list, max_length=20)

class PlanSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")
    destination: str = Field(min_length=1, max_length=200)
    days: list[DaySchema] = Field(default_factory=list, min_length=1, max_length=31)
    budget: BudgetSchema = Field(default_factory=BudgetSchema)
    hotels: list[HotelSchema] = Field(default_factory=list, max_length=20)
```

几个关键选择：

- **`extra="ignore"`**——LLM 多输出的字段直接丢弃，不留垃圾
- **`Literal[...]`**——type 只能是三选一，杜绝"餐厅/美食/景点"这种自由心证
- **`date` 类型**——Pydantic 自动把 `2026-10-01` 解析成真正的日期（格式错直接报错）
- **范围校验**——纬度 [-90,90]、经度 [-180,180]，坐标越界直接失败
- **min/max_length**——防 LLM 输出 8000 字的小说

校验函数：

```python
def validate_plan(data: dict) -> dict:
    """校验 LLM 输出并返回「可 JSON 序列化」的干净 dict（丢弃多余字段）。"""
    validated = PlanSchema.model_validate(data)
    return validated.model_dump(mode="json")
```

## 第二层：把错误喂回 LLM，让它自纠正

校验失败的瞬间，把 Pydantic 的 `ValidationError` 转成给 LLM 的简短纠错提示（`_validation_feedback`）：

```python
def _validation_feedback(exc: Exception) -> str:
    """把 Pydantic ValidationError 转成给 LLM 的简短纠错提示。"""
    errors = getattr(exc, "errors", list)()
    lines = []
    for e in errors[:6]:  # 只取前 6 条，防止提示太长
        loc = ".".join(str(x) for x in e.get("loc", []))
        lines.append(f"- {loc}: {e.get('msg', 'invalid')}")
    return "你的最终行程 JSON 校验失败，请修正后重新输出完整的 JSON（不要解释）：\n" + "\n".join(lines)
```

在 Agent 循环里（`graph.py` 的 `agent_node`）：

```python
try:
    clean = validate_plan(final)
    return {"messages": [response], "plan": clean, "status": "completed"}
except Exception as exc:  # Pydantic ValidationError
    corrections = state.get("corrections", 0) + 1
    if corrections > state.get("max_corrections", 3):
        return {"messages": [response], "status": "failed",
                "error": f"LLM 输出校验失败: {exc}"}
    feedback = SystemMessage(content=_validation_feedback(exc))
    # 关键：把「错误提示」作为一条新 SystemMessage 追加回消息历史，
    # LLM 带着「刚才哪里错了」重新输出完整 JSON
    return {"messages": [response, feedback], "iterations": iterations,
            "corrections": corrections}
```

**为什么有效**：LLM 是 context 驱动的。把错误摘要作为一个新消息追加进消息历史，它就"知道"自己刚才哪里错了，重试时修正那里——比"再生成一次"靠谱得多。实测多数情况下 1-2 次自纠正就能通过。

**三个工程细节**：

1. **纠错上限（max_corrections=3）**——防止 LLM 反复输出同一错误死循环；超限直接失败返回给用户，绝不无限重试
2. **错误摘要截断（前 6 条）**——避免把 30 个字段全塞给 LLM，维持上下文干净
3. **提示里强调"不要解释，直接给完整 JSON"**——避免 LLM 用一段话道歉而不是重新输出

## 第三层：T-A-O 循环里的鲁棒性

上面只处理了"校验失败"，还有两类情况：

**A. LLM 输出里根本找不到 JSON**（全是散文）——`_extract_json` 返回 None，同样进自纠正流程，提示"只输出一个 JSON 对象，不要解释、不要额外文字"。

**B. 迭代上限（max_iterations=10）**——如果 LLM 一直在调用工具不收敛（比如把同一个搜索重复 10 次），说明它陷入循环，强制结束标记失败：

```python
if state.get("iterations", 0) >= state.get("max_iterations", 10):
    state["status"] = "failed"
    state["error"] = f"达到最大迭代次数 {state.get('max_iterations')}"
    return "end"
```

**这三层合起来，Agent 输出从"时好时坏"变成"要么一次通过，要么在有限次自纠正内通过，要么明确失败"——三种结果都是可预期的。**

## 测试怎么覆盖（FakeLLM 测试替身）

强校验逻辑是可以离线测试的——用 FakeLLM 替身模拟"输出坏 JSON 一次，然后输出好 JSON"：

```python
class FakeLLM:
    """测试替身：第一次返回坏 JSON，之后返回好 JSON。"""
    def __init__(self, bad_first: bool = True):
        self.calls = 0
        self.bad_first = bad_first

    async def ainvoke(self, messages):
        self.calls += 1
        if self.bad_first and self.calls == 1:
            return AIMessage(content='{"destination": "杭州", "days": []}')  # days 空数组，校验必失败
        return AIMessage(content=GOOD_PLAN_JSON)
```

测试断言：第一次输出坏 JSON → 系统进入自纠正 → 第二次输出好 JSON → 最终 status=completed、plan 通过校验、corrections=1。**整个过程不耗 token、不依赖网络、几毫秒跑完。**

## 小结：三层输出的工程化

| 层 | 机制 | 保证 |
|---|---|---|
| Schema 强校验 | Pydantic（类型/范围/枚举/长度） | 坏输出进不了业务层 |
| 失败自纠正 | 错误摘要回喂 LLM（上限 3 次） | 多数坏输出自己改好 |
| 循环兜底 | 迭代上限 + 纠错上限 | 永不无限循环 |

**LLM 输出不可信，但可以把它变成"有边界的不可信"——边界由代码定义，不在 prompt 里靠自觉。**

---

*项目源码：github.com/TonyJun18/my-trip-planner。下一篇：[《Agent 的容错工程：重试、熔断、降级，以及怎么测试》](./03-resilience-engineering.md)*