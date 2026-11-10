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

// ── 收藏地点收集箱（task-social-favorites-flow-eval：collect-first 底座） ──
// 与「收藏行程」分离：收集箱装的是导入解析出的候选地点（还没进行程），
// 行程确定后再聚合/汇入。批量收藏幂等（同名跳过），单批上限 50（后端 422 防超量）。
export const listFavoriteSpots = (params = {}) =>
  http.get('/trips/favorite-spots', { params }).then((r) => r.data)

export const collectFavoriteSpots = (spots) =>
  http.post('/trips/favorite-spots/batch', { spots }).then((r) => r.data)

export const removeFavoriteSpot = (spotId) =>
  http.delete(`/trips/favorite-spots/${spotId}`).then((r) => r.data)

// ── 收藏地点 → 一键成路线（第二段聚合：收集箱 → 新草稿行程） ──
// 勾选收集箱地点 + 行程基础信息 → 生成新行程（确定性分天，每天 ≤ 5 站）。
// 返回 { trip, report: { placed, overflow, hotel_overflow, skipped } }。
export const createFavoriteSpotRoute = (payload) =>
  http.post('/trips/favorite-spots/route', payload).then((r) => r.data)