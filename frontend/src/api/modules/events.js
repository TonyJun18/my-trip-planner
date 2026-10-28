import http from '../http'

// ── 行程事件流（task-trip-event-notify：主动通知最小版） ─────────
// 后端契约：GET /trips/{id}/events（owner）/ GET /trips/share/{token}/events（免登录只读）
// → { items: [{id, trip_id, event_type, payload, created_at}], total }
export const getTripEvents = (tripId, params = {}) =>
  http.get(`/trips/${tripId}/events`, { params }).then((r) => r.data)
export const getSharedTripEvents = (token, params = {}) =>
  http.get(`/trips/share/${token}/events`, { params }).then((r) => r.data)

// ── 行程导出（task-export-offline：输出自由 / 数据主权） ──────────
// 后端契约：GET /trips/{id}/export（owner）→ 完整 JSON 快照（trip+days+budget+plan 元信息）
// GET /trips/share/{token}/export（免登录只读，同 share 信任语义）
export const exportTripJson = (tripId) =>
  http.get(`/trips/${tripId}/export`, { responseType: 'blob' }).then((r) => r.data)
export const exportSharedTripJson = (token) =>
  http.get(`/trips/share/${token}/export`, { responseType: 'blob' }).then((r) => r.data)