/**
 * 分享 / 受邀编辑的访问密码免验凭证（task-share-gate-eval 前端接线）。
 *
 * 后端契约：
 * - 访客输密码 → POST /trips/{share|edit}/{token}/verify → { gate_token }（HMAC，12h）
 * - 后续所有免登录读取（行程 / 评论 / 投票 / 行中 / 护照 / 导出 / 地图编辑）带
 *   `X-Share-Gate: <gate_token>` 即免重复输密码；WS 用 `?gate=`。
 *
 * 这里做两件事：
 * 1. 按令牌（token 本身唯一，share/edit 各自一把）本地存取 gate_token；
 * 2. 给 axios 请求自动附加 X-Share-Gate —— 只匹配 `/trips/share/{token}` 与
 *    `/trips/edit/{token}` 前缀，verify 端点自身不带旧凭证（避免脏凭证互相干扰）。
 *
 * 安全边界：gate_token 是短期免验凭证、不含密码本身；密码永不出现在本地存储。
 */
const PREFIX = 'share_gate:'

// /trips/share/{token} 或 /trips/edit/{token}（后接 /comments 等子路径同样命中）
const SHARE_PATH_RE = /\/trips\/(?:share|edit)\/([^/?#]+)/

function storageKey(token) {
  return `${PREFIX}${token}`
}

/** 读取某令牌的免验凭证（没有则空串）。 */
export function getGateToken(token) {
  if (!token) return ''
  try {
    return localStorage.getItem(storageKey(token)) || ''
  } catch {
    return ''
  }
}

/** 保存免验凭证（验证通过后调用）。 */
export function setGateToken(token, gateToken) {
  if (!token || !gateToken) return
  try {
    localStorage.setItem(storageKey(token), gateToken)
  } catch {
    // 存储不可用（隐私模式等）→ 仅本次请求内有效，下次仍需输密码
  }
}

/** 清除免验凭证（密码被改/被清除、或验证失败时）。 */
export function clearGateToken(token) {
  if (!token) return
  try {
    localStorage.removeItem(storageKey(token))
  } catch {
    // noop
  }
}

/**
 * 给分享/编辑请求自动附加 X-Share-Gate（axios 请求拦截器调用）。
 * - verify 端点跳过：它用一次性密码换凭证，不该带旧凭证
 * - 调用方已显式设置时不覆盖
 */
export function attachShareGate(config) {
  const url = config?.url || ''
  if (!url || url.includes('/verify')) return
  const match = url.match(SHARE_PATH_RE)
  if (!match) return
  const gate = getGateToken(match[1])
  if (!gate) return
  if (config.headers && !config.headers['X-Share-Gate']) {
    config.headers['X-Share-Gate'] = gate
  }
}
