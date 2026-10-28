import http from '../http'

// ── 行中「今日视图」（task-live-today-view：MonkeyTravel live trip 差异化） ──
export const getLiveSnapshot = (tripId) => http.get(`/trips/${tripId}/live`).then((r) => r.data)
export const checkLiveStop = (tripId, stopId, checked = true) =>
  http.post(`/trips/${tripId}/live/stops/${stopId}/check`, { checked }).then((r) => r.data)
export const skipLiveStop = (tripId, stopId) =>
  http.post(`/trips/${tripId}/live/stops/${stopId}/skip`, null).then((r) => r.data)
export const delayLiveTrip = (tripId) =>
  http.post(`/trips/${tripId}/live/delay`, null).then((r) => r.data)

// ── 行中「今日视图」受邀编辑版（免登录，凭 edit_token；ShareView 同伴操作） ──
export const getLiveSnapshotByToken = (token, edit = true) =>
  http.get(`/trips/${edit ? 'edit' : 'share'}/${token}/live`).then((r) => r.data)
export const checkLiveStopByToken = (token, stopId, checked = true) =>
  http.post(`/trips/edit/${token}/live/stops/${stopId}/check`, { checked }).then((r) => r.data)
export const skipLiveStopByToken = (token, stopId) =>
  http.post(`/trips/edit/${token}/live/stops/${stopId}/skip`, null).then((r) => r.data)
export const delayLiveTripByToken = (token) =>
  http.post(`/trips/edit/${token}/live/delay`, null).then((r) => r.data)
// 只读分享版今日快照（share_token 免登录查看，不支持操作）
export const getLiveSnapshotShared = (token) => getLiveSnapshotByToken(token, false)