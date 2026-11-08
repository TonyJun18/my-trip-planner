import http from '../http'

// ── planner（异步任务） ───────────────────────────────────
export const planTrip = (data) => http.post('/planner/plan', data).then((r) => r.data)
export const getPlanTask = (taskId) => http.get(`/planner/tasks/${taskId}`).then((r) => r.data)
// 规划额度快照（task-quota-governance-eval）：最近 24h 次数 + 参考阈值；只提示不拦截。
// silent：未登录/接口异常时不弹错误提示，由调用方静默隐藏。
export const getPlanQuota = () => http.get('/planner/quota', { silent: true }).then((r) => r.data)

// ── 行程备选方案（Plan B：确定性规则生成，无 LLM） ─────────
export const getPlanB = (tripId) => http.get(`/trips/${tripId}/plan-b`).then((r) => r.data)