/**
 * 前端意图埋点（task-trip-detail-refactor 阶段一：基线事件）。
 *
 * 原则（三方拍板，见 docs/prd/2026-10-29-trip-detail-refactor-spec.md §3）：
 * - 不引第三方 SDK；本模块是新端点 POST /api/v1/analytics/events 的唯一前端入口
 * - fire-and-forget：失败静默，不弹错、不重试，不允许影响业务
 * - 完成率类事件（打卡/顺延/跳过/加站）不在此发——判定线走后端 TripEvent 事实流
 * - 只发意图与曝光：planning_tool_open / top_action_click / itinerary_first_view / itinerary_scroll_depth
 *   （阶段二收口补了 workspace_tab_switch / workspace_all_toggle 两个收纳层信号）
 *
 * 实现约束：
 * - **不走 http（axios）实例**：埋点失败/401 必须静默，不能触发全局拦截器的
 *   401 → 踢登录页逻辑；用原生 fetch + keepalive，且 keepalive 保证页面卸载时也送达。
 * - 公共载荷由 trackEvent 自动附加：viewport_width / is_touch / role（详情页=owner）。
 *   trip_id / trip_phase 由调用方传入（挂载点在 TripDetailView orchestrator）。
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

function deviceContext() {
  return {
    viewport_width: window.innerWidth || 0,
    is_touch: typeof window !== 'undefined' && ('ontouchstart' in window || navigator.maxTouchPoints > 0),
  }
}

/**
 * 发送意图事件（fire-and-forget，所有失败静默）。
 * @param {string} name 事件名（后端白名单枚举）
 * @param {object} payload 专有载荷 + trip_id / trip_phase
 */
export function trackEvent(name, payload = {}) {
  try {
    const token = localStorage.getItem('trip_planner_token')
    const headers = { 'Content-Type': 'application/json' }
    if (token) headers.Authorization = `Bearer ${token}`
    fetch(`${API_BASE}/analytics/events`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ name, payload: { ...deviceContext(), ...payload } }),
      keepalive: true,
    }).catch(() => {
      /* 埋点失败静默：不影响业务路径 */
    })
  } catch {
    /* 同步异常也静默 */
  }
}

// 事件名常量（与后端 app/schemas/analytics.py 白名单保持一致）
export const ANALYTICS_EVENTS = {
  planningToolOpen: 'planning_tool_open',
  topActionClick: 'top_action_click',
  itineraryFirstView: 'itinerary_first_view',
  itineraryScrollDepth: 'itinerary_scroll_depth',
  // 收纳层信号（阶段二收口）：G1「工具因收纳而流失」的两种失败形态
  // ①没进工具区 ②进了但 tab 迷路 / 频繁逃到「全部工具」——后者由这两个事件直接代理
  workspaceTabSwitch: 'workspace_tab_switch',
  workspaceAllToggle: 'workspace_all_toggle',
}

/** 由 trip 的起止日期推断当前时机阶段（planning / live / finished）。 */
export function tripPhase(trip) {
  if (!trip?.start_date || !trip?.end_date) return 'planning'
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const start = new Date(`${trip.start_date}T00:00:00`)
  const end = new Date(`${trip.end_date}T00:00:00`)
  if (today < start) return 'planning'
  if (today > end) return 'finished'
  return 'live'
}