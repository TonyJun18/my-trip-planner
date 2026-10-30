/**
 * 最小 Feature Flag 模块（前端本地，无后端依赖）。
 *
 * 用途：信息架构类改版（如详情页 IA v2）需要可回滚开关，灰度期靠它切对照组。
 *
 * 解析优先级：
 *   1. URL 覆盖 —— `?flag=tripDetail.ia.v2=off`（可逗号分隔多项），便于验收/回滚时临时关闭
 *   2. localStorage 持久化 —— `setFlag(key, on)` 写入
 *   3. DEFAULTS 默认值
 *
 * 约定：
 * - 所有异常静默降级到默认值（隐私模式 / 禁用 localStorage 不应阻断页面）
 * - 关闭值识别：off / 0 / false / no（大小写不敏感）
 */

const DEFAULTS = {
  // 详情页信息架构 v2：按时机收纳次级工具（tabs）+ 全部工具开关
  // 关掉 = 恢复「三段式工具箱全部平铺」旧结构，用于 G1 工具流失对照组
  'tripDetail.ia.v2': true,
}

const STORE_PREFIX = 'mtp.flag.'
const OFF_VALUES = ['off', '0', 'false', 'no']

function parseBool(raw) {
  return !OFF_VALUES.includes(String(raw ?? 'on').trim().toLowerCase())
}

/** 读取 URL 上的 ?flag= 覆盖（返回 null 表示未覆盖该 key） */
function urlOverride(key) {
  try {
    const raw = new URLSearchParams(window.location.search).get('flag')
    if (!raw) return null
    for (const part of String(raw).split(',')) {
      const [k, v] = part.split('=')
      if (k && k.trim() === key) return parseBool(v)
    }
  } catch {
    /* 静默：无 window / URL 解析失败 */
  }
  return null
}

/** 判断开关是否开启 */
export function isFlagOn(key) {
  const fromUrl = urlOverride(key)
  if (fromUrl != null) return fromUrl
  try {
    const saved = localStorage.getItem(STORE_PREFIX + key)
    if (saved != null) return saved !== '0'
  } catch {
    /* localStorage 不可用 → 用默认值 */
  }
  return DEFAULTS[key] !== false
}

/** 持久化开关（本地灰度 / 排查用） */
export function setFlag(key, on) {
  try {
    localStorage.setItem(STORE_PREFIX + key, on ? '1' : '0')
  } catch {
    /* 静默 */
  }
}

/** 清除本地覆盖，回到默认值 */
export function clearFlag(key) {
  try {
    localStorage.removeItem(STORE_PREFIX + key)
  } catch {
    /* 静默 */
  }
}
