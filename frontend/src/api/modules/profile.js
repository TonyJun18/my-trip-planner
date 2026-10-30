import http from '../http'

// ── 旅行记忆偏好条目（task-floattrip-borrow Story 2）────────────
// 可查看/编辑/删除的长期偏好；删除（忘记）后规划上下文不再注入。
export const listPreferences = () => http.get('/profile/preferences').then((r) => r.data)
export const addPreference = (data) => http.post('/profile/preferences', data).then((r) => r.data)
export const updatePreference = (itemId, data) => http.put(`/profile/preferences/${itemId}`, data).then((r) => r.data)
export const deletePreference = (itemId) => http.delete(`/profile/preferences/${itemId}`).then((r) => r.data)