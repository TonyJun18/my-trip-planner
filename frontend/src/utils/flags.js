/**
 * 最小 Feature Flag 模块（本地优先 + 服务端回滚口）。
 *
 * 用途：信息架构类改版（如详情页 IA v2）需要可回滚开关 —— 既能在验收时逐人对照，
 * 也要能让运维**在不重新发布前端的前提下**把全站切回旧版面。
 *
 * 解析优先级（高 → 低）：
 *   1. URL 覆盖 —— `?flag=tripDetail.ia.v2=off`（可逗号分隔多项；仅限验收/排查，
 *      **不持久**：刷新后 URL 仍在则继续生效，链接被复制出去也会带上，别当用户分流手段）
 *   2. 服务端下发 —— `GET /api/v1/flags`（`primeFlags()` 拉取；仅当服务端**显式**下发
 *      该 key 时才覆盖，env 为空 → 不影响本地）
 *   3. localStorage —— `setFlag(key, on)`，单浏览器灰度/排查
 *   4. 内置默认值 DEFAULTS
 *
 * 分级与依赖（`docs/plans/2026-11-08-trip-detail-ia-v2-phase2-closeout.md` §3.0）：
 *   tripDetail.ia.v2               总闸：关 = 完整 v1 三段式平铺
 *     ├ tripDetail.ia.v2.tabs       时机 tab 收纳（关 = 12 面板平铺）
 *     ├ tripDetail.ia.v2.hoist      AI 修订/备选提升到主路径（关 = 回工具箱）
 *     └ tripDetail.ia.v2.collapseDays 逐日默认折叠（关 = 全展开）
 *   子开关**仅在总闸开启时生效**：避免「总闸关 + 子开关开」产生第四种无法验收的版面。
 *
 * 约定：
 * - 响应式：服务端开关是运行中到达的，`useFlag()` 返回 computed，取到新值即重渲染
 *   （旧版 `ref(isFlagOn(...))` 只在 setup 读一次，等于没有 kill switch）
 * - 所有异常静默降级到默认值（隐私模式 / localStorage 不可用 / 接口 404 都不阻断页面）
 * - 关闭值识别：off / 0 / false / no（大小写不敏感）
 */
import { computed, reactive } from 'vue'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const DEFAULTS = {
  // 总闸：按时机收纳次级工具（tabs）+ 规划工具提升 + 逐日折叠，一并控制
  'tripDetail.ia.v2': true,
  // 子开关：仅在总闸开启时生效
  'tripDetail.ia.v2.tabs': true,
  'tripDetail.ia.v2.hoist': true,
  'tripDetail.ia.v2.collapseDays': true,
}

const MASTER = 'tripDetail.ia.v2'
const STORE_PREFIX = 'mtp.flag.'
const OFF_VALUES = ['off', '0', 'false', 'no']

/** 服务端显式下发的值（未下发的 key 不在此对象里，避免「远端没提」覆盖本地） */
const remote = reactive({})
/** 内置默认值（唯一可变来源之外的第二层，便于极端情况下临时改默认） */
const defaults = reactive({ ...DEFAULTS })

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

/** 读取 localStorage 覆盖（返回 null 表示未设置） */
function storedOverride(key) {
  try {
    const saved = localStorage.getItem(STORE_PREFIX + key)
    if (saved != null) return saved !== '0'
  } catch {
    /* localStorage 不可用 */
  }
  return null
}

/** 单个 key 的直接解析（不含分级依赖） */
function resolveOne(key) {
  const fromUrl = urlOverride(key)
  if (fromUrl != null) return fromUrl
  if (key in remote) return remote[key]
  const fromStore = storedOverride(key)
  if (fromStore != null) return fromStore
  return defaults[key] !== false
}

/** 带依赖的解析：子开关跟随总闸 */
function resolve(key) {
  if (key !== MASTER && !resolveOne(MASTER)) return false
  return resolveOne(key)
}

/**
 * 组件内读取开关（响应式）。script setup 里返回 computed，模板自动解包。
 * @param {string} key
 */
export function useFlag(key) {
  return computed(() => resolve(key))
}

/** 同步读取（事件处理 / 非渲染逻辑用） */
export function isFlagOn(key) {
  return resolve(key)
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

/**
 * 拉取服务端开关快照并合入（App 启动时调一次）。
 *
 * 失败静默：接口不可用 / 离线 / 返回非法结构 → 保持本地状态，绝不阻断页面。
 * 只接受 DEFAULTS 里已有的 key（防止后端笔误造出前端不认识、永远无效的开关）。
 */
export async function primeFlags() {
  try {
    const resp = await fetch(`${API_BASE}/flags`)
    if (!resp.ok) return
    const data = await resp.json()
    const flags = data?.flags
    if (!flags || typeof flags !== 'object') return
    for (const key of Object.keys(DEFAULTS)) {
      if (typeof flags[key] === 'boolean') remote[key] = flags[key]
    }
    // revision 留在 window 上，排查时一眼确认「服务端下发的是哪一版」
    if (typeof window !== 'undefined') window.__mtpFlagsRevision = data?.revision ?? ''
  } catch {
    /* 静默：无网络 / 端点缺失都不影响页面 */
  }
}

/** 已声明的开关 key 列表（排查 / 文档用） */
export const FLAG_KEYS = Object.keys(DEFAULTS)
