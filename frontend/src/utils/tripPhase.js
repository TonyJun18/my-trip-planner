/**
 * 详情页「时机」判定（四态）：planning / prep / live / finished
 *
 * 与 `api/modules/analytics.js` 的 tripPhase（三态，埋点用）分开：
 * 埋点口径已定死为 planning/live/finished，不能因为 IA 需要多一个「行前」而漂移，
 * 否则历史基线无法对齐。本模块只服务详情页的版面/操作换血。
 *
 * prep（行前）的锚点基准（PRD §4 裁决）：
 *   首个 stop_type === 'hotel' 的站点所在日 → 该日 00:00 减 48h 起进入 prep；
 *   无 hotel 站点 → 行程 start_date 减 48h 兜底。
 *   注意：**不用 plan.checkin**——它是入住指引产物（dict），不是日期字段。
 */

const PREP_LEAD_MS = 48 * 60 * 60 * 1000

export const TRIP_DETAIL_PHASES = ['planning', 'prep', 'live', 'finished']

/** 'YYYY-MM-DD' → 本地时区当天 00:00 */
function parseDateOnly(value) {
  if (!value) return null
  const d = new Date(`${value}T00:00:00`)
  return Number.isNaN(d.getTime()) ? null : d
}

function startOfToday() {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d
}

function addDays(date, n) {
  const d = new Date(date.getTime())
  d.setDate(d.getDate() + n)
  return d
}

/**
 * 行前锚点日：首个 hotel 站点所在日；无则行程开始日。
 * @returns {Date|null}
 */
export function prepAnchorDate(trip) {
  const start = parseDateOnly(trip?.start_date)
  if (!start) return null
  for (const day of trip?.days || []) {
    const isHotelDay = (day.stops || []).some((s) => s?.stop_type === 'hotel')
    if (isHotelDay) {
      const offset = Math.max(0, (Number(day.day_number) || 1) - 1)
      return addDays(start, offset)
    }
  }
  return start
}

/**
 * 判定详情页时机。
 * @param {object} trip 行程对象（需 start_date / end_date，可选 days）
 * @returns {'planning'|'prep'|'live'|'finished'}
 */
export function detailPhase(trip) {
  const start = parseDateOnly(trip?.start_date)
  const end = parseDateOnly(trip?.end_date) || start
  if (!start || !end) return 'planning'

  const today = startOfToday()
  if (today > end) return 'finished'
  if (today >= start) return 'live'

  const anchor = prepAnchorDate(trip) || start
  const prepFrom = new Date(anchor.getTime() - PREP_LEAD_MS)
  return today >= prepFrom ? 'prep' : 'planning'
}

/** 行中当前是第几天（不在行中返回 null） */
export function currentDayNumber(trip) {
  const start = parseDateOnly(trip?.start_date)
  if (!start) return null
  const today = startOfToday()
  const diff = Math.round((today - start) / (24 * 60 * 60 * 1000))
  const total = (trip?.days || []).length || 0
  if (diff < 0) return null
  if (total && diff + 1 > total) return null
  return diff + 1
}
