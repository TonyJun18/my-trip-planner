import http from '../http'

// ── planner（异步任务） ───────────────────────────────────
export const planTrip = (data) => http.post('/planner/plan', data).then((r) => r.data)
export const getPlanTask = (taskId) => http.get(`/planner/tasks/${taskId}`).then((r) => r.data)

// ── 行程备选方案（Plan B：确定性规则生成，无 LLM） ─────────
export const getPlanB = (tripId) => http.get(`/trips/${tripId}/plan-b`).then((r) => r.data)