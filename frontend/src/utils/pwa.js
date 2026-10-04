// PWA 离线辅助（task-pwa-offline + task-pwa-cache-deep）
// 提供「从 Cache API 读行程 API 响应」的能力，供视图在网络失败时降级展示缓存内容。

/**
 * 从 Service Worker 的 api 缓存中读取 GET 响应（path 为绝对路径，如 /api/v1/trips/xxx）。
 * 遍历所有 api-* 版本缓存（SW activate 会清理旧版，但读取时兼容多版本更稳）。
 * 返回解析后的 JSON；无缓存或解析失败返回 null（调用方自行降级）。
 */
export async function readCachedJson(path) {
  try {
    if (!('caches' in window)) return null
    const keys = await caches.keys()
    const apiCaches = keys.filter((k) => k.startsWith('api-'))
    for (const name of apiCaches) {
      const cache = await caches.open(name)
      const res = await cache.match(path, { ignoreSearch: true })
      if (!res) continue
      const text = await res.text()
      if (!text) return null
      try {
        return JSON.parse(text)
      } catch {
        continue // 坏缓存尝试下一个版本
      }
    }
    return null
  } catch {
    return null
  }
}

/** 当前是否在线（navigator.onLine 仅是提示，离线时 SW 会拦截；此处用于 UI 提示） */
export const isOnline = () => navigator.onLine !== false