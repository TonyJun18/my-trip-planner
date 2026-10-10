// PWA 离线辅助（task-pwa-offline / task-pwa-cache-deep）
// 提供「从 Cache API 读行程 API 响应」的能力 + Service Worker 注册与更新监听。

// 注意：必须与 public/sw.js 的 VERSION 常量保持同步（SW 升级时此处手动 bump）。
// sw.js: const VERSION = 'v2' → API_CACHE = `api-${VERSION}` = 'api-v2'
const API_CACHE_NAME = 'api-v2'

/**
 * 从 Service Worker 的 api 缓存中读取 GET 响应（path 为绝对路径，如 /api/v1/trips/xxx）。
 * 返回解析后的 JSON；无缓存或解析失败返回 null（调用方自行降级）。
 * ignoreSearch: true —— 列表页带分页 query 的缓存也能被无 query 的 path 命中。
 */
export async function readCachedJson(path) {
  try {
    if (!('caches' in window)) return null
    const cache = await caches.open(API_CACHE_NAME)
    const res = await cache.match(path, { ignoreSearch: true })
    if (!res) return null
    const text = await res.text()
    if (!text) return null
    return JSON.parse(text)
  } catch {
    return null
  }
}

/** 当前是否在线（navigator.onLine 仅是提示，离线时 SW 会拦截；此处用于 UI 提示） */
export const isOnline = () => navigator.onLine !== false

/**
 * 注册 Service Worker 的更新监听（注册动作仍在 main.js 完成）：
 * 当「新版本 SW 已就绪」时回调 onUpdate()，触发时机：
 *  1. updatefound：新 SW 下载完成且已 installed（旧 SW 仍控制页面，最可靠的提示点）
 *  2. SW 广播 SW_UPDATED：新 SW activate 后主动通知（skipWaiting + clients.claim 后）
 *  3. controllerchange：新 SW 已接管页面
 * 页面收到回调后应展示「新版本已就绪 → 刷新」提示；回调可能重复触发，由调用方去重。
 * 返回 unlisten() 用于组件卸载时解绑监听。
 */
export function registerSW(onUpdate) {
  if (!('serviceWorker' in navigator)) return () => {}
  let unlisten = () => {}

  const cleanup = navigator.serviceWorker.ready
    .then((reg) => {
      let newWorker = null
      const onUpdateFound = () => {
        // 等待新 SW 完成 install（installed 状态）后再提示，避免反复 updatefound
        newWorker = reg.installing
        if (!newWorker) return
        newWorker.addEventListener('statechange', () => {
          if (newWorker && newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            onUpdate?.()
          }
        })
      }
      reg.addEventListener('updatefound', onUpdateFound)

      const onControllerChange = () => onUpdate?.()
      navigator.serviceWorker.addEventListener('controllerchange', onControllerChange)

      // SW activate 后的主动广播（守护：updatefound 因时序错过时的兜底）
      const onMessage = (evt) => {
        if (evt.data && evt.data.type === 'SW_UPDATED') onUpdate?.()
      }
      navigator.serviceWorker.addEventListener('message', onMessage)

      unlisten = () => {
        reg.removeEventListener('updatefound', onUpdateFound)
        navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange)
        navigator.serviceWorker.removeEventListener('message', onMessage)
      }
    })
    .catch(() => {
      // SW 注册失败（如非 https/localhost）：静默，不阻断应用
    })

  return () => {
    cleanup?.then(() => unlisten?.())
  }
}