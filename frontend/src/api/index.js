import axios from 'axios'
import { ElMessage } from 'element-plus'
import i18n from '@/i18n'

// API 地址支持构建期注入（Capacitor/移动端打包时 WebView 无法用相对路径 /api/v1）：
// - VITE_API_BASE_URL：完整后端地址（如 https://api.example.com/api/v1）
// - 未设置时回退 `/api/v1`（Web 端 Nginx 反代 / vite dev proxy）
const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const http = axios.create({
  baseURL: API_BASE,
  timeout: 300000, // 规划任务轮询超时（轮询本身很快）
})

// 自动附带 Bearer token（从 localStorage 读取）
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('trip_planner_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    // 401: 登录失效 → 清理本地会话并跳转登录页
    if (err.response?.status === 401 && !err.config?.url?.includes('/auth/login')) {
      localStorage.removeItem('trip_planner_token')
      localStorage.removeItem('trip_planner_user')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    const msg = err.response?.data?.error?.message || i18n.global.t('common.requestFailed')
    if (msg !== 'canceled') ElMessage.error(msg)
    return Promise.reject(err)
  },
)

// ── auth ──────────────────────────────────────────────────
export const register = (data) => http.post('/auth/register', data).then((r) => r.data)
export const login = (account, password) => http.post('/auth/login', { account, password }).then((r) => r.data)
export const googleLogin = (idToken) => http.post('/auth/google', { id_token: idToken }).then((r) => r.data)
export const getMe = () => http.get('/auth/me').then((r) => r.data)

// ── health ────────────────────────────────────────────────
export const health = () => http.get('/health').then((r) => r.data)

// ── trips ─────────────────────────────────────────────────
export const listTrips = (params = {}) => http.get('/trips', { params }).then((r) => r.data)
export const getTrip = (id) => http.get(`/trips/${id}`).then((r) => r.data)
export const createTrip = (data) => http.post('/trips', data).then((r) => r.data)
export const updateTrip = (id, data) => http.patch(`/trips/${id}`, data).then((r) => r.data)
export const deleteTrip = (id) => http.delete(`/trips/${id}`)

// ── days / stops ──────────────────────────────────────────
export const addDay = (tripId, data) => http.post(`/trips/${tripId}/days`, data).then((r) => r.data)
export const generateDays = (tripId, start, end) =>
  http.post(`/trips/${tripId}/days/generate`, null, { params: { start, end } }).then((r) => r.data)
export const addStop = (dayId, data) => http.post(`/trips/days/${dayId}/stops`, data).then((r) => r.data)
export const updateStop = (dayId, stopId, data) => http.patch(`/trips/days/${dayId}/stops/${stopId}`, data).then((r) => r.data)
export const reorderStops = (dayId, order) => http.put(`/trips/days/${dayId}/stops/order`, { order }).then((r) => r.data)
export const deleteDay = (dayId) => http.delete(`/trips/days/${dayId}`)
export const deleteStop = (dayId, stopId) => http.delete(`/trips/days/${dayId}/stops/${stopId}`)

// ── budget / planner（异步任务） ──────────────────────────
export const getBudget = (tripId) => http.get(`/trips/${tripId}/budget`).then((r) => r.data)
export const getTripPlan = (tripId) => http.get(`/trips/${tripId}/plan`).then((r) => r.data)
export const planTrip = (data) => http.post('/planner/plan', data).then((r) => r.data)
export const getPlanTask = (taskId) => http.get(`/planner/tasks/${taskId}`).then((r) => r.data)

// ── 小红书笔记（方案 A：内容工厂） ─────────────────────────
export const generateXhsNote = (tripId) => http.post(`/trips/${tripId}/xhs-note`, { provider: 'auto' }).then((r) => r.data)

// ── 行中「今日视图」（task-live-today-view：MonkeyTravel live trip 差异化） ──
export const getLiveSnapshot = (tripId) => http.get(`/trips/${tripId}/live`).then((r) => r.data)
export const checkLiveStop = (tripId, stopId, checked = true) =>
  http.post(`/trips/${tripId}/live/stops/${stopId}/check`, { checked }).then((r) => r.data)
export const skipLiveStop = (tripId, stopId) =>
  http.post(`/trips/${tripId}/live/stops/${stopId}/skip`, null).then((r) => r.data)
export const delayLiveTrip = (tripId) =>
  http.post(`/trips/${tripId}/live/delay`, null).then((r) => r.data)

// ── 规划任务实时推送（WebSocket；断线由轮询兜底） ─────────
const WS_BASE = () => {
  // WebSocket 地址同样支持构建期注入（移动端壳场景）
  const injected = import.meta.env.VITE_WS_BASE_URL
  if (injected) return injected
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws`
}

/**
 * 订阅规划任务实时事件流。
 * - onEvent(msg): 收到任一条 WS 消息（phase / artifact / trace / status）
 * - onStatus(msg): 收到终态消息（status 快照，含 plan / trip_id）
 * - onClose(): 连接关闭（调用方应切换轮询兜底）
 * 返回一个 close() 函数。
 */
export function subscribePlanTask(taskId, { onEvent, onStatus, onClose }) {
  const token = localStorage.getItem('trip_planner_token') || ''
  const ws = new WebSocket(`${WS_BASE()}/planner/tasks/${taskId}?token=${encodeURIComponent(token)}`)
  ws.onmessage = (evt) => {
    let msg
    try {
      msg = JSON.parse(evt.data)
    } catch {
      return
    }
    if (msg.type === 'status' || msg.type === 'state') {
      onStatus?.(msg)
    } else {
      onEvent?.(msg)
    }
  }
  ws.onclose = () => onClose?.()
  ws.onerror = () => {
    try { ws.close() } catch { /* noop */ }
  }
  return () => {
    try { ws.close() } catch { /* noop */ }
  }
}

// ── 对话式修订行程（方案 B） ──────────────────────────────
export const reviseTrip = (tripId, data) => http.post(`/trips/${tripId}/revise`, data).then((r) => r.data)

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

/**
 * 订阅行程协作/行中 feed（实时同步今日卡片）。
 * - 登录态：传 tripId（owner 详情页，JWT 鉴权）
 * - 免登录：传 { token, edit }（分享/受邀编辑页）
 * 返回 close()；断线由调用方轮询兜底。
 */
export function subscribeTripCollab(tripId, { token, edit = false, onEvent, onClose } = {}) {
  const params = new URLSearchParams()
  if (token) {
    params.set('token', token)
    if (edit) params.set('edit', '1')
  } else {
    const jwt = localStorage.getItem('trip_planner_token') || ''
    params.set('token', jwt)
  }
  const ws = new WebSocket(`${WS_BASE()}/trips/${tripId}/collab?${params.toString()}`)
  ws.onmessage = (evt) => {
    let msg
    try {
      msg = JSON.parse(evt.data)
    } catch {
      return
    }
    onEvent?.(msg)
  }
  ws.onclose = () => onClose?.()
  ws.onerror = () => {
    try { ws.close() } catch { /* noop */ }
  }
  return () => {
    try { ws.close() } catch { /* noop */ }
  }
}

// ── 地图拖拽修订（task-map-drag-edit）：拖动 marker 改坐标 → 最小 diff 原子应用 ──
export const mapEditTrip = (tripId, data) => http.post(`/trips/${tripId}/map-edit`, data).then((r) => r.data)

// ── 行程分享（只读链接） ──────────────────────────────────
export const createShare = (tripId) => http.post(`/trips/${tripId}/share`).then((r) => r.data)
export const getSharedTrip = (token) => http.get(`/trips/share/${token}`).then((r) => r.data)

// ── 分享令牌生命周期（TTL / 吊销 / 审计） ─────────────────
export const getShareLifecycle = (tripId) => http.get(`/trips/${tripId}/share/lifecycle`).then((r) => r.data)
export const revokeShareToken = (tripId, kind) => http.post(`/trips/${tripId}/share/revoke`, { kind }).then((r) => r.data)
export const setShareTokenTtl = (tripId, kind, days) => http.post(`/trips/${tripId}/share/ttl`, { kind, days }).then((r) => r.data)

// ── 收藏灵感夹（登录用户收藏他人分享的行程） ───────────────
export const listFavorites = (params = {}) => http.get('/trips/favorites', { params }).then((r) => r.data)
export const addFavorite = (tripId) => http.post(`/trips/favorites/${tripId}`).then((r) => r.data)
export const removeFavorite = (tripId) => http.delete(`/trips/favorites/${tripId}`).then((r) => r.data)

// ── 行程备选方案（Plan B：确定性规则生成，无 LLM） ─────────
export const getPlanB = (tripId) => http.get(`/trips/${tripId}/plan-b`).then((r) => r.data)

// ── 受邀编辑（edit_token：owner 开放/收回编辑权，受邀者免登录受限编辑） ──
export const createShareEdit = (tripId) => http.post(`/trips/${tripId}/share/edit`).then((r) => r.data)
export const revokeShareEdit = (tripId) => http.delete(`/trips/${tripId}/share/edit`).then((r) => r.data)
export const getEditableTrip = (token) => http.get(`/trips/edit/${token}`).then((r) => r.data)
export const updateInvitedStop = (token, stopId, data) =>
  http.patch(`/trips/edit/${token}/stops/${stopId}`, data).then((r) => r.data)
export const reorderInvitedStops = (token, dayId, order) =>
  http.put(`/trips/edit/${token}/days/${dayId}/stops/order`, { order }).then((r) => r.data)
// 受邀编辑地图拖拽（task-map-drag-edit：持 edit_token 免登录移动站点坐标）
export const mapEditInvitedTrip = (token, data) =>
  http.post(`/trips/edit/${token}/map-edit`, data).then((r) => r.data)

// ── 分享页协作（评论 / 站点投票，免登录，凭 share_token） ──
export const getSharedTripComments = (token) => http.get(`/trips/share/${token}/comments`).then((r) => r.data)
export const postSharedTripComment = (token, data) => http.post(`/trips/share/${token}/comments`, data).then((r) => r.data)
export const getSharedTripVotes = (token) => http.get(`/trips/share/${token}/votes`).then((r) => r.data)
export const castSharedTripVote = (token, stopId, value) =>
  http.post(`/trips/share/${token}/votes/${stopId}`, { value }).then((r) => r.data)

// ── 内容导入（五通道：笔记 / 截图 / 邮件 / 链接 / 社交粘贴；外部内容按敌意输入处理，纯规则解析零凭证） ──
// 后端契约：POST /trips/note/import {text} / screenshot/import <图片原始字节> /
// email/import {text} / link/import {url} / social/import {text} → 解析为站点候选，勾选后经 addStop 并入行程
export const importNote = (data) => http.post('/trips/note/import', data).then((r) => r.data)
export const importScreenshot = (file) =>
  http
    .post('/trips/screenshot/import', file, {
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      maxBodyLength: 20 * 1024 * 1024,
    })
    .then((r) => r.data)
export const importEmail = (data) => http.post('/trips/email/import', data).then((r) => r.data)
export const importLink = (data) => http.post('/trips/link/import', data).then((r) => r.data)
// 社交分享（task-social-collection-eval）：粘贴 caption+链接 → 地点候选；URL 只识别平台、绝不抓取
export const importSocial = (data) => http.post('/trips/social/import', data).then((r) => r.data)

// ── 灵感优先目的地推荐（task-inspiration-mode：还没想好去哪 → 按兴趣/预算/季节推荐） ──
// 后端契约：GET /trips/inspiration?interests=food,nature&budget_tier=comfort&season=&limit=5
// → { items: [{name/country/tags/best_season/budget_tier/est_daily_budget/suggested_days/
//              reason/play/match_score/matched_tags/season_note/basis}], counts, note }
export const getInspiration = (params = {}) => http.get('/trips/inspiration', { params }).then((r) => r.data)

// ── 灵感画廊 + 城市模板（task-gallery-featured / city-templates） ──
// GET /trips/gallery（公开精选） / GET /trips/gallery/templates（城市模板卡）
// POST /trips/gallery/{id}/clone（复制到我的账号） / POST /trips/{id}/gallery/publish
export const getGallery = (params = {}) => http.get('/trips/gallery', { params }).then((r) => r.data)
export const getCityTemplates = (params = {}) =>
  http.get('/trips/gallery/templates', { params }).then((r) => r.data)
export const cloneGalleryTrip = (sourceId) =>
  http.post(`/trips/gallery/${sourceId}/clone`).then((r) => r.data)
export const publishToGallery = (tripId, data = {}) =>
  http.post(`/trips/${tripId}/gallery/publish`, data).then((r) => r.data)
export const unpublishFromGallery = (tripId) =>
  http.delete(`/trips/${tripId}/gallery/publish`).then((r) => r.data)

// ── 行程事件流（task-trip-event-notify：主动通知最小版） ─────────
// 后端契约：GET /trips/{id}/events（owner）/ GET /trips/share/{token}/events（免登录只读）
// → { items: [{id, trip_id, event_type, payload, created_at}], total }
export const getTripEvents = (tripId, params = {}) =>
  http.get(`/trips/${tripId}/events`, { params }).then((r) => r.data)
export const getSharedTripEvents = (token, params = {}) =>
  http.get(`/trips/share/${token}/events`, { params }).then((r) => r.data)

// ── 行程导出（task-export-offline：输出自由 / 数据主权） ──────────
// 后端契约：GET /trips/{id}/export（owner）→ 完整 JSON 快照（trip+days+budget+plan 元信息）
// GET /trips/share/{token}/export（免登录只读，同 share 信任语义）
export const exportTripJson = (tripId) =>
  http.get(`/trips/${tripId}/export`, { responseType: 'blob' }).then((r) => r.data)
export const exportSharedTripJson = (token) =>
  http.get(`/trips/share/${token}/export`, { responseType: 'blob' }).then((r) => r.data)

// ── 对话式行程助手（B 期：pi-agent-core runtime 驱动的多轮工具对话） ──────────
// 后端契约：POST /chat/sessions（建会话）/ GET /chat/sessions（我的会话）
// GET /chat/sessions/{id}（详情）/ DELETE /chat/sessions/{id}
// POST /chat/sessions/{id}/messages {message, provider} → assistant 回复
// WS /ws/chat/{session_id} → assistant_delta / tool_start / tool_end / assistant_done
export const createChatSession = (data = {}) => http.post('/chat/sessions', data).then((r) => r.data)
export const listChatSessions = (params = {}) => http.get('/chat/sessions', { params }).then((r) => r.data)
export const getChatSession = (sessionId) => http.get(`/chat/sessions/${sessionId}`).then((r) => r.data)
export const deleteChatSession = (sessionId) => http.delete(`/chat/sessions/${sessionId}`)
export const listChatMessages = (sessionId, params = {}) =>
  http.get(`/chat/sessions/${sessionId}/messages`, { params }).then((r) => r.data)
export const sendChatMessage = (sessionId, message, provider = 'auto') =>
  http.post(`/chat/sessions/${sessionId}/messages`, { message, provider }).then((r) => r.data)

/** 订阅对话实时事件（WS）：assistant_delta / tool_start / tool_end / assistant_done。返回 close()。 */
export function subscribeChatSession(sessionId, { onEvent, onClose } = {}) {
  const token = localStorage.getItem('trip_planner_token') || ''
  const ws = new WebSocket(`${WS_BASE()}/chat/${sessionId}?token=${encodeURIComponent(token)}`)
  ws.onmessage = (evt) => {
    let msg
    try {
      msg = JSON.parse(evt.data)
    } catch {
      return
    }
    onEvent?.(msg)
  }
  ws.onclose = () => onClose?.()
  ws.onerror = () => {
    try { ws.close() } catch { /* noop */ }
  }
  return () => {
    try { ws.close() } catch { /* noop */ }
  }
}

export default http