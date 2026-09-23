import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/api/v1',
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
    const msg = err.response?.data?.error?.message || err.message || '请求失败'
    if (msg !== 'canceled') ElMessage.error(msg)
    return Promise.reject(err)
  },
)

// ── auth ──────────────────────────────────────────────────
export const register = (data) => http.post('/auth/register', data).then((r) => r.data)
export const login = (account, password) => http.post('/auth/login', { account, password }).then((r) => r.data)
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

// ── 对话式修订行程（方案 B） ──────────────────────────────
export const reviseTrip = (tripId, data) => http.post(`/trips/${tripId}/revise`, data).then((r) => r.data)

// ── 行程分享（只读链接） ──────────────────────────────────
export const createShare = (tripId) => http.post(`/trips/${tripId}/share`).then((r) => r.data)
export const getSharedTrip = (token) => http.get(`/trips/share/${token}`).then((r) => r.data)

// ── 分享页协作（评论 / 站点投票，免登录，凭 share_token） ──
export const getSharedTripComments = (token) => http.get(`/trips/share/${token}/comments`).then((r) => r.data)
export const postSharedTripComment = (token, data) => http.post(`/trips/share/${token}/comments`, data).then((r) => r.data)
export const getSharedTripVotes = (token) => http.get(`/trips/share/${token}/votes`).then((r) => r.data)
export const castSharedTripVote = (token, stopId, value) =>
  http.post(`/trips/share/${token}/votes/${stopId}`, { value }).then((r) => r.data)

export default http