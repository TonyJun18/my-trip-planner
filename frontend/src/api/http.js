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
  // 后端文案语种跟随「App 语言」（vue-i18n），不交给浏览器 Accept-Language：
  // 浏览器头来自系统语言——系统英文 + App 选中文的用户，后端 Plan B 等
  // 服务端文案会回英文（金额还按语种切换成 $），与界面语言不一致。
  const appLocale = i18n.global.locale?.value
  if (appLocale) {
    config.headers['Accept-Language'] = appLocale
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
    // config.silent：调用方自己兜底（如额度快照这类「有则显示、无则静默」的旁路请求）
    if (msg !== 'canceled' && err.config?.silent !== true) ElMessage.error(msg)
    return Promise.reject(err)
  },
)

export default http