import http from '../http'

// ── 收藏灵感夹（登录用户收藏他人分享的行程） ───────────────
export const listFavorites = (params = {}) => http.get('/trips/favorites', { params }).then((r) => r.data)
export const addFavorite = (tripId) => http.post(`/trips/favorites/${tripId}`).then((r) => r.data)
export const removeFavorite = (tripId) => http.delete(`/trips/favorites/${tripId}`).then((r) => r.data)