import { defineStore } from 'pinia'
import * as api from '@/api'

const TOKEN_KEY = 'trip_planner_token'
const USER_KEY = 'trip_planner_user'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
    displayName: (state) => state.user?.display_name || state.user?.email || state.user?.phone || '未登录',
  },
  actions: {
    async login(account, password) {
      const data = await api.login(account, password)
      this.setSession(data)
    },
    async register(payload) {
      const data = await api.register(payload)
      this.setSession(data)
    },
    setSession({ access_token, user }) {
      this.token = access_token
      this.user = user
      localStorage.setItem(TOKEN_KEY, access_token)
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    },
    async fetchMe() {
      if (!this.token) return null
      try {
        this.user = await api.getMe()
        localStorage.setItem(USER_KEY, JSON.stringify(this.user))
        return this.user
      } catch {
        this.logout()
        return null
      }
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})