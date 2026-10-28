import http from '../http'

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