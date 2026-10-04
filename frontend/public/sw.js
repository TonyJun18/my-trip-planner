/* my-trip-planner Service Worker — PWA 离线支持（task-pwa-offline + task-pwa-cache-deep）
 *
 * 缓存策略（按可验证性排序）：
 * - 导航请求（HTML）：network-first → 回退 /index.html → 最后回退 /offline.html
 * - 静态资源（/assets/、/icon.svg、/manifest.webmanifest）：cache-first
 * - 行程 API GET（白名单：列表/详情/预算/方案/分享读取）：network-first，成功写缓存，失败回退 stale 缓存
 * - 其他请求（写操作、非白名单）：仅走网络，不缓存
 *
 * 注意：
 * - 写操作（POST/PATCH/PUT/DELETE）一律不拦截，避免离线时产生「成功」假象。
 * - 列表 GET /api/v1/trips 静默缓存（key 归一化为 pathname，忽略分页 query）：
 *   离线时列表页降级展示最近一次成功拉取的缓存列表（task-pwa-cache-deep）。
 */
const VERSION = 'v2'
const SHELL_CACHE = `shell-${VERSION}`
const API_CACHE = `api-${VERSION}`

const SHELL_URLS = ['/', '/index.html', '/offline.html', '/manifest.webmanifest', '/icon.svg']

// 允许离线回退的行程 API GET 白名单（Trip.id 为 UUID 字符串，token 为 64 位字符串）：
//   /api/v1/trips                    行程列表（静默缓存，pathname 归一化）
//   /api/v1/trips/{id}                行程详情
//   /api/v1/trips/{id}/budget         预算
//   /api/v1/trips/{id}/plan           规划方案
//   /api/v1/trips/{id}/plan-b         备选方案
//   /api/v1/trips/share/{token}       分享只读行程
//   /api/v1/trips/edit/{token}        受邀编辑行程（读取）
// 排除 /api/v1/trips/favorites 列表（收藏列表语义离线无意义，维持走网络）
const API_WHITELIST =
  /^\/api\/v1\/trips\/(?!favorites)([^/]+(\/(budget|plan|plan-b))?|(share|edit)\/[^/]+)$/

self.addEventListener('install', (event) => {
  // allSettled：个别资源失败不阻塞 SW 激活（如未部署的路径）
  // 注意：这里不调用 skipWaiting()——首次安装（无旧版本）时 install 完成即自动 activate；
  // 更新场景（已有旧版本控制页面）新 SW 进入 waiting，由前端弹窗确认后
  // 通过 SKIP_WAITING 消息接管（task-pwa-cache-deep 更新提示）。
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => Promise.allSettled(SHELL_URLS.map((u) => cache.add(u))))
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
  )
})

// 前端新版本就绪提示：收到 SKIP_WAITING 后立即接管（配合 updatefound 引导刷新）
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting()
  }
})

// 提醒：生产部署需为 /sw.js 配置 Cache-Control: no-cache（或 updateViaCache: 'none'），
// 否则浏览器可能用 HTTP 缓存里的旧 SW 脚本做更新检查，导致新版本永远无法被发现。

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

  // 行程列表 GET：network-first + stale 回退；缓存 key 归一化为 pathname（忽略分页 query），
  // 保证离线时无论当前页码都能取到最近一次成功列表（task-pwa-cache-deep）
  if (url.pathname === '/api/v1/trips') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone()
            caches.open(API_CACHE).then((c) => c.put(new Request(url.pathname), copy))
          }
          return res
        })
        .catch(() =>
          caches.match(new Request(url.pathname)).then((r) => r || Response.error())
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
    url.pathname === '/icon.svg'
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