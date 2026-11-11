# 行程详情页 · 日程时间轴化（方案 A）设计稿

**Date**: 2026-11-11
**Status**: 待用户确认
**依据**: 真机体验实证 + `docs/superpowers` 探索报告（代码取证券见文中引用）
**后续**: 方案 B（质检→行动闭环）、方案 C（站点卡信息增强）将各自独立 OpenSpec change 接续

---

## 0. 一句话结论

给「每日站点」补一层**读取时确定性计算的起止时刻**（visit_start/visit_end + 段间交通耗时），
让详情页日程卡从「无时刻的站点列表」升级为「时刻流水线 + 全天时间窗口」，
过载（如 D2 全天 17h30m）在时间轴上自然可视；**不改 Stop 表结构、不碰任何写路径**，
时刻是派生值（ephemeral derived），与「预算由代码重算、口径诚实标注」的既有哲学同构。

---

## 1. 问题（真机实证）

| # | 问题 | 证据 |
|---|---|---|
| P1 | 日程卡只有 `N 站 · ¥587 · 17h30m`，用户看不到「几点出发、几点到哪」，17.5h 过载毫无感知 | `TripDetailDayCard.vue:34-58` 求和渲染；`Stop` 无时间字段（`models/trip.py:115-135`） |
| P2 | 站点行只有价格+时长，无时刻、无段间交通，行程"一天"没有时间边界 | `TripDetailDayCard.vue:185-188`、`live_service.py:80-130`（今日快照同样无时刻） |
| P3 | TimeGate 已有 cursor 推时刻的能力（过饱和/闭馆告警），但结果只是 warning 文字，没有可视化 | `time_validation.py:407-441` cursor 循环 |
| P4 | 轻量顺带：问答卡把「接口错误」渲染成「还没有可答的结构化数据」，误导 | `TripDetailQaCard.vue`（旧后端 404 时实测误导文案） |

## 2. 方案比较

### A1 读取时派生（推荐 ✅）

新增 `schedule_service.py` 纯函数排程器，读取路径（GET /trips/{id}、GET /share/{token}）计算并注入
派生字段；Stop 零 DDL，写路径（修订/PATCH/重排/删除/AI diff）零挂钩 → **不存在「时刻脏数据」问题**
（调研报告核心风险全部规避）。

- ✅ 最小改动；所有写操作后时刻自动正确（重排了 → 下次读取重算）
- ✅ 与 `budget_service.compute_budget` 读取路径重算的成熟范式同构（`budget_service.py:160`）
- ✅ 多城市「交通占位站」（已带 `visit_start="09:00"`）天然接入
- ⚠️ 用户手动固定某一站时刻（如「15:00 是硬性航班」）不在本期（可作 B/C 扩展）

### A2 持久化 visit_start 列（否决，留作后续扩展）

DDL + 迁移 + `revise_service` 白名单/PATCH/reorder/add/planning 落库五处挂钟 +
`_plan_snapshot` 补序列化 → 改动面大、且调研确认存在 remove/reorder 后脏时刻风险。
**仅当未来需要「用户手动锁定时刻」时再立项**（可作为方案 C 的一部分）。

### A3 LLM 输出时刻（否决）

`validate_plan` `extra="ignore"` 会静默丢弃 LLM 输出的时间字段（`schemas/plan.py:18`），
需要同时改 StopSchema + 提示词 + 自纠正回路；与仓库「LLM 理解、代码执行」哲学相悖
（时刻这种确定性数值应由代码算，LLM 只决定顺序——顺序它已经在出了）。

## 3. 方案 A1 详细设计

### 3.1 后端排程器 `backend/app/services/schedule_service.py`（新建）

纯函数（零 IO、零 LLM），从 `time_validation.py` 的 cursor 循环抽出并增强：

```python
@dataclass
class StopScheduleItem:
    stop_id: str
    start: str | None        # "09:30"（HH:MM）；None = 无法排（无坐标且无锚点仅限占位兜底,兜底永远可排）
    end: str                 # "11:30"（含游玩时长）
    travel_to_next_minutes: int | None  # 到下一站的段间交通估算（None = 最后一站）

def schedule_day(stops: list[Stop], *, start: tuple[int, int] = (9, 0)) -> list[StopScheduleItem]
```

规则（确定性、口径诚实 `basis=rule`）：
1. **起点**：日首站显式锚点优先（today plan_json `visit_start`），否则 `DAY_START=(9,0)`
   —— 与 `time_validation.DAY_START` 同一常量（单一出处，import 复用）。
2. **游玩时段**：逐站 `start → start + estimated_duration_minutes`。
3. **段间交通**：`estimate_drive_minutes(prev.lat/lng → cur.lat/lng)`（`driving_service.py:47`
   球面距离 ÷ 50km/h）作为 gap 插入，`travel_to_next_minutes` 同步输出给前端。
4. **住宿站特判**：hotel 的 720min 是「过夜停留」不是游玩——**不占时段**，
   渲染为 `入住 {end}`（只有到店时刻）。
5. **跨夜钳制与过载信号**：`end` 跨入次日（>24:00）时钳制为 `24:00` 并返回
   `overflow=True`；全天窗口跨度（首站 start → 末站 end）>12h 也返回 overflow ——
   对应 P1/D2 17h30m 的可视化预警，与 TimeGate 过饱和告警口径互补。
6. **交通占位站**：识别 `details.is_transfer`（见 3.2）→ 时段照常排但前端渲染为
   🚄 交通样式（不当作景点游玩）。
7. **日级窗口**：`schedule_day` 返回 items + `day_window {start, end, overflow}`。

### 3.2 占位站标记持久化（两行白名单补丁）

`planning_service._persist_trip`（`planning_service.py:314-319`）details 白名单补
`is_transfer`——把 plan JSON 中 multi_city 占位站的 `is_transfer` 带入落库。
存量行程兼容：`is_transfer` 识别回落到名称匹配 `（交通占位）` 后缀（`multi_city.py:141`）。

### 3.3 读取路径注入（响应层，不改 ORM）

`backend/app/schemas/trip.py`：
- `StopOut` 增 `visit_start: str | None = None`、`visit_end: str | None = None`、
  `travel_to_next_minutes: int | None = None`、`is_transfer: bool = False`（派生字段，非存储，
  与 `TripOut.escalated` 派生字段先例一致，`schemas/trip.py:108-109`）。

`backend/app/api/v1/trips_crud.py` `get_trip`（`:79-87`）：`TripOut.model_validate(trip)` 后
调用 `schedule_service.attach_schedule(trip_out)`（读 Stop 集合 → 逐日 schedule_day →
回填派生字段）。同一挂点复用到：
- Owner 详情路由 `GET /trips/{id}`（trips_crud:get_trip）
- 免登录分享路由 `GET /trips/share/{token}`（`trips_share.py`，ShareView 也渲染日程列表）
- 行中快照 `GET /trips/{id}/live`（`live_service.py:88-98` stops 补 `visit_start/end`，
  行中打卡视图同步有时刻）

不出现在 `/days/{day_id}/...` 写响应（写路径继续返回既有 7 字段，前端 diff 更新时
保留派生字段由下次整读刷新——与现有 `load()` 全量重载行为一致）。

### 3.4 前端渲染

`frontend/src/components/trip-detail/TripDetailDayCard.vue`（站点行已有 stop-rail 时间轴视觉骨架）：
1. `stop-meta` 行首加时刻徽标 `🕐 09:00–11:30`（时间归一小时最小单位，与后端口径一致）。
   hotel 站渲染 `🏨 入住 21:00`；is_transfer 站渲染 `🚄 交通` + 占位样式（非游玩）。
2. 站点间插入段间交通 chip `🚶 15 分钟`（`travel_to_next_minutes`：≤1.5km 步行 /
   ≤8km 公交 / 其他 打车——复用 servicing 阈值口径文案，本地简单规则，与
   `servicing_service._transit_mode_for_distance` 同参数）。
3. **日头窗口**：`D2 2026-10-30 · 08:30 → 21:00 · 4 站 · ¥587`（窗口替代 17h30m 裸时长；
   overflow 时红色高亮 + tooltip「时间超出一天，建议让 AI 压缩」——为方案 B 留 action 挂点）。
4. 站点编辑弹窗**本期不加时间字段**（时刻为派生值，手动改时刻属 A2 范畴）。

`TripDetailLiveToday.vue`：今日卡站点行加时刻徽标（从 live snapshot 新字段渲染）。

i18n：`schedule.startTime` / `schedule.checkin` / `schedule.transfer` / `schedule.travelChip`
/ `schedule.overflow` 等 zh/en 各 ~6 键。

### 3.5 轻量顺带：问答卡错误态修复

`TripDetailQaCard.vue`：API 非 200（网络/404/500）时显示独立错误文案
「数据加载失败，请稍后重试」+ 重试按钮，与「还没有可答的结构化数据」空态区分。

## 4. 验收标准（成功定义）

1. `pytest` 新增专项全绿：
   - schedule_service 单测：正常日（9:00 起点顺序累加）、hotel 日（住宿不占时段）、
     占位站（details.is_transfer / 名称兜底）、无站点日、跨夜 overflow、段间 gap 计算。
   - API 测试：`GET /trips/{id}` 响应含 visit_start/visit_end/travel_to_next_minutes/is_transfer；
     `GET /trips/share/{token}` 同样含；`GET /trips/{id}/live` stops 含时刻。
   - 写路径回归：修订/重排/PATCH 后再次 GET，时刻反映新顺序（派生一致性）。
2. 前端 `npm run build` 通过；i18n zh/en 键齐全。
3. 真机验收（Playwright）：上海行程详情页 D 卡显示时刻流水线，D2 overflow 高亮，
   行中今日卡有时刻。
4. 453 个既有测试全绿（零回归）。

## 5. 风险与边界

| 风险 | 处置 |
|---|---|
| 手动 PATCH 改 `estimated_duration_minutes` 后时间轴 | 读取时重算 → 自动正确（A1 天然免疫） |
| reorder 后过优化（day_optimizer 最近邻）顺序 | 同上 |
| 旧行程（无坐标） | `estimate_drive_minutes` 无坐标返回兜底 180min？——排程器对无坐标站跳过 gap（相邻直接顺延），与 servicing「缺坐标跳过不编造」一致 |
| 性能 | 纯函数 + 已加载集合，每读一次 <1ms 量级 |
| 主题去重 | 时刻口径与 TimeGate cursor 常量一致（DAY_START 单一出处） |
