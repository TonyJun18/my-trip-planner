import http from '../http'

// ── auth ──────────────────────────────────────────────────
export const register = (data) => http.post('/auth/register', data).then((r) => r.data)
export const login = (account, password) => http.post('/auth/login', { account, password }).then((r) => r.data)
export const googleLogin = (idToken) => http.post('/auth/google', { id_token: idToken }).then((r) => r.data)
export const getMe = () => http.get('/auth/me').then((r) => r.data)

// ── health ────────────────────────────────────────────────
export const health = () => http.get('/health').then((r) => r.data)