import http from '../http'

// ── 行程分享（只读链接） ──────────────────────────────────
export const createShare = (tripId) => http.post(`/trips/${tripId}/share`).then((r) => r.data)
export const getSharedTrip = (token) => http.get(`/trips/share/${token}`).then((r) => r.data)

// ── 分享令牌生命周期（TTL / 吊销 / 审计） ─────────────────
export const getShareLifecycle = (tripId) => http.get(`/trips/${tripId}/share/lifecycle`).then((r) => r.data)
export const revokeShareToken = (tripId, kind) => http.post(`/trips/${tripId}/share/revoke`, { kind }).then((r) => r.data)
export const setShareTokenTtl = (tripId, kind, days) => http.post(`/trips/${tripId}/share/ttl`, { kind, days }).then((r) => r.data)

// ── 分享链接访问密码（task-share-gate-eval 前端接线） ──────────
// owner：设置 / 清除（password 空串 = 清除，幂等）；密码绝不回传，只透出 has_password
export const setSharePassword = (tripId, kind, password) =>
  http.post(`/trips/${tripId}/share/password`, { kind, password }).then((r) => r.data)

/**
 * 访客：用访问密码换免验凭证（12h）。
 * - edit=true 走受邀编辑链路的 /edit/{token}/verify（kind 绑定，与 share 凭证不通用）
 * - silent：密码错误由调用方就地提示，不弹全局错误 toast
 */
export const verifySharePassword = (token, password, { edit = false } = {}) =>
  http
    .post(`/trips/${edit ? 'edit' : 'share'}/${token}/verify`, { password }, { silent: true })
    .then((r) => r.data)

// ── 受邀编辑（edit_token：owner 开放/收回编辑权，受邀者免登录受限编辑） ──
export const createShareEdit = (tripId) => http.post(`/trips/${tripId}/share/edit`).then((r) => r.data)
export const revokeShareEdit = (tripId) => http.delete(`/trips/${tripId}/share/edit`).then((r) => r.data)
export const getEditableTrip = (token) => http.get(`/trips/edit/${token}`).then((r) => r.data)
export const updateInvitedStop = (token, stopId, data) =>
  http.patch(`/trips/edit/${token}/stops/${stopId}`, data).then((r) => r.data)
export const reorderInvitedStops = (token, dayId, order) =>
  http.put(`/trips/edit/${token}/days/${dayId}/stops/order`, { order }).then((r) => r.data)
// 受邀编辑地图拖拽（task-map-drag-edit：持 edit_token 免登录移动站点坐标）
export const mapEditInvitedTrip = (token, data) =>
  http.post(`/trips/edit/${token}/map-edit`, data).then((r) => r.data)

// ── 分享页协作（评论 / 站点投票，免登录，凭 share_token） ──
export const getSharedTripComments = (token) => http.get(`/trips/share/${token}/comments`).then((r) => r.data)
export const postSharedTripComment = (token, data) => http.post(`/trips/share/${token}/comments`, data).then((r) => r.data)
export const getSharedTripVotes = (token) => http.get(`/trips/share/${token}/votes`).then((r) => r.data)
export const castSharedTripVote = (token, stopId, value) =>
  http.post(`/trips/share/${token}/votes/${stopId}`, { value }).then((r) => r.data)