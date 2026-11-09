import http from '../http'

// ── 机票特价（FlightDeals：全网收集 → 2–3 个方案 → 用户确认） ──
// 口径：返回的 price_kind 恒为 from（航线页最低「起价」），确认选择 ≠ 已订。
export const getFlightDeals = (tripId, { refresh = false } = {}) =>
  http.get(`/trips/${tripId}/flight-deals`, { params: refresh ? { refresh: 1 } : {} }).then((r) => r.data)

// 确认一个方案：optionId 来自 getFlightDeals 的 options[].option_id；
// 也支持手动兜底 { option: { title, price, currency, source_url } }。
export const chooseFlight = (tripId, payload) =>
  http.post(`/trips/${tripId}/flight-choice`, payload).then((r) => r.data)

export const clearFlightChoice = (tripId, bookingId) =>
  http.delete(`/trips/${tripId}/flight-choice`, {
    params: bookingId ? { booking_id: bookingId } : {},
  })
