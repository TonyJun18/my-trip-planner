# Design — trip-detail-schedule-timeline

## Context

调研实证（`docs/superpowers/specs/2026-11-11-trip-detail-schedule-timeline-design.md` §2 比较与 §7 挂点）：

- `Stop`（`models/trip.py:115-135`）无任何时间字段；`StopOut/StopUpdate` 白名单 7 字段（`schemas/trip.py:16-43`）。
- plan JSON 约定层已四处消费 `visit_start / open_hours`（`time_validation.py`、`multi_city.py`、`property_qa_service.py:52`、`dynamic_facts.py:191`）；`validate_plan` `extra="ignore"` 会丢弃 LLM 输出的时间字段（`schemas/plan.py:18`）。
- `time_validation.py:407-441` 的 cursor 推进本质是排程模拟器：`DAY_START=(9,0)` 起点逐站累加时长，显式 `visit_start` 优先。
- `driving_service.estimate_drive_minutes`（球面距离 ÷ 50km/h）与 servicing 阈值口径（≤1.5km 步行 / ≤8km 公交）可复用。
- `_recompute_budget`（`revise_service.py:563-651`）是「读取路径重算」的成熟范式（`budget_service.compute_budget` 读取路径版同构）。
- multi_city 占位站已带 `visit_start="09:00" / is_transfer=True`（`multi_city.py:135-153`），但 `planning_service._persist_trip` details 白名单（`:314-319`）只落 `source/source_url/address/geo/rating`，is_transfer 丢弃；落库后仅名称「前往{city}（交通占位）」可辨认。
- 读取路径：owner 详情 `GET /trips/{id}`（`trips_crud.py:79`，`TripOut.days[].stops[]`）、分享 `GET /trips/share/{token}`、行中快照 `GET /trips/{id}/live`（`live_service.py:80-130`，stops 无时刻）。

## Goals / Non-Goals

**Goals**
- 详情页日程卡与行中今日卡、分享页日程具备时刻流水线与全天时间窗口；过载可视。
- 排程纯确定性、零 LLM、零网络；写路径零挂钩，读取重算（永不脏）。

**Non-Goals**
- 不做用户手动固定站点时刻（A2 持久化列，留作后续 change/方案 C 扩展）。
- 不改写路径（修订/PATCH/重排/diff 内核白名单不动）。
- 不让 LLM 输出时刻（不改 `StopSchema` 与 planner 提示词）。
- 不做日级日历视图/周视图（仅日卡内时间轴）。

## Decisions

### D1. 时刻为读取路径派生值，非持久化列（选择 A1）

响应层注入派生字段（`StopOut` 新增可选 `visit_start / visit_end / travel_to_next_minutes / is_transfer`，
与 `TripOut.escalated` 派生字段先例一致）。
- 替代案 A2（持久化列）：DDL + 迁移 + 5 处写路径挂钟 + `_plan_snapshot` 补序列化，remove/reorder 产生脏时刻，改动面 10 倍且收益仅是「可手动锁定时刻」（本 change 不需要）。
- 替代案 A3（LLM 输出时刻）：`extra="ignore"` 会静默丢弃，需改 schema+提示词+自纠正回路；且时刻属确定性数值，按「LLM 理解、代码执行」哲学应由代码算。

### D2. 排程器收敛为单一纯函数 `schedule_service.schedule_day`

从 `time_validation` cursor 循环抽出语义并增强（通行 gap、住宿特判、跨夜钳制、过载信号），
`DAY_START` 从 `time_validation` import（单一出处，两处口径永不漂移）。
返回结构：`items[stop_id, start, end, travel_to_next_minutes, is_transfer]` + `day_window{start, end, overflow, span_minutes}`。
- 住宿站语义：不占时段队列，记「到店时刻」（其后的站点从该时刻顺延新游玩段），渲染「入住 HH:MM」。
- 跨夜钳制：`end > 24:00` 钳到 `24:00` 并触发 overflow；跨度 >720min 亦 overflow。
- 无坐标相邻对：gap 跳过不编造（与 servicing「缺坐标跳过」一致）。
- 显式锚点：plan JSON 内该站 `visit_start`（新落库占位站）优先于 09:00 起点默认——本期锚点只覆盖占位站（存量行程名称兜底），用户手动锚点非本期。

### D3. 注入挂点：三个读取路径统一走 `schedule_service.attach_*`

`trips_crud.get_trip`、`trips_share` 分享读路径、`live_service.live_snapshot` 序列化后/返回前统一调用一个注入函数（输入 stops 集合，输出回填字段），避免三处各自实现口径。写路径响应（POST/PATCH/PUT stops、revise）不注入——前端写操作后走既有 `load()` 全量重载。

### D4. is_transfer 持久化到 `details` JSON + 名称兜底

`planning_service._persist_trip` details 白名单补 `is_transfer`（未来占位站新数据自动带标记）；存量行程由排程器按名称后缀「（交通占位）」识别（`multi_city.py:141` 命名是稳定出处）。

### D5. 前端渲染收敛在 DayCard / LiveToday，窗口由前端聚合

日头窗口（`08:30 → 21:00` + overflow 高亮）由前端从 stops 派生字段聚合（不再加 day 级响应字段，减少响应契约面）；段间交通 chip 文案复用 servicing 阈值口径（步行/公交/出租车），仅本地换算函数。QA 卡错误态：fetch catch 分支独立渲染 + 重试按钮。

## Risks / Trade-offs

- [时刻口径与 TimeGate 告警不一致] → DAY_START 单一出处 import；schedule 与 time_gate 同为规则口径文档标注 `basis=rule`（诚实口径哲学）。
- [极端日（>24h 钳制）与 TimeGate 过饱和告警重复提示] → 钳制仅在响应派生层，不改 time_gate；前端 overflow 高亮与质检卡 badge 共存但分通道。
- [每读一次重算的性能] → 纯函数 + 已加载集合，单日 O(n)；实测 NYC 级（31 天 × 20 站）上限仍 <5ms。
- [派生字段混入 StopOut 导出/分享导出 JSON] → export 路径（`export.py`）本期不注入，导出物保持既有 schema，避免消费方契约面扩大；如需导出时刻属后续 change。

## Migration Plan

纯增量：新服务文件 + schema 可选字段 + 三个读路径注入 + details 白名单两行。无 DDL、无环境变量、无迁移命令。
回滚：revert 单 commit 即回到基线（响应字段消失，前端对缺失字段渲染为无时刻旧行为——样式已做 None 兜底）。

## Open Questions

- 行中今日卡的「顺延」（delay_today）是否需要在顺延提示里引用时刻？—— 本期仅展示时刻，不动 delay 语义；留待方案 B（质检/行动）时顺带评估。
