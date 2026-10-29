# task-meal-walk-anchors-eval 评估记录 · 2026-10-30

> 来源：2026-10-30 竞品分析（Passage AI 行中预订管理 + 步行体验微调）——「餐饮放进合理时段 + 站间步行分钟数」是 Passage AI 步行导向核心；我们已有类目营业基准/体力系数，缺餐饮窗口锚定、无站间步行时长。

## 结论

**① 餐饮时段锚定：✅ 评估通过，实现最小版（纯规则零凭证）**
**② 站间步行估算：❌ 评估不过，降级关单（与 open-hours-real / price-alert 同构：免费真实源不存在）**

## ① 餐饮锚定（已实现）

### 设计
- `MEAL_WINDOWS` 规则表：breakfast 07:00-10:00 / lunch 11:30-14:00 / dinner 17:00-21:00（半开区间宽口径）
- `_classify_meal_window(arrival_minutes)` 纯函数：窗口内 → (key, window)；明确间隙 → (gap_key, 建议窗口)
- 间隙定义（只覆盖真正值得提醒的明确偏离）：
  - `gap_early` < 07:00：多数餐厅未开门
  - `gap_brunch` 10:00-11:30：多数餐厅午市未开
  - `gap_afternoon` 14:00-17:00：午市收、晚市未开——**最典型翻车场景**
  - `gap_late` ≥ 21:00：多数餐厅已收市
- `_ALL_DAY_MEAL_EXEMPT_KEYWORDS` 全天候类目豁免：夜市/夜宵/烧烤/大排档/酒吧/精酿/居酒屋/咖啡/茶馆/甜品/下午茶/面包/烘焙/奶茶/快餐/便利店/小吃——宽时段营业不受窗口约束，不误伤
- 检出 → `CritiqueIssueSchema` 兼容 issue（severity=warning / category=schedule / message / suggestion / day_number），与闭馆到达/体力负荷共用 `plan.time_gate.issues` + 前端 timegate-card 透出通道；`basis=rule_based` 诚实标注
- i18n zh/en 双键：`timegate.meal.{breakfast,lunch,dinner}` / `timegate.msg.meal_anchor` / `timegate.suggest.meal_anchor`

### 落点
- `backend/app/services/time_validation.py`：规则表 + `_classify_meal_window` + `check_plan_time_gate` 内新增餐饮锚定循环（独立 pass，cursor 复用）
- `backend/app/i18n/translations.py`：zh/en 各 5 键
- `backend/tests/test_time_validation.py`：+6 组餐饮锚定专项（窗口正常/午晚空档/深夜+夜市豁免/全日豁免/cursor 推进/早餐边界）

### 为什么不是独立服务
餐饮锚定与闭馆到达共享同一「到达时刻推算」逻辑，放进 `check_plan_time_gate` 自然复用 cursor/结构，避免重复实现；前端零改动（timegate-card 已通用）。

## ② 站间步行估算（降级关单）

| 方案 | 凭证 | 精度 | 结论 |
|---|---|---|---|
| 城市中心 POI 间 5-15 分钟规则估算 | 零凭证 | 中低：同城 5-15 分钟对市中心（1-3km）尚可，但跨城/远郊站点会臆断 | 规则估算作为「步行导向」不可靠，且有与 DrivingGate（自驾）语义重叠/矛盾风险 |
| 高德步行路径 API（v3/walking） | AMAP_API_KEY | 高（dist + duration） | 需凭证；项目当前 DRIVING_ROUTE_SOURCE 未启用 amap 时恒降级，同类钥匙不新增 |
| Google Directions（walking） | 需凭证 | 高 | 需凭证，关单 |
| OSM OSRM walking profile | 零凭证但自托管 | 依赖部署 | 引入外部服务 + 运维成本，单 worker 窗口不足 |

**结论**：维持「站间交通不在时间规则库」现状（`time_validation` 注释已声明），站间步行时长如未来接入真实路径，应并入 `amap_driving.py` 同款「配置切换 + API key + 熔断降级」模式（DRIVING_ROUTE_SOURCE == 'amap' 时复用同一钥匙走 walking profile），本夜不做。

## 验收对照（todo）
- [x] 评估记录（本文件）
- [x] 餐饮锚定 warning + 测试覆盖（test_time_validation.py +6 组）
- [x] 站间步行：降级关单（数据源矩阵如上）
- [x] 专项测试全绿 + 全套回归（见分支 commit 记录）