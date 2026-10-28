// WebSocket 订阅辅助（与 axios http 无关，独立封装）

const WS_BASE = () => {
  // WebSocket 地址同样支持构建期注入（移动端壳场景）
  const injected = import.meta.env.VITE_WS_BASE_URL
  if (injected) return injected
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws`
}

/** 创建带 JWT token 的 WS（token 为空时也建立连接，服务端按需鉴权）。 */
function wsWithAuth(path) {
  const token = localStorage.getItem('trip_planner_token') || ''
  return new WebSocket(`${WS_BASE()}${path}?token=${encodeURIComponent(token)}`)
}

/** 通用 WS 订阅骨架：解析 JSON 消息 → onEvent → onClose/onError 收敛。 */
function subscribe(ws, { onEvent, onClose } = {}) {
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

/**
 * 订阅规划任务实时事件流。
 * - onEvent(msg): 收到任一条 WS 消息（phase / artifact / trace / status）
 * - onStatus(msg): 收到终态消息（status 快照，含 plan / trip_id）
 * - onClose(): 连接关闭（调用方应切换轮询兜底）
 * 返回一个 close() 函数。
 */
export function subscribePlanTask(taskId, { onEvent, onStatus, onClose }) {
  const ws = wsWithAuth(`/planner/tasks/${taskId}`)
  return subscribe(ws, {
    onEvent: (msg) => {
      if (msg.type === 'status' || msg.type === 'state') {
        onStatus?.(msg)
      } else {
        onEvent?.(msg)
      }
    },
    onClose,
  })
}

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
  return subscribe(ws, { onEvent, onClose })
}

/** 订阅对话实时事件（WS）：assistant_delta / tool_start / tool_end / assistant_done。返回 close()。 */
export function subscribeChatSession(sessionId, { onEvent, onClose } = {}) {
  const ws = wsWithAuth(`/chat/${sessionId}`)
  return subscribe(ws, { onEvent, onClose })
}