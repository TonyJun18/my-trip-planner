import http from '../http'

// ── 地图拖拽修订（task-map-drag-edit）：拖动 marker 改坐标 → 最小 diff 原子应用 ──
export const mapEditTrip = (tripId, data) => http.post(`/trips/${tripId}/map-edit`, data).then((r) => r.data)

// ── 小红书笔记（方案 A：内容工厂） ─────────────────────────
export const generateXhsNote = (tripId) => http.post(`/trips/${tripId}/xhs-note`, { provider: 'auto' }).then((r) => r.data)

// ── 对话式修订行程（方案 B） ──────────────────────────────
export const reviseTrip = (tripId, data) => http.post(`/trips/${tripId}/revise`, data).then((r) => r.data)