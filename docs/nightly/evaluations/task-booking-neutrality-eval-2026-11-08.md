# 评估记录 · 预订中立性显性化（task-booking-neutrality-eval）

- 日期：2026-11-08
- 类型：候选评估（backend/docs，纯文档 + 前端文案，无新后端代码）
- 来源：docs/nightly/competitive-analysis/2026-11-07.md（行动项 2）+ 2026-11-08.md（三组新证据）
- 结论：**评估通过，采用方案 B 最小版（显性声明）已落地**；方案 C（中性比价聚合）记录为「需资质/佣金冲突，关单」，方案 D（自建预订闭环）沿用 10-28 决定继续不做。

## 1. 问题

10-28 我们把「预订」做了方案 A：`booking_service` 只组装**公开跳转链接**（携程/去哪儿/12306/飞猪/同程的 train、hotel 检索页），不自建库存、不代收资金、不伪造「已订」；用户在 OTA 完成交易后回来粘贴确认号回填（`TripBooking` 状态机 `suggested → pending → confirmed ⇄ cancelled`，`confirmed` 必须带凭证）。

当时这是**成本与合规上的取舍**。2026-11 的市场变化让这件事多了一层含义：它变成了**产品立场**。

11-07 与 11-08 两夜证据：

| 竞品 | 现状 | 含义 |
|---|---|---|
| Airbnb | Q3 电话会（2026-11-05）宣布自建可视化 AI agent，通过 MCP 连接外部服务，目标是自家库存 | 自营闭环 + 自建入口 |
| Mindtrip | 已在 chat 内**直接成交**机票与酒店（此前只有研究/收藏）+ Personal Travel Assistant 盯价 | 从规划层越到交易层 |
| Layla | 被 Expedia 收购（2026-07-31）后转为「AI 规划 + 真人 Travel Expert 成交」打包行程 | 独立工具被收编后的归宿 |
| Expedia / Booking / Trip.com / Hilton / Marriott | 一周内全量上线自家 AI planner，且只导流自家库存 | 「规划入口」= 「货架入口」 |

→ 结论：**「免费给你规划、然后中立地把你送去买」正在从行业默认变成稀缺位**。我们已经在做，但从来没有说过。

## 2. 现状核验（代码事实，2026-11-08）

| 事实 | 证据 |
|---|---|
| 预订只有外链，无库存/无资金 | `backend/app/services/booking_service.py:58 _deeplink` 纯函数拼 `_PROVIDER_HINT` 模板；`Provider = ctrip/qunar/12306/feizhu/tongcheng/manual` |
| **外链不含任何联盟/返佣参数** | `grep -rn "affiliate\|utm_\|allianceid\|sid=" backend/app/services/booking_service.py` → 0 命中 |
| 不给 LLM 碰交易 | 同上文件头注释：`provider_url 是纯规则组装，不经过 LLM、不伪造"可订"` |
| 状态机防伪造 | `suggested → pending → confirmed ⇄ cancelled`，`confirmed` 必须带 `order_no`/`credential`（`BookingStateError`） |
| 数据自由已具备 | `GET /trips/{id}/export` + `GET /trips/share/{token}/export`（JSON，含 stops/预算/质检元信息，令牌零输出） |
| 声明缺失 | 落地页 4 张价值卡与 README 都没有一句「我们不卖货、不拿返佣」；README「已知局限」表把「无预订/支付闭环」只写成**缺点** |

## 3. 方案矩阵

| 方案 | 内容 | 成本 | 风险 | 结论 |
|---|---|---|---|---|
| **A 维持隐含** | 什么都不说，代码里天然中立 | 0 | 用户/读者无法把这个事实与竞品区分开；在与 OTA 的对比中看起来只是「功能缺失」 | 不选 |
| **B 显性声明（最小版）** | 落地页价值卡 + README 章节 + 「已知局限」表改写为「有意边界」 | 1 个前端卡片（2 处 i18n 键）+ 1 段 README + 1 行表格改写；**零后端、零凭证、零迁移** | 声明与行为必须持续一致（见 §5） | ✅ **采用** |
| **C 中性比价聚合** | 同屏并列多家 OTA 报价（可能带联盟参数） | 需分销/联盟资质、报价源、合规评审 | 一旦带返佣，中立声明即失效；不带返佣则无收入也无差异化 | 关单（与 10-28 booking-closure 结论一致） |
| **D 自建预订闭环** | 接分销 API、代收资金、库存同步 | 数月 + 资金/合规/客服 | 与「小而锋利的规划层」定位冲突 | 沿用 10-28 决定：不做 |

## 4. 已实施（最小版）

1. **落地页第 4 张价值卡**（`frontend/src/views/LandingPage.vue::whyPoints`）：`landing.whyNeutralTitle/Desc` —— 「规划不卖货：不碰库存、不拿佣金、不藏价格，预订只给公开跳转，行程随时导出」。复用既有 `why-grid`（`auto-fit minmax(260px)`）自动排布，无新增样式。
2. **README 新增「中立立场」小节** + 改写「已知局限」表中「无预订/支付闭环」一行：从「缺点」改述为**有意边界**，并注明联盟/返佣为零的代码事实。
3. i18n：`zh-CN.js` / `en-US.js` 各补 2 键（`npm run check:i18n` 919 → 921 键双侧齐）。

验收：`npm run build` 通过、`npm run check:i18n` 无重复无缺失、落地页中英文均显示新卡片（无原始 key）；纯文案改动，无后端测试需求（既有 `test_booking_service.py` / `test_export_*` 不受影响，本日全量回归一并跑）。

## 5. 残余风险与后续约束

1. **声明与行为一致性是硬约束**：任何未来接入联盟/返佣/自营库存的动作，必须先更新本声明与落地页卡片，否则视同违反产品承诺。
2. **不做「隐藏排序偏置」**：若将来接多家报价，排序规则必须公开口径（当前无此能力，仅记录约束）。
3. **内容侧衔接**：15 文《收购季》已论证「深度 + 中立」两缝隙；本文档可作为 15 文后续「中立不是姿态，是可验证的工程事实」段落的素材落点（含 `_deeplink` 无联盟参数、`export` 双路径两条可验证事实）。
