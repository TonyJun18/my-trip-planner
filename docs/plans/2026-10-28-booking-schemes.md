# 预订能力打通方案（车票 + 酒店）

**作者**: Alex (PM)  **日期**: 2026-10-28  **版本**: v1.0（候选方案评审稿，未批准）
**状态**: 候选方案——3 条路线并行评审，无单一推荐，需用户拍板
**关联**: `docs/plans/2026-10-28-trip-journey-xhs-schemes.md`（旅程追踪 + 晒图）· `docs/prd/2026-10-28-iteration-spec.md`（需求规格说明书）

---

## 1. 背景与已具备的资产

- 前端 Vue3 + Element Plus；后端 FastAPI + SQLAlchemy async + Postgres（docker 5433）
- **多 Agent 编排已收敛**：`backend/app/agent/pipeline.py`（PipelineStep 声明式 + PlanningPipeline 调度器 + CollectAgentsStep 六路采集）——新增采集类 Agent 优先注册为 PipelineStep，trace/事件契约不变（2026-10-28 C+A 架构升级）
- **plan JSON 语义已成契约**：`plan.hotels` = HotelAgent 搜索的**候选池**；`days[].stops[].type=="hotel"` = **已安排酒店**；`plan.budget` = 确定性代码估算，标注"参考价"
- **servicing 第二段**：`services/servicing_service.py`（transit/checkin/discounts 组合入口，任一失败只记 warnings 不阻断）
- **已有真实第三方调用基座**：高德 Web API（geocode location 为"经度,纬度"；驾车方向 /v3/direction/driving）、交通采集 rule 兜底估算（高铁 0.45 元/km）
- **可观测性**：`app/core/tracing.py`（RequestIdMiddleware + X-Trace-ID 响应头 + trace_context 任务作用域）；LOG_FORMAT=json 输出单行 JSON 日志自动带 trace_id
- **事件流**：`TripEvent`（append-only，event_type=revise/check/skip/delay/comment/vote/edit/share）+ `record_event` + WS collab feed 广播
- **行中 live 已就绪**：`live_service.py`（trip_phase 推断 upcoming/live/finished、今日日快照、check/skip/delay_today、免登录 share/edit token 双路径）
- **费用分摊已就绪**：`expense_service.py` + `TripExpense`（append-only 记账）
- **输入自由已打通**：note/screenshot/link/email 四通道导入；`email_import.parse_email` 能解析预订确认邮件
- **i18n / 降级链 / sheriff 测试纪律**全部就绪

**一句话现状**：规划/修订/协作/行中/记账/晒图的内容工厂都已具备，**缺的是"把行程中的交通与住宿从'建议'变成'真实可核销订单'的能力"**。

---

## 2. 目标与非目标

### Goals
1. 让行程里的"大交通 + 酒店"可**被真实预订**（或至少可一键跳转完成预订）；
2. 预订数据**回写行程**（订单状态、凭证号、均价、账号归属），支撑"全程追踪"；
3. 保持"规划层"的产品定位：透明（真实价格/库存/状态）、可回退（取消/改期）、不锁死用户。

### Non-Goals（本轮明确不做）
- **不做支付牌照 / 资金池**：不代收代付，不碰备付金与结算牌照；所有资金动作在第三方渠道完成。
- **不做自建库存 / 退改规则引擎**：退改完全依赖渠道策略，只做展示与转发。
- **不做 GDS 直连 / Sabre / Amadeus**：小团队不进资本密集型供应链（见 docs/articles/10 终局剧本）。
- **不做多币种结算**：预算口径保持 CNY。
- **不做实名/证件收集**：预订凭证号与订单状态即可，出行人证件由渠道侧收集。

> 评审要点：这三条 Non-Goal 划清"规划层 vs 预订层"边界——我们不拥有交易，只做"触达真实交易"的最短路径。

---

## 3. 方案总览（3 条路线）

| 方案 | 名称 | 核心做法 | 成本 | 预订闭环度 | 适用阶段 |
|---|---|---|---|---|---|
| **A** | OTA 联盟跳转（outlink） | 生成可点击预订外链（携程/去哪儿/12306 搜索 deep-link），跳转完成交易 | 极低（纯规则 + URL 组装） | ★☆☆ 引导型：用户跳出去订 | MVP 最快落地 |
| **B** | 浏览器会话式预订助手（agentic booking） | 现有大模型 + 用户在浏览器完成的"预订动作编排"：填表/跳转/确认码解析回写 | 中（浏览器自动化 + 会话恢复） | ★★☆ 半自动：AI 操作一半，用户确认一半 | 中期演进 |
| **C** | 官方开放平台 / 分销 API 直连 | 携程/飞猪/同程开放平台（授权码模式）查询实时价 + 库存 + 下单回调 | 高（商户资质/审批/联调/签名/对账） | ★★★ 真预订：API 下单、订单回调 | 长期商业化 |

**共同底座（3 条路线都复用的部分）**：
- 新增 `BookingAgent`（PipelineStep 注册），在规划/修订后把"建议"转成"可预订实体"；
- 新增 `plan.bookings` 契约字段（见 §4）与 `TripBooking` 表；
- 统一事件 `booking.*` 进入 `TripEvent` + WS 广播；
- 与 expense/live 联动：预订凭证号进费用记录备注、行中订单状态可查。

---

## 4. 方案 A — OTA 联盟跳转（outlink，MVP 首选）

### 4.1 数据流（拓扑：顺序链的"预订化"收尾）

```
Plan(含 transport/hotels/stops)
   │  BookingAgent(新 PipelineStep，代码规则 + LLM 整理)
   ▼
plan.bookings[]  ← 每条含 provider_url（可点击直达）
   │
   ▼
前端"一键预订"卡片 → 新标签页跳 provider_url（携程/去哪儿/12306）
   │
   ▼（用户回来后，可手动回填或接入 email-import）
"我订好了" → 粘贴确认邮件/截图 → email_import 解析 → 落 TripBooking
```

### 4.2 涉及文件
- `backend/app/agent/pipeline.py`：注册 `BookingStep`（Collect 段之后的新 PipelineStep）
- `backend/app/agent/agents.py`：`booking_agent`（输入 Plan → 输出 bookings 列表）
- `backend/app/schemas/plan.py`：`plan.bookings`（`BookingSchema`）+ `BookingProvider` 枚举
- `backend/app/models/trip.py`：`TripBooking` 表（trip_id/kind/order_no/status/provider_url/credential/amount/currency）
- `backend/app/api/v1/trips_bookings.py`：`POST /trips/{id}/bookings`（回填）、`GET`、`PATCH status`
- `backend/app/services/booking_service.py`：`_build_train_url` / `_build_hotel_url` / `_deeplink` 纯函数
- `backend/tests/test_booking_service.py` / `test_booking_api.py`（mock LLM，断言 URL 模板与 fallback）
- `frontend/src/views/TripDetailView.vue`：预订卡片（provider 标签/价格/跳转按钮/回填入口）
- `frontend/src/locales/{zh-CN,en-US}.js`：i18n 键

### 4.3 关键实现语义（契约优先）
```python
class BookingProvider(str, Enum):
    ctrip   = "ctrip"      # 携程
    qunar   = "qunar"      # 去哪儿
    tripcom = "12306"      # 铁路 12306
    # 后续可扩展 meituan / feizhu / tongcheng
```
- `_deeplink(provider, kind, query)`：纯函数组装 URL，零网络；对未知 provider 返回 None
- **不伪造"可订"**：outlink 只承诺"跳转搜索页，用户完成交易"；禁出现"已订/占座/确认"字样
- **回填链路**：跳转后用户"我订好了" → 粘贴确认邮件/截图 → 复用 email_import 敌意输入剥离 + 结构化解析（航班/酒店/确认码/金额）→ 落 `TripBooking` + 记 `booking.confirmed` 事件
- **失败兜底**：BookingAgent 失败/LLM 超时 → 静默降级：不产出 bookings，plan 照常落库，前端不显示预订卡（绝不阻断主流程，沿用 servicing 哲学）

### 4.4 显式故障模式 + 恢复路径
| 故障 | 检测 | 恢复 |
|---|---|---|
| LLM 生成异常结构 | Pydantic 校验失败 | 自纠正 ≤2 次 → 降级不产出 |
| URL 模板过期（provider 改规则） | schema 校验 + 前端 404 外链 | 版本化模板 + 记录 failure 事件，可运营修正 |
| 用户跳出去未回来 | 无检测（外链天然无回调） | 前端"我订好了"手动回填 + email-import 兜底 |
| 重复回填同一订单 | 唯一键 provider+order_no | 幂等 upsert，重复粘贴提示已存在 |

### 4.5 优点 / 风险
- ✅ 成本极低（纯规则 + URL 组装 + 回填），1 个 sprint 可落地，零资质
- ✅ 尊重"规划层"定位：不锁死用户、不碰资金、无合规负担
- ❌ 不产生佣金/转化数据（无联盟 SDK，转化靠回填，归因弱）
- ⚠ 外链存活受 OTA 页面结构影响，模板需维护

---

## 5. 方案 B — 浏览器会话式预订助手（agentic booking）

> 对标 Mindtrip Flights / Layla：对话内"搜索 → 比价 → 确认 → 支付（跳转）"。
> 我们不做自己的浏览器自动化内核，而是**把现有 A 轮（outlink）升级为"AI 引导预订 + 凭证回填"的会话**。

### 5.1 数据流（多了一个"会话编排"层）

```
Plan → ChatView（复用 B 期 runtime.AgentLoop）
   │  预订意图识别（"帮我订这趟高铁/这家酒店"）
   ▼
BookingAgent（Tool-call 模式）：
   ├─ 高德/12306 余票查询（外部 API，有 key 才启用）
   ├─ 拼出 deeplink → 引导用户在浏览器完成支付
   └─ wait：用户回来后粘贴凭证/确认页 → email-import 解析
   ▼
TripBooking 落库 + booking.* 事件 + 行中订单卡
```

### 5.2 关键技术点
- **会话恢复**：用户跳转支付后回来，会话上下文必须保留（chat 表 + webruntime 状态存续）
- **凭证解析**：复用 email_import / screenshot_import（粘贴确认邮件/截图 → 结构化订单）
- **不是无人驾驶**：支付动作永远由用户在浏览器完成（我们不碰资金）；"预订助手"负责搜索、比价、填表引导、凭证回填
- **可观测**：每次 tool 调用的 trace_id 贯穿会话；预订动作记录进 TripEvent

### 5.3 故障模式（会话式特有）
| 故障 | 检测 | 恢复 |
|---|---|---|
| 用户跳转后半途放弃 | 无回调 | 会话提示"没订成功？可以换个时间/车次/酒店" |
| 支付成功但凭证格式各渠道不同 | email_import 解析率兜底 | 降级：模板字段手动补录 |
| Agent 幻觉"已订成功" | 强校验：无凭证号/无渠道回调 = 未成交 | 状态机只允许 pending → confirmed（有凭证）→ cancelled |

### 5.4 优点 / 风险
- ✅ 体验最接近"对话内成交"，是竞品主打形态
- ✅ 无商户资质也能做（支付仍在浏览器）
- ❌ **浏览器自动化复杂度高**；会话中断/被反爬/被风控（OTA 登录态）风险显著
- ⚠ 需要接入真实余票/价格源（高德/12306 有接口与配额成本），否则仍是"搜索链接 + 引导"

---

## 6. 方案 C — 官方开放平台 / 分销 API 直连（真预订，长期）

### 6.1 数据流（进入"预订层"，资金在渠道）

```
Plan → BookingAgent(API 模式)
   ├─ 授权码换取 access_token（携程/飞猪/同程开放平台）
   ├─ 实时查询价格/库存（车次/房型/退改规则）
   ├─ 创建订单（带回调 URL）
   └─ 用户确认 → 跳渠道收银台/宿主 H5 支付
   ▼
渠道异步回调 → webhook 落 TripBooking（confirmed + 凭证号）
   ▼
行中展示：订单卡 + 退改规则 + 行程追踪
```

### 6.2 前置条件（硬门槛）
- 企业资质 + 开放平台商户入驻（携程合作 API / 飞猪商家 / 同程分销）审批周期以月计
- 签名机（RSA/国密）、对账、回调安全（验签 + 幂等）、沙箱联调
- 佣金结算协议（CPS/CPS+API 模式才对独立工具开放；纯 API 往往要求流量承诺）

### 6.3 故障模式（资金侧）
| 故障 | 检测 | 恢复 |
|---|---|---|
| 回调重复/乱序 | 幂等键 provider+order_no+event | 去重 + 状态机校验 |
| 支付成功但回调丢失 | 主动查单轮询（status=pending timeout） | 拉起查单任务 → 补偿状态 |
| 签名为空/篡改 | 验签失败 | 丢弃 + 告警（信任边界） |
| 渠道侧退改规则变动 | 订单操作返回错 | 展示"以渠道为准"，不承诺退改 |

### 6.4 优点 / 风险
- ✅ 真预订闭环：API 下单 + 回调，可做佣金收入，变现潜力最高
- ❌ 资质/审批/联调/对账/合规 = 重资产，小团队单飞不可行
- ⚠ 与"规划层小而锋利"定位冲突；需先有真实用户规模（见 §8 触发条件）

---

## 7. 跨方案共用设计

### 7.1 `plan.bookings` 契约（LLM 不生成，编排层代码回填，沿用 servicing 哲学）
```json
{
  "bookings": [
    {
      "kind": "train" | "hotel",
      "provider": "ctrip" | "qunar" | "12306" | "feizhu" | "tongcheng" | "manual",
      "title": "G1371 杭州东→上海虹桥 09:30-10:30",
      "provider_url": "https://m.ctrip.com/webapp/train/...",
      "price_estimate": 73,
      "currency": "CNY",
      "reference": "plan.generated",     // plan.generated | user.confirmed | channel.callback
      "order_no": null,                  // 用户回填/渠道回调后才有
      "status": "suggested"              // suggested | pending | confirmed | cancelled
    }
  ]
}
```
- 字段全部由代码回填，LLM 只产出 title 整理；`reference` 区分"建议/用户确认/渠道回调"，防幻觉
- `plan.bookings` 不强校验：A/B 未接入时为空数组，前端无预订卡，零回归

### 7.2 `TripBooking` 表（行中追踪 + 凭证回填的主体）
```
id / trip_id(FK) / kind / provider / title / provider_url
order_no / credential / status / amount / currency
created_at / updated_at / confirmed_at / cancelled_at
```
- 状态机：`suggested → pending → confirmed ⇄ cancelled`（只允许带凭证/回调进 confirmed）
- 与 expense 联动：confirmed 的订单可一键"记一笔账"（category=transport/hotel，payer 自由文本）
- 所有权：owner 可改，受邀 token 只读

### 7.3 事件
- 新增 `event_type ∈ {booking.suggested, booking.pending, booking.confirmed, booking.cancelled}` 并入 TripEvent + WS collab feed 广播（复用 event_service._broadcast）
- **可观测**：所有 booking 动作带 trace_id；成本/延迟追踪（按 §7.1 契约）

### 7.4 降级链（沿用 servicing：主路径 → 收窄兜底 → 规则降级 → 人工）
| 优先级 | 路径 | 触发 |
|---|---|---|
| 1 | BookingAgent LLM 整理 + deeplink | 默认 |
| 2 | 纯规则模板（无 LLM） | LLM 失败 |
| 3 | 不产出 bookings（前端隐藏预订卡） | 全部失败或 provider 不可用 |

---

## 8. 方案选择建议（触发条件，非拍板）

| 维度 | 选 A | 选 B | 选 C |
|---|---|---|---|
| 当前阶段（0 真实用户） | ✅ 立即做 | ⚠ 可并行评估 | ❌ 排队 |
| 有 1k+ 日活 / 有商家资源 | ✅（联盟化） | ✅（体验升级） | ✅ 启动资质申请 |
| 商业变现诉求明确 | ✅ 联盟 CPS | ✅ CSP | ✅ API 佣金 |
| 单人 / 小团队工程预算 | ✅ | ⚠ 风险高 | ❌ |

> 结论：**最少步数建议 = A 先行落地（打通"可预订"体验 + 回填闭环），B 作为中期形态观察，C 在真实用户规模到来前不排期**。C+A 架构升级已为"新增采集类 Agent 注册为 PipelineStep"铺好路，A 的成本被显著压低。

---

## 9. 风险与开放问题（评审表）

| # | 开放问题 | 影响 | 建议决策人 |
|---|---|---|---|
| 1 | OTA 外链被改规则/封禁 | A/B 可用性 | 运营侧可配置模板 |
| 2 | 12306 余票接口配额与合规 | B 的真实性上限 | 需联调评估 |
| 3 | 联盟 CPS 需流量承诺 | C 的可行性 | 用户（唯一开发者） |
| 4 | 是否引入"人工代订"（Layla 式） | 商业模型 | 用户（评审） |

---

*关联阅读：docs/articles/06-planning-vs-booking.md · docs/articles/10-endgame-booking-agentic.md（预订层是资本壁垒，规划层小而锋利）*