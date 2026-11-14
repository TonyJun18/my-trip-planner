# trip-detail-schedule-timeline 交付结果与验证证据

> 交付日期：2026-11-14（实现 2026-11-11 完成，真机验证因 Chrome CDP 失效延至今日补齐）
> 工作流：superpowers-openspec-execution-workflow（探索 → OpenSpec 锁定 → TDD 实现 → 归档）

## 实现落点（已由用户 review 提交）

- **后端 `1a78f53`**：`schedule_service.schedule_day` 纯函数（日起点 9:00 与 TimeGate 同源 + 球面距离估时）+ 三读路径注入（`GET /trips/{id}`、分享 token、行中 live 快照）+ `StopWriteOut` 写路径契约隔离（零 DDL、写路径零挂钩）+ `planning_service._stop_details` 白名单补 `is_transfer`
- **前端 `ea80e1c`**：`TripDetailDayCard` 时刻徽标/段间交通 chip/日头时间窗口/过载红色高亮 + `TripDetailLiveToday` 时刻徽标 + `TripDetailQaCard` 错误态与空态分离 + i18n zh/en 对齐（check:i18n 1163 keys × 2 通过）

## 验证证据（2026-11-14 补齐）

1. **测试回归**：`test_schedule_service` / `test_trip_schedule_api` / `test_planning_details_whitelist` 共 **21 passed**（当前 HEAD，3 天演进后仍绿）
2. **API 派生口径**（curl）：D1 `09:00→15:03`；D2 酒店到店 `09:00~09:00`（不占时段）、`（交通占位）磁悬浮` 名称兜底 `is_transfer=true`、末站 `18:12~24:00` 跨夜钳制 + 过载信号
3. **真机渲染**（playwright-cli，上海测试行程 `f53a0d79-8f5c-4dd8-b9fe-e5840427f3bc`）：
   - D2 时刻流水线：`入住 09:00` / `09:20–17:20` / `🚄 17:37`（紫色）/ `18:12–24:00`，段间 chip `🚌 20min / 🚌 17min / 🚶 5min`
   - 日头窗口：`09:00 → 24:00 ⚠ 超出一天` 过载徽标（tooltip 给出「让 AI 压缩」hint）
   - 截图：`/tmp/trip-detail-timeline-d2-overflow.png`、`/tmp/trip-detail-timeline-qa-error.png`
4. **派生一致性（task 4.2）**：PATCH D1 人民广场 120→240 分钟 → 页面重载后全日时刻顺延（`09:00→13:00`、日头 `09:00→17:03`），且写路径响应**无**派生字段泄漏（StopWriteOut 契约）
5. **QA 错误态**：route mock 500 → 「数据加载失败 + 重试」红调错误态（与空态文案分离）；解除 mock 点重试 → facts 正常加载（闭环）

## 归档

- `openspec archive trip-detail-schedule-timeline --yes` → `archive/2026-11-14-trip-detail-schedule-timeline`，spec 合入 `openspec/specs/trip-schedule-timeline/spec.md`（+3 requirement）
- 归档 commit：见本文件同日 chore(openspec) 提交

## 备注

- 验证用测试账号 `timeline-verify-20261114@test.local`（注册于本地 dev DB），行程「时间轴验证行程」未删除，可在 5174 端口 dev server 登录查看
- 本 harness 下 nohup 后台进程不能跨命令存活，dev server 须用 shell background 模式启动
- 方案 B（质检→行动闭环）与方案 C（站点卡信息增强）为后续独立 OpenSpec change，用户明确顺序 A → B → C
