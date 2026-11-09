import http from '../http'

// ── 地图拖拽修订（task-map-drag-edit）：拖动 marker 改坐标 → 最小 diff 原子应用 ──
export const mapEditTrip = (tripId, data) => http.post(`/trips/${tripId}/map-edit`, data).then((r) => r.data)

// ── 小红书笔记（方案 A：内容工厂） ─────────────────────────
export const generateXhsNote = (tripId) => http.post(`/trips/${tripId}/xhs-note`, { provider: 'auto' }).then((r) => r.data)

// ── 小红书发布通道（方案 C：策略 + 工厂，default manual） ────
// 通道能力：mode=manual（复制）/ rpa（自动填表）；requires_images 决定是否先传封面
export const getXhsChannels = (tripId, mode) =>
  http
    .get(`/trips/${tripId}/xhs-channels`, { params: mode ? { mode } : {}, silent: true })
    .then((r) => r.data)
// 封面图上传（canvas dataURL → 服务端落盘），返回 asset_id
export const uploadXhsAsset = (tripId, dataUrl) =>
  http.post(`/trips/${tripId}/xhs-assets`, { data_url: dataUrl }).then((r) => r.data)
// 建发布任务（202 + job_id），前端轮询
export const publishXhsNote = (tripId, data) =>
  http.post(`/trips/${tripId}/xhs-publish`, data).then((r) => r.data)
export const getXhsPublishJob = (tripId, jobId) =>
  http.get(`/trips/${tripId}/xhs-publish/${jobId}`).then((r) => r.data)

// ── 对话式修订行程（方案 B） ──────────────────────────────
export const reviseTrip = (tripId, data) => http.post(`/trips/${tripId}/revise`, data).then((r) => r.data)