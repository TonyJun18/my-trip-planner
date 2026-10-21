# task-live-lockscreen-eval 评估记录（2026-10-22）

> 背景：Tripnotes iOS Live Activities（锁屏/灵动岛常驻行程条）是 2026 唯一锁屏行中实现。
> 我们评估 PWA 低成本近似方案。结论：**降级关单（PWA 无等价能力），已有能力（今日视图 + 事件流通知）覆盖核心需求**。

## 一、候选方案矩阵

| 方案 | 可行性 | 体验接近度 | 成本 | 判定 |
|---|---|---|---|---|
| iOS Live Activities / 灵动岛 | ❌ | — | 需原生 App（Swift + ActivityKit） | 不做（项目定位 Web/PWA） |
| 独立窗口常驻进度条（window.open 小窗） | ⚠️ | 低 | 中（多窗口管理 + 用户需手动允许） | 不推荐 |
| PWA 顶栏常驻横幅（应用内） | ✅ | 中 | 低（已有今日视图卡片） | 已在「今日视图」覆盖 |
| Home Screen 状态卡片（PWA shortcut/widget） | ❌ PWA 无标准 widget API | — | 高（需原生壳） | 不做 |
| PWA Notification（系统通知） | ✅ | 中低（非常驻） | 低（已实现，P1-4） | ✅ 已落地 |
| Bitwarden/Chrome 后台 badge（Badging API） | ⚠️ 仅安装 PWA 可用 | 低 | 低 | 可选后续 |

## 二、现状核对

- **行中今日视图**：详情页 live 期间置顶今日卡片（打卡/跳过/顺延 + 进度条），已实现。
- **事件流 + PWA Notification**：修订/打卡/跳过/顺延/评论/投票事件推送系统通知（P1-4），页面在后台时触发。
- **缺失**：锁屏态常驻（不做）；应用图标角标（Badging API，可选）。

## 三、决定

- **关单**：不做锁屏/常驻条等价物。
- 理由：PWA 平台能力不支持 Live Activities/原生 widget；独立小窗体验差、打扰大；
  核心需求（行中知进度、被提醒变更）已由今日视图 + 事件流通知覆盖。
- 后续可选（低优先）：接入 Badging API（`navigator.setAppBadge`）在已安装 PWA 上显示未读事件数，成本 < 1h，需真机验证。

## 四、诚实边界

- 与 Tripnotes 的锁屏体验差距客观存在，是平台能力差异而非工程取舍。
- 若未来上原生壳（Capacitor 已有基础），可再评估 Live Activities / 桌面 widget。