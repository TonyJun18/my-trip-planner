# 灵感优先：AI 行程工具的入口之争

> 写给：AI 旅行/规划类产品的产品经理和工程师，以及所有在思考「用户第一次打开你的工具时，到底该看到什么」的人。
> 一句话结论：2026 年三家头部 AI 旅行工具（Mindtrip / Layla / Wonderplan）不约而同地把战场从「生成质量」挪到了「起点体验」——先定目的地的表单正在被「还没想好去哪」的灵感流取代。但入口之争的答案不是选一种范式，而是**低摩擦起点 + 高质量承接**：用最便宜的姿势接住模糊的诉求，再用工程手段把模糊变精确。本文对比三种入口范式的体验与工程代价，并落成我们仓库里的具体实现（问答表单 + 四通道导入 + questions 追问 + 灵感推荐）。

## 一、为什么 2026 年大家突然都在抢「入口」

先说三个几乎同时发生的事实：

1. **Mindtrip 上线 Start Anywhere**：不必先定目的地，从「一个模糊情绪 / 一张截图 / 一条社交帖 / 一份 PDF」直接开始规划。官方强调的卖点就是「你不需要知道要去哪」。
2. **Layla 的五问 checklist 起步**：第一问是「Where to」，但旁边永远挂着一个按钮——「**Let me inspire you if you don't know**」。五问分别是去哪 / 从哪 / 和谁 / 何时 / 要什么，答完即 generate。
3. **Wonderplan 免费无门槛**：打开就用，表单式输入（目的地/日期/预算/兴趣）→ 个性化行程，不设注册墙。

三家的产品形态完全不同（对话式地图第一视图 / 对话 + 真人专家 / 纯免费表单），但起点设计的结论高度一致：**「先定目的地」是所有规划流程里摩擦最大的一步**。用户打开工具的瞬间，脑子里往往只有「我想出去玩」和「我大概有三千块」，没有「我要去杭州四天」。

这不是玄学——「去哪」是一个**决策**，而「要不要出去玩」是一个**情绪**。让用户在还没产生决策的时候就填目的地表单，等于逼他在拿到答案之前先给出答案。入口之争抢的，就是「情绪 → 决策」这段真空地带。

## 二、三种入口范式：体验与工程代价

我们把市面上所有 AI 行程工具的入口抽象成三种范式：

| 范式 | 代表 | 起点输入 | 摩擦 | 工程代价 | 承接质量 |
|---|---|---|---|---|---|
| **① 目的地优先表单** | Wonderplan、传统行程工具 | 目的地/日期/预算/兴趣（必填或强预设） | 高：用户先做决策才能开始 | 低：一个表单 + 一个生成接口 | 高：输入结构化，生成可控 |
| **② Checklist 五问** | Layla | 5 个固定问题，答完即生成 | 中：结构化引导，可跳过 | 中：问题模板 + 答案解析 + 兜底 | 中：答案自由文本，需消化 |
| **③ 灵感流（Start Anywhere）** | Mindtrip | 模糊输入：情绪/链接/截图/一句话 | 极低：先出东西，再慢慢收窄 | 高：内容理解 + 推荐 + 可逆 | 低→高：取决于承接机制 |

关键洞察藏在第三列和最后一列的关系里：**入口摩擦越低，承接质量越难做**。

- 范式①的工程代价最低，但把决策成本全部转嫁给了用户——「还没想好去哪」的用户直接流失。
- 范式②好一点，用五个问题帮用户把模糊诉求结构化，代价是每多一个问题就多一层流失（Layla 的解法是「Let me inspire you」兜底：答不上来就别答，我给你灵感）。
- 范式③的表面功夫最好看——丢一个链接进来就「开始规划了」，但魔鬼在细节：**链接里是什么内容？多长的行程？什么预算？** 如果工具只是把链接塞给 LLM 然后吐一个行程，那叫「看起来低摩擦」，实际是把模糊传导给了生成环节，质量必然翻车。Mindtrip 能撑住是因为它有 1100 万 POI 库 + 4 万本地达人输入做地基，不是所有团队都付得起这个代价。

所以真正的产品问题不是「选哪种范式」，而是：**怎么用尽可能低的入口摩擦，接住尽可能模糊的诉求，同时不让生成质量塌掉。**

## 三、我们的答卷：问答表单 + 四通道导入 + questions 追问 + 灵感推荐

我们（my-trip-planner，FastAPI + LangGraph + Vue3，开源于 github.com/TonyJun18/my-trip-planner）没有选择单一种范式，而是把三种范式的优点拆开，叠成一条「宽进严出」的入口链路。以下代码引用均与仓库实际一致（main 分支，2026-10 时点）。

### 第一层：问答表单（范式①的骨架）

种子行程由「目的地 + 日期 + 预算档 + 偏好 chips」驱动，这是确定性最强的起点——一旦用户知道自己要去哪，表单是最快的路径。预算档与后端档位严格对齐（`economy 1500 / comfort 3000 / quality 6000 / luxury 12000` 元），兴趣 chips 词表直接对接推荐与规划 Agent 的偏好解析，**表单里选的每一个值，后端都有对应的确定性语义**（`frontend/src/views/PlanWizard.vue` 的 `tierPresetMap` / `prefLabelKeyMap`）。

### 第二层：四通道导入（范式③的轻量版，输入自由）

「还没想好去哪」不代表「没有输入」。用户手里通常有攻略笔记、种草截图、社交链接、甚至预订确认邮件——这些真实世界的信息就是最好的起点素材。我们把四种输入全部接进同一条「候选勾选」管线（`backend/app/services/`）：

```python
# backend/app/services/note_import.py
def parse_note(text: str) -> NoteImportResult: ...
# backend/app/services/email_import.py
def parse_email(text: str) -> EmailImportResult: ...
# backend/app/services/screenshot_import.py
def parse_screenshot(image_bytes: bytes) -> ScreenshotImportResult: ...
# backend/app/services/link_import.py（社交分享链接 → 结构化提取，失败静默降级为链接收藏）
```

四条通道共享同一个敌意输入处理管线：任何指令型内容（`_INJECTION_RE`：忽略类/扮演类/必须类措辞）在进入候选前就被剥离，绝不进入下游 Agent 上下文——**导入入口 = 敌意输入入口**，这是安全底线，不是可选项。

这一层的产品语义是：**用户不需要先定义「行程」，只需要先丢进来一点「素材」**。素材变成候选站点列表，用户勾选后并入行程——把「从零生成」降级为「从一到多」。

### 第三层：questions 追问（范式②的轻量版，需求澄清）

表单之外，规划请求可以带一组主动提问 Q&A（`PlanRequest.questions`，`max_length=10`：人群/节奏/避峰/备选方案），答案会作为补充上下文注入 Planner 与 Critic：

```python
# backend/app/agent/agents.py
def _questions_text(request: dict[str, Any]) -> str:
    # 主动提问 Q&A：有回答才注入，未回答的问题忽略
    questions = request.get("questions") or []
    answered = [q for q in questions if isinstance(q, dict) and (q.get("answer") or "").strip()]
```

设计取舍：**未回答的问题不产生任何约束**（不注入），回答了才进上下文。这样追问永远「可跳过」，不增加起点摩擦，同时把「和谁去 / 想玩多松 / 要不要避峰」这些表单里没有的隐性需求捞出来——这正是 Layla 五问想做的事，但我们用可增量、可跳过的方式实现。

### 第四层：灵感推荐（范式③的确定性实现，task-inspiration-mode）

针对「真的还没想好去哪」的用户，我们在创建规划页加了灵感入口：填预算档 / 兴趣标签 / 季节 → 推荐 3-5 个目的地卡片（一句话理由 + 参考玩法 + 预估日均预算 + 建议天数）→ 点选后预填创建表单。

关键工程决策：**这一层没有用 LLM**。它是一套确定性规则库（`backend/app/services/inspiration_service.py`）：

```python
# backend/app/services/inspiration_service.py
def recommend_destinations(
    interests: list[str] | None = None,
    budget_tier: str = "comfort",
    season: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    # 预算诚实：目的地基准消费档超出用户档位 → 不推荐（推荐消费得起的地方）
    # 兴趣匹配：交集计数（至少一个命中才入选；无兴趣输入时全部候选）
    # 季节：当季 +1.0 / 四季皆宜 0 / 非最佳 -0.5 降权不排除，附 season_note
    # 全部产物带 basis="rule_based" 诚实标注
```

为什么不用 LLM 做推荐？三个理由：

1. **可测试**：23 个目的地知识库 + 确定性排序，单测直接断言「选了 food+spring 就出杭州/成都/大理，预算 luxury 才出东京」。LLM 推荐没法这么测。
2. **诚实口径**：目的地自带 `budget_tier`（基准消费档），超出用户预算档的直接不推荐——推荐「消费得起的地方」而不是「看起来很酷的地方」，延续我们预算诚实的一贯哲学（基础价代码估算 + `estimate_basis` 口径标注，见文章⑨）。
3. **成本**：这层是高频低价值调用（用户可能反复调），零 LLM 意味着零成本、零延迟、零故障——入口层不应该有失败率。

前端接线（`frontend/src/views/PlanWizard.vue`）：

```js
async function loadInspiration() {
  const data = await api.getInspiration({
    interests: form.preferences.join(','),
    budget_tier: budgetTierKey.value,
    season: seasonKey.value,
    limit: 5,
  })
  // → inspirationItems: 名称/理由/参考玩法/预估日均预算/建议天数/匹配标签/季节提示
}
function applyInspiration(dest) {
  // 选点预填创建表单：目的地 + 预算对齐该目的地基准档
  form.destination = dest.name
  form.budget = tierPresetMap[dest.budget_tier] || form.budget
}
```

注意 `applyInspiration` 的语义：**灵感推荐不是终点，是预填**。用户点选一个目的地卡片，表单自动填好目的地 + 对齐预算档，然后走正常的高质量生成流程（多 Agent 并行采集 + 四维质检 + T-A-O 轨迹）。灵感层负责降低起点摩擦，生成层负责质量，两层解耦——这就是「低摩擦起点 + 高质量承接」的落地形态。

后端 API 是纯只读派生接口（`GET /trips/inspiration?interests=...&budget_tier=...&season=...`，登录必需，`backend/app/api/v1/inspiration.py`），不写任何表，与 plan_b / map_edit 同风格。

## 四、入口之争的工程账：哪些钱值得花

| 投资 | 我们花在哪 | 收益 | 不花会怎样 |
|---|---|---|---|
| 表单与后端契约对齐 | `tierPresetMap` / `prefLabelKeyMap` / `PlanRequest.questions` | 表单任意输入都有确定性语义，生成可控 | 表单是装饰品，LLM 自由发挥 |
| 四通道导入（敌意输入同管线） | note/email/screenshot/link 四个 parser | 用户的真实素材直接变候选，导入即安全 | 只留表单，用户手里的攻略/截图全部浪费 |
| questions 追问（可跳过） | `_questions_text` 有回答才注入 | 隐性需求进上下文，不增加摩擦 | 用户说「随便」，生成就真的随便 |
| 灵感推荐（确定性规则） | `recommend_destinations` 零 LLM | 入口零成本零失败，推荐诚实可测 | 入口要么没有，要么是又一个 LLM 黑盒 |
| **不花**：免注册即用（guest 创建） | 评估关闭（task-guest-trial）：多 Agent 规划 = 免费算力矿场敞口 + 归属语义被污染 | 省掉匿名滥用治理成本 | —（详见 docs/nightly/evaluations/task-guest-trial-2026-10-15.md） |

## 五、可复用的模式

| 决策 | 落地方式 | 收益 |
|---|---|---|
| 入口分层，不选边站 | 表单（精确）+ 导入（素材）+ 追问（澄清）+ 灵感（模糊）四层可叠加 | 不同用户从不同层进入，都导向同一个高质量生成流程 |
| 灵感推荐用规则不用 LLM | 知识库 + 交集计数 + 季节降权 + 预算过滤（inspiration_service.py） | 可测试、零成本、诚实口径 |
| 灵感是预填不是终点 | `applyInspiration` 只填表单，生成仍走完整质检管线 | 低摩擦入口不稀释生成质量 |
| 追问可跳过 | 未回答的问题不注入（agents.py `_questions_text`） | 澄清需求不增加起点摩擦 |
| 导入通道共享敌意处理 | `_INJECTION_RE` 剥离指令型内容后才进候选 | 开放的入口不变成注入通道 |
| 候选勾选统一形态 | 四通道都产出「候选站点列表」，用户勾选并入行程 | 导入体验一致，后端只有一条并入管线 |

## 六、给同行的一份「入口检查清单」

1. **你的用户打开工具时，脑子里有目的地吗？** 没有的话，你的第一屏是在帮他还是挡他？
2. **「还没想好」有兜底吗？** Layla 有 Let me inspire you，Mindtrip 有 Start Anywhere——你的等效物是什么？（哪怕是一个预填模板）
3. **低摩擦入口会把模糊传导给生成吗？** 如果会，你的承接机制在哪？（灵感 → 预填 → 完整质检，而不是灵感 → 直接吐行程）
4. **入口层值得用 LLM 吗？** 高频低价值的调用（推荐、解析常见格式）优先用确定性代码 + 规则库，LLM 留给真正需要理解的环节。
5. **你接住用户的素材了吗？** 攻略笔记、截图、链接、确认邮件——这些是用户真实世界的输入，也是你区别于「从空白表单开始」的竞品的入口资产。
6. **开放的入口安全吗？** 任何接受用户内容的通道，都要按敌意输入处理（注入剥离 + 结构化校验 + 失败降级）。

---

## 小结

- 2026 年三家头部（Mindtrip / Layla / Wonderplan）的共识：**「先定目的地」是规划流程最大的起点摩擦**，入口之争抢的是「情绪 → 决策」的真空地带。
- 三种入口范式（目的地优先表单 / checklist 五问 / 灵感流）的本质是「摩擦 vs 承接质量」的权衡：摩擦越低，承接越难做。
- 我们的答卷不是选一种范式，而是**四层叠加**：问答表单（精确起点）+ 四通道导入（素材起点）+ questions 追问（澄清起点）+ 灵感推荐（模糊起点），全部导向同一个高质量生成流程。
- 灵感推荐用确定性规则（23 目的地知识库 + 预算诚实过滤 + 季节降权不排除 + `basis="rule_based"`）而不是 LLM：可测试、零成本、推荐诚实——**入口层不应该有失败率，也不应该有幻觉**。

---

*项目源码：github.com/TonyJun18/my-trip-planner（FastAPI + LangGraph + Vue3，MIT License）*
*相关文章：[《当 AI 旅行工具都在抢着替你花钱：独立规划层的生存策略》](./07-open-planning-layer.md) · [《终局剧本：当 agentic 预订已经成交、独立工具已被收购——规划层还剩什么》](./10-endgame-booking-agentic.md) · [《预算是 AI 行程工具最不诚实的部分》](./09-budget-transparency.md)*
*本文是「规划层生存策略」系列的入口篇：10 讲终局后规划层还剩什么，本文讲用户第一次打开工具时该看到什么——入口是产品，不是漏斗。*