import http from '../http'

// ── 质检报告（task-trip-quality-report-a/b：五类只读聚合 + 导出） ──
// owner（JWT）与分享令牌（免登录只读）双路径；只含质检结论，不含任何凭证。
export const getQualityReport = (tripId) =>
  http.get(`/trips/${tripId}/quality-report`).then((r) => r.data)
export const getSharedQualityReport = (token) =>
  http.get(`/trips/share/${token}/quality-report`).then((r) => r.data)