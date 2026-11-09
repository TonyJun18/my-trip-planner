import http from '../http'

// ── 行中费用记录（task-expense-split-mini；多币种在 task-multi-currency-expense-eval 落地）──
// 费用是「实付」，只对 owner / 受邀编辑者开放；share_token 只读分享页不返回费用。
export const listExpenses = (tripId) => http.get(`/trips/${tripId}/expenses`).then((r) => r.data)
export const addExpense = (tripId, data) => http.post(`/trips/${tripId}/expenses`, data).then((r) => r.data)
export const deleteExpense = (tripId, expenseId) =>
  http.delete(`/trips/${tripId}/expenses/${expenseId}`)
