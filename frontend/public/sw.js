/* my-trip-planner Service Worker — PWA 离线支持（task-pwa-offline / task-pwa-cache-deep）
 *
 * 缓存策略（按可验证性排序）：
 * - 导航请求（HTML）：network-first → 回退 /index.html → 最后回退 /offline.html
 * - 静态资源（/assets/、/icon.svg、/manifest.webmanifest）：cache-first
 * - 行程 API GET（白名单：列表/详情/预算/方案/分享读取）：network-first，成功写缓存，失败回退 stale 缓存
 * - 其他请求（写操作、非白名单）：仅走网络，不缓存
 *
 * 注意：写操作（POST/PATCH/PUT/DELETE）一律不拦截，避免离线时产生「成功」假象。
 * 更新协议：install 时若已有旧 SW 激活则标记升级；activate 后向所有 window clients
 * 广播 { type: 'SW_UPDATED' }，页面据此提示「新版本已就绪」引导刷新。
 */
const VERSION = 'v2'
const SHELL_CACHE = `shell-${VERSION}`
const API_CACHE = `api-${VERSION}`

const SHELL_URLS = [
  '/',
  '/index.html',
  '/offline.html',
  '/manifest.webmanifest',
  '/icon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/apple-touch-icon.png',
]

// 允许离线回退的行程 API GET 白名单（Trip.id 为 UUID 字符串，token 为 64 位字符串）：
//   /api/v1/trips                      行程列表（登录态首页，静默缓存当前页）
//   /api/v1/trips/{id}                 行程详情
//   /api/v1/trips/{id}/budget          预算
//   /api/v1/trips/{id}/plan            规划方案
//   /api/v1/trips/{id}/plan-b          备选方案
//   /api/v1/trips/share/{token}        分享只读行程
//   /api/v1/trips/edit/{token}         受邀编辑行程（读取）
// 排除 /api/v1/trips/favorites 列表、/share/{token}/comments、/share/{token}/votes（协作接口语义离线无意义，维持走网络）
const API_WHITELIST =
  /^\/api\/v1\/trips(\/(?!favorites)([^/]+(\/(budget|plan|plan-b))?|(share|edit)\/[^/]+))?$/

// 本次 install 是否有旧版 SW 正在激活（用于区分「首装」与「升级」）
let isUpgrade = false

self.addEventListener('install', (event) => {
  // 升级检测：已有激活的旧 SW → 本次为升级，activate 后通知页面
  isUpgrade = self.registration.active !== null
  // allSettled：个别资源失败不阻塞 SW 激活（如未部署的路径）
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => Promise.allSettled(SHELL_URLS.map((u) => cache.add(u))))
      .then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => {
        const keep = new Set([SHELL_CACHE, API_CACHE])
        return Promise.all(keys.filter((k) => !keep.has(k)).map((k) => caches.delete(k)))
      })
      .then(() => self.clients.claim())
      .then(() => {
        // 仅升级时通知页面（首装无需刷新提示）
        if (isUpgrade) {
          return self.clients
            .matchAll({ type: 'window', includeUncontrolled: true })
            .then((clients) =>
              clients.forEach((client) =>
                client.postMessage({ type: 'SW_UPDATED', version: VERSION })
              )
            )
        }
      })
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return // 写操作一律走网络
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return

  // 导航请求：network-first，html 缓存到 shell（供离线打开）
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone()
          caches.open(SHELL_CACHE).then((c) => c.put('/index.html', copy))
          return res
        })
        .catch(() =>
          caches.match('/index.html').then((r) => r || caches.match('/offline.html'))
        )
    )
    return
  }

  // 行程 API GET：network-first + stale 回退
  if (url.pathname.match(API_WHITELIST)) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone()
            caches.open(API_CACHE).then((c) => c.put(req, copy))
          }
          return res
        })
        .catch(() => caches.match(req).then((r) => r || Response.error()))
    )
    return
  }

  // 静态资源：cache-first（vite 产物带 hash，天然不可变）
  if (
    url.pathname.startsWith('/assets/') ||
    url.pathname === '/manifest.webmanifest' ||
    url.pathname === '/icon.svg' ||
    url.pathname === '/apple-touch-icon.png' ||
    url.pathname.startsWith('/icons/')
  ) {
    event.respondWith(
      caches.match(req).then(
        (cached) =>
          cached ||
          fetch(req).then((res) => {
            const copy = res.clone()
            caches.open(SHELL_CACHE).then((c) => c.put(req, copy))
            return res
          })
      )
    )
  }
})