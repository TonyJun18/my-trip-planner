/**
 * 单日多点导航深链（task-day-map-deeplink，2026-11-14）
 *
 * 竞争证据：Dream Trip 把「单日导出 Google Maps」作为行中动作；我们此前只有
 * ICS 导出，日卡没有「一键导航」。
 *
 * 设计决策（纯函数、零凭证、零依赖）：
 * - Google Maps：origin=首站、destination=末站、waypoints=中间站，一次带出全天路线。
 *   最多 9 站（Google waypoints 上限），超限降级为「按顺序的逐站导航列表」。
 * - Apple Maps / 高德：单点导航（按顺序「下一站」逐站带跳）。
 * - 坐标体系差异（Google WGS84 vs 高德 GCJ-02）不做纠偏——国内默认高德、海外默认
 *   Google，文案注明「以地图实际路线为准」（坐标偏差通常 <500m，导航 app 会吸附道路）。
 * - 缺坐标站点跳过，避免死链。
 */

/** Google Maps waypoints 最多 9 个（origin + destination + waypoints ≤ 11 总量上限我们取 9） */
export const MAX_MAP_STOPS = 9

/** 单站深层链接（缺坐标返回 null） */
export function singleStopMapUrl(stop, provider = 'google') {
  const coord = stopCoord(stop)
  if (!coord) return null
  const q = `${coord.lat},${coord.lng}`
  const label = encodeURIComponent(stop.name || '')
  const providers = {
    google: `https://www.google.com/maps/search/?api=1&query=${q}${label ? '(' + label + ')' : ''}`,
    apple: `https://maps.apple.com/?ll=${q}${label ? '&q=' + label : ''}`,
    amap: `https://uri.amap.com/marker?position=${coord.lng},${coord.lat}${label ? '&name=' + label : ''}`,
  }
  return providers[provider] || null
}

/** 当日多站导航链接；超 9 站返回逐站列表 */
export function dayMapLinks(stops, provider = 'google') {
  const withCoord = (stops || []).filter((s) => stopCoord(s))
  if (withCoord.length === 0) return { url: null, list: [] }
  if (withCoord.length === 1) {
    return { url: singleStopMapUrl(withCoord[0], provider), list: [] }
  }
  if (withCoord.length <= MAX_MAP_STOPS) {
    return { url: multiStopMapUrl(withCoord, provider), list: [] }
  }
  // 超限 → 降级为按顺序的单点导航列表（保底可用）
  return { url: null, list: withCoord.map((s) => singleStopMapUrl(s, provider)).filter(Boolean) }
}

/** 多站驾驶/步行路线链接（仅 Google 支持 waypoints；Apple/高德返回首站单点） */
export function multiStopMapUrl(stops, provider = 'google') {
  const withCoord = (stops || []).filter((s) => stopCoord(s))
  if (withCoord.length === 0) return null
  const first = withCoord[0]
  const last = withCoord.length > 1 ? withCoord[withCoord.length - 1] : first
  const middle = withCoord.slice(1, -1)
  if (provider === 'google') {
    const params = new URLSearchParams()
    params.set('api', '1')
    params.set('origin', `${first.lat},${first.lng}`)
    params.set('destination', `${last.lat},${last.lng}`)
    if (middle.length) {
      params.set('waypoints', middle.map((s) => `${s.lat},${s.lng}`).join('|'))
    }
    return `https://www.google.com/maps/dir/?${params.toString()}`
  }
  // Apple / 高德：无 waypoints，给首站单点（用户按顺序导航下一站）
  return singleStopMapUrl(first, provider)
}

/** 提取站点坐标（lat/lng 数字，缺失或非法返回 null） */
export function stopCoord(stop) {
  if (!stop) return null
  const lat = Number(stop.lat)
  const lng = Number(stop.lng)
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || lat === 0 || lng === 0) return null
  return { lat, lng }
}