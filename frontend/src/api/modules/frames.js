import http from '../http'

// ── 旅拍相框市场（frame-marketplace） ──
// 模板目录（免登录可看，付费模板带 locked 标注）
export const getFrameCatalog = () => http.get('/frames/catalog').then((r) => r.data)
// 我的已解锁包列表
export const getFrameEntitlements = () => http.get('/frames/entitlements').then((r) => r.data)
// 兑换码换权益（幂等；404/409/410 语义由 http 拦截器透传）
export const redeemFrameCode = (code) => http.post('/frames/redeem', { code }).then((r) => r.data)
// 单日打卡卡数据投影（owner）
export const getFrameDayData = (tripId, dayId) =>
  http.get(`/trips/${tripId}/frames/${dayId}/data`).then((r) => r.data)
// 整程总结图数据投影（owner）
export const getFrameSummaryData = (tripId) =>
  http.get(`/trips/${tripId}/frames/summary/data`).then((r) => r.data)
// AI 配文生成（owner；无自动发布副作用）
export const generateFrameCopy = (tripId, dayId, { channel = 'xhs', provider = 'auto' } = {}) =>
  http.post(`/trips/${tripId}/frames/${dayId}/copy`, { channel, provider }).then((r) => r.data)
