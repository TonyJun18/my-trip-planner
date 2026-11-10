import http from '../http'

// ── 收藏灵感夹（登录用户收藏他人分享的行程） ───────────────
export const listFavorites = (params = {}) => http.get('/trips/favorites', { params }).then((r) => r.data)
export const addFavorite = (tripId) => http.post(`/trips/favorites/${tripId}`).then((r) => r.data)
export const removeFavorite = (tripId) => http.delete(`/trips/favorites/${tripId}`).then((r) => r.data)
// ── 收藏 → 一键成路线（task-favorites-to-route） ──────────
// 聚合收藏行程的站点为候选（按名去重，附来源行程标题）
export const aggregateFavoriteStops = (params = {}) =>
  http.get('/trips/favorites/stops', { params }).then((r) => r.data)
// 把收藏的行程复制为我的草稿行程（收藏即许可，未收藏 404）
export const createRouteFromFavorite = (tripId) =>
  http.post(`/trips/favorites/${tripId}/route`).then((r) => r.data)