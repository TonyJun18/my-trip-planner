<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Calendar, Plus } from '@element-plus/icons-vue'
import * as api from '@/api'
// 阶段一拆分：TripDetailView 收敛为 orchestrator（装配 + 共享状态 + 对话框）
// 阶段二信息架构：头部合并（Header）+ 次级工具按时机收纳（Workspace）
// 组件树见 docs/plans/2026-10-29-trip-detail-refactor-solution.md §1.1 / §2.1
import TripDetailHeader from '@/components/trip-detail/TripDetailHeader.vue'
import TripDetailLiveToday from '@/components/trip-detail/TripDetailLiveToday.vue'
import TripDetailBudgetBar from '@/components/trip-detail/TripDetailBudgetBar.vue'
import TripDetailMapCard from '@/components/trip-detail/TripDetailMapCard.vue'
import TripDetailPlanTools from '@/components/trip-detail/TripDetailPlanTools.vue'
import TripDetailDayCard from '@/components/trip-detail/TripDetailDayCard.vue'
import TripDetailToolbox from '@/components/trip-detail/TripDetailToolbox.vue'
import TripDetailWorkspace from '@/components/trip-detail/TripDetailWorkspace.vue'
import TripDetailSidebar from '@/components/trip-detail/TripDetailSidebar.vue'
import TripDetailRatingCard from '@/components/trip-detail/TripDetailRatingCard.vue'
import TripDetailQaCard from '@/components/trip-detail/TripDetailQaCard.vue'
import TripDetailDialogs from '@/components/trip-detail/TripDetailDialogs.vue'
import AddExpenseDialog from '@/components/AddExpenseDialog.vue'
import { useTripDetailLoad } from '@/composables/useTripDetailLoad'
import { useRevise } from '@/composables/useRevise'
import { useEditDialog } from '@/composables/useEditDialog'
import { useTripShareActions } from '@/composables/useTripShareActions'
import { useExport } from '@/composables/useExport'
import { useTripTypes } from '@/composables/useTripTypes'
import { useFlag } from '@/utils/flags'
import { isOnline } from '@/utils/pwa'
import { detailPhase, currentDayNumber } from '@/utils/tripPhase'
import { trackEvent, ANALYTICS_EVENTS, tripPhase } from '@/api/modules/analytics'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// ── 核心加载域（trip/budget/plan/离线降级/行中/Plan B） ──
// 子组件 ref（Toolbox 内部 JourneyTimeline / PassportPanel / Sidebar 仪表盘刷新）
const toolboxRef = ref(null)  // TripDetailToolbox（暴露 loadJourney / loadPassport）
const sidebarRef = ref(null)  // TripDetailSidebar（暴露 load）
// 折叠头信息徽标（预订数 / 追踪进度 / 护照徽章）——轻量并行拉取，失败静默
const tripSummaries = ref({ journey: null, passport: null })
async function loadSummaries() {
  if (!trip.value?.id || offlineFallback.value) return
  try {
    const [j, p] = await Promise.all([
      api.getJourney(trip.value.id),
      api.getPassport(trip.value.id),
    ])
    tripSummaries.value = { journey: j, passport: p }
  } catch {
    tripSummaries.value = { journey: null, passport: null }
  }
}
// 预订折叠头徽标（来自 journey 投影的 booking_status，无需额外请求）
const bookingBadge = computed(() => {
  const bs = tripSummaries.value?.journey?.booking_status
  if (!bs) return ''
  const confirmed = bs.confirmed || 0
  const pending = bs.pending || 0
  if (!confirmed && !pending) return ''
  const parts = []
  if (confirmed) parts.push(t('tripDetail.badgeConfirmed', { n: confirmed }))
  if (pending) parts.push(t('tripDetail.badgePending', { n: pending }))
  return parts.join(' · ')
})
// 追踪折叠头徽标（如“完成 12/20 · 进行中”或“已完成”）
const journeyBadge = computed(() => {
  const j = tripSummaries.value?.journey
  if (!j) return ''
  const total = j.total_stops || 0
  if (!total) return ''
  const done = j.completed_stops || 0
  const phaseMap = { live: t('journey.phase.live'), finished: t('journey.phase.finished'), upcoming: t('journey.phase.upcoming') }
  const phase = phaseMap[j.phase] || ''
  return `${done}/${total}${phase ? ' · ' + phase : ''}`
})
// 护照折叠头徽标
const passportBadge = computed(() => {
  const p = tripSummaries.value?.passport
  if (!p?.badge_count) return ''
  return `${p.badge_count}`
})

function refreshJourney() {
  // 子组件内部面板刷新（Toolbox 内 JourneyTimeline/PassportPanel/ExpensePanel + Sidebar 内 TripDashboard）
  toolboxRef.value?.loadJourney()
  toolboxRef.value?.loadPassport()
  toolboxRef.value?.loadExpense()
  sidebarRef.value?.load()
  loadSummaries()
}

// ── 行中「记一笔」对话框（今日卡片入口；工具箱内也有独立面板，同一 API） ──
const expenseDialogVisible = ref(false)

// ── 离线降级（task-offline-degrade）：在线才加载地图瓦片，离线改「按日站点列表」 ──
const online = ref(isOnline())
function syncOnline() {
  online.value = isOnline()
}

// ── 协作变更提示（task-collab-update-notice）：同伴改了行程 → 顶部轻提示「刷新查看」 ──
// 事件不带 actor（后端事件流是事实记录，不做身份承载），因此用「本地写入抑制窗」区分自己：
// 自己刚发起的写操作 8 秒内到达的事件不提示，避免刷新按钮被自己的动作点亮。
const collabStale = ref(false)
const COLLAB_SUPPRESS_MS = 8000
let suppressCollabUntil = 0
function markLocalWrite() {
  suppressCollabUntil = Date.now() + COLLAB_SUPPRESS_MS
}
function reloadFromCollab() {
  collabStale.value = false
  suppressCollabUntil = Date.now() + COLLAB_SUPPRESS_MS
  load()
  loadSummaries()
  if (live.value?.phase === 'live') loadLive()
}
// 会改动行程内容的协作事件（评论/投票/分享不算——它们不改行程，不该让人以为要刷新）
const COLLAB_STALE_EVENTS = new Set(['edit', 'revise', 'check', 'skip', 'delay', 'expense', 'chat_edit'])
function isCollabContentEvent(type) {
  if (!type) return false
  if (type === 'event.booking.confirmed' || type === 'event.booking.cancelled') return true
  return type.startsWith('event.') && COLLAB_STALE_EVENTS.has(type.slice(6))
}

// 本地写操作包装：记账（今日卡片入口 / 工具箱内面板）也走同一抑制窗
function onExpenseAdded() {
  markLocalWrite()
  refreshJourney()
}
function onToolboxChanged() {
  markLocalWrite()
  load()
}

const core = useTripDetailLoad({ onJourneyChange: refreshJourney, onLocalWrite: markLocalWrite })
const {
  trip, loading, budget, plan, offlineFallback,
  live, liveOp,
  planB, activePlan, planOptions, onPlanChange,
  doCheckStop, doSkipStop, doDelayTrip, loadLive, load,
} = core

// ── 分享 / 收藏 / 画廊 / 受邀编辑权 ──────────────────────
const share = useTripShareActions({ trip, afterChange: load })
const {
  sharing, xhsNoteVisible, importVisible, doShare,
  publishGallery,
  doShareEdit, doRevokeShareEdit,
  shareSettingsVisible, lifecycleItems, lifecycleLoading, ttlUpdating, revokingKind,
  openShareSettings, loadShareLifecycle, lifecycleStatus, copyShareUrl, setTtl, revokeShareLink, ttlOptions,
  passwordUpdating, setSharePassword, clearSharePassword,
  isFavorite, favoriting, hasSharedToken, toggleFavorite,
} = share

// load 内部在行程已分享时检查收藏状态（注入 share 域的实现）
core.setCheckFavorite(share.checkFavorite)

// ── AI 对话式修订行程（方案 B：revise） ──────────────────
const reviseState = useRevise({
  afterRevise: () => {
    markLocalWrite()  // 自己发起的修订：抑制窗内不弹「同伴更新」提示
    budget.value = null
    load()
  },
})
const {
  reviseMsg, revising, lastReviseSummary, lastReviseDiff, reviseError, reviseDone, lastReviseQuality,
  visibleReviseDiff, reviseDiffMore, diffText, revise,
} = reviseState

// ── 编辑对话框（行程/日程/站点三合一） ────────────────────
const edit = useEditDialog({
  trip,
  afterSave: (opts) => {
    markLocalWrite()
    if (opts?.deleted) {
      router.push('/trips')
    } else {
      load()
    }
  },
})
const {
  editType, editDayId, editStopId, dialogVisible, stopFormRef,
  stopForm, dayForm, tripForm, tripTypeOptions, tripTypeDisplay,
  openEditTrip, saveTrip, openAddDay, saveDay,
  openEditStop, openAddStop, saveEditStop, saveStop,
  moveStop, removeStop, removeDay, removeTrip,
} = edit

// ── 导出（截图 / PDF / JSON / 打印） ─────────────────────
const exportEl = ref(null)
const exp = useExport({ exportEl, getTrip: () => trip.value })
const { exporting, doExportImage, doExportPdf, doExportJson, doExportIcs, doPrint } = exp

// ── 三段式旅程工作台（task-trip-detail-triptych：主路径 + 工具分离） ──
// 段1 头部：紧凑摘要条（hero-bar）
// 段2 主内容：地图（activeDay 联动高亮）+ 逐日卡大纲 + 右侧 sticky 仪表盘
// 段3 工具箱：次级功能统一容器收纳（规划修订 / 旅程执行 / 装备素材）
// - activeDay：聚焦某日 → 地图高亮该日 marker + 视野聚焦；null = 全部
// - 导出时 exportAll=true → 透传 CollapsibleSection.forceOpen（修复 §0 forceOpen 未接线问题）
const activeDay = ref(null)
const exportAll = ref(false)

function focusDay(dayNumber) {
  const on = activeDay.value === dayNumber ? null : dayNumber
  activeDay.value = on
  // 聚焦某日 → 顺带展开该日，避免「地图高亮但下方看不到站点」
  if (on != null && iaV2.value) openDayByNumber(on)
}

// ── 时机（planning / prep / live / finished）────────────────
// 四态只服务版面与操作换血；埋点仍用三态 tripPhase（基线口径不能漂移）
const phase = computed(() => (trip.value ? detailPhase(trip.value) : 'planning'))

// ── 信息架构 v2（feature flag 分级可回滚）────────────────
// 总闸 off = 恢复「三段式工具箱全部平铺」，用于 G1 工具流失对照组
// 子开关仅在总闸开启时生效（依赖关系在 flags.js 里统一处理），分别控制：
//   tabs        时机 tab 收纳（off = 12 面板平铺，主路径 PlanTools 保留）
//   hoist       AI 修订 / 备选提升到主路径（off = 回工具箱，G1 对照组）
//   collapseDays 逐日默认折叠（off = 全展开）
const iaV2 = useFlag('tripDetail.ia.v2')
const tabsV2 = useFlag('tripDetail.ia.v2.tabs')
const hoistV2 = useFlag('tripDetail.ia.v2.hoist')
const collapseDaysV2 = useFlag('tripDetail.ia.v2.collapseDays')


// ── 次级工作台：按时机收纳面板（tab + 全部工具开关）──────────
const WS_PLAN_KEYS = ['revise', 'planb', 'timegate', 'quality', 'hotel']
const WS_PREP_KEYS = ['booking', 'hotel', 'servicing', 'flights', 'packing', 'events']
const WS_LIVE_KEYS = ['journey', 'expense', 'passport', 'story']
// 已结束：行程走完了，「追踪进度」仍有意义（回顾走到了哪），但事件流重新有价值（消费/打卡记录），
// 而「行中」这个标签已经不成立 —— 单独一组，标签用「回顾」。
const WS_FINISHED_KEYS = ['journey', 'expense', 'passport', 'story', 'events']

const wsTab = ref('')
const wsShowAll = ref(false)
// 非规划时机：规划面板默认隐藏，由「更多 → 调整行程」或 tab 显式打开
const wsPlanExtra = ref(false)

const planIssues = computed(() => {
  const q = plan.value?.quality?.issues?.length || 0
  const g = plan.value?.time_gate?.issues?.length || 0
  return q + g
})

const journeyProgress = computed(() => {
  const j = tripSummaries.value?.journey
  if (!j?.total_stops) return ''
  return `${j.completed_stops || 0}/${j.total_stops}`
})

const phaseTabs = computed(() => {
  const p = phase.value
  if (p === 'prep') {
    // 行前给两个 tab：默认停在「行前」，但质检/时间校验（规划工具）不再需要
    // 「更多 → 调整行程」两跳才能看见 —— 徽标直接告诉你还有几个问题没处理。
    return [
      { key: 'prep', label: t('tripDetail.tabs.prep'), keys: WS_PREP_KEYS, badge: bookingBadge.value },
      planTab.value,
    ]
  }
  if (p === 'live') {
    return [{ key: 'live', label: t('tripDetail.tabs.live'), keys: WS_LIVE_KEYS, badge: journeyProgress.value }]
  }
  if (p === 'finished') {
    return [{ key: 'review', label: t('tripDetail.tabs.review'), keys: WS_FINISHED_KEYS, badge: journeyProgress.value }]
  }
  return [planTab.value]
})

const planTab = computed(() => ({
  key: 'plan',
  label: t('tripDetail.tabs.plan'),
  keys: WS_PLAN_KEYS,
  badge: planIssues.value ? String(planIssues.value) : '',
}))

const wsTabs = computed(() => {
  // flag 关闭（总闸 off 或只关 tab 收纳）→ 不出现 tab 条：
  // 此时 wsKeys 为 null（渲染全部面板），留一个点了不生效的死 tab 是最糟的对照组形态
  if (!iaV2.value || !tabsV2.value) return []
  const tabs = phaseTabs.value
  if (wsPlanExtra.value && !tabs.some((x) => x.key === 'plan')) return [...tabs, planTab.value]
  return tabs
})

const activeTab = computed(() => wsTabs.value.find((x) => x.key === wsTab.value) || wsTabs.value[0] || null)

// 传给工具箱的面板白名单：null = 全部（全部工具 / 导出模式 / flag 关闭）
const wsKeys = computed(() => {
  if (!iaV2.value || !tabsV2.value || wsShowAll.value || exportAll.value) return null
  return activeTab.value?.keys || null
})

// ── 规划修订 + 行程备选：提到主路径（地图与行程大纲之间）──────
// 这两个是主线操作，收在工作台底部需要先滚完整段大纲才够得着。
// 时机策略（2026-11-06 修正）：AI 调整行程**任何时机都常驻**。
//   上一版按 phase==='planning' 才显示，行前（prep）/行中（live）/已结束（finished）
//   全部隐藏，只剩「更多 → 调整行程」这一个隐藏入口 —— 用户在详情页根本找不到改行程，
//   而改行程正是本产品的核心 AI 动作（行前换酒店、行中顺延/删站都靠它）。
//   因此这里不再跟时机绑定，只保留导出态隐藏（导出物是给同行人看的行程，不该出现输入框）。
// 行程备选方案（planB 段）仍按数据条件渲染：后端没生成备选就不占版面。
const planToolsVisible = computed(() => iaV2.value && hoistV2.value && !exportAll.value)
// 交给工具箱的「已提升」名单：hoist 开启时这两个面板永远不在工具箱里渲染，避免同屏两份。
// 注意：导出态（PlanTools 卸载）仍然算「已提升」——修订输入框不该被截图/PDF 带走。
const hoistedPlanKeys = computed(() => (iaV2.value && hoistV2.value ? ['revise', 'planb'] : []))

// 时机切换后重定位到该时机的主 tab（并收起「额外打开的规划」）
watch(phase, () => {
  wsPlanExtra.value = false
  wsShowAll.value = false
  wsTab.value = wsTabs.value[0]?.key || ''
}, { immediate: true })

// 开关变化（含服务端 kill switch 运行中到达）→ 回到当前时机的首个 tab。
// 旧座面残留的 wsTab（如 v2 的 'prep' 在 v1 下不存在）会让 activeTab 落空，
// 表现为「工作台一片空白」，比整块回滚更糟。
watch([iaV2, tabsV2], () => {
  wsPlanExtra.value = false
  wsShowAll.value = false
  wsTab.value = wsTabs.value[0]?.key || ''
})

// 用户手动切 tab 时退出「全部工具」态（顺带埋点：G1 的「tab 迷路」信号）
function onWsTabChange(key) {
  if (trip.value?.id) {
    trackEvent(ANALYTICS_EVENTS.workspaceTabSwitch, {
      trip_id: trip.value.id,
      trip_phase: phaseName.value,
      tab: key || undefined,
      from: wsShowAll.value ? 'all' : (wsTab.value || undefined),
    })
  }
  wsShowAll.value = false
  wsTab.value = key
}

// 「全部工具」＝ 收纳失败时的逃生通道：打开频次是 G1 最直接的风险信号
function toggleWsAll() {
  const next = !wsShowAll.value
  wsShowAll.value = next
  if (trip.value?.id) {
    trackEvent(ANALYTICS_EVENTS.workspaceAllToggle, {
      trip_id: trip.value.id,
      trip_phase: phaseName.value,
      on: next,
    })
  }
}

// ── 逐日折叠：默认只展开当天（行中）/ 第一天，导出全开 ────────
const openDayIds = ref(new Set())

function initOpenDays() {
  const days = trip.value?.days || []
  if (!days.length) {
    openDayIds.value = new Set()
    return
  }
  const cur = phase.value === 'live' ? currentDayNumber(trip.value) : null
  const target = days.find((d) => d.day_number === cur) || days[0]
  openDayIds.value = new Set(target ? [target.id] : [])
}

function isDayOpen(day) {
  if (exportAll.value) return true
  // 折叠开关关闭（对照组 / 排查中）：逐日默认全展开
  if (!collapseDaysV2.value) return true
  return openDayIds.value.has(day.id)
}

function toggleDayOpen(day) {
  const next = new Set(openDayIds.value)
  if (next.has(day.id)) next.delete(day.id)
  else next.add(day.id)
  openDayIds.value = next
}

function openDayByNumber(dayNumber) {
  const day = (trip.value?.days || []).find((d) => d.day_number === dayNumber)
  if (!day) return
  const next = new Set(openDayIds.value)
  next.add(day.id)
  openDayIds.value = next
}

const allDaysOpen = computed(() => {
  const days = trip.value?.days || []
  if (!collapseDaysV2.value) return days.length > 0
  return days.length > 0 && days.every((d) => openDayIds.value.has(d.id))
})

function toggleAllDays() {
  const days = trip.value?.days || []
  if (allDaysOpen.value) {
    // 全收 → 保留当天/第一天，避免页面彻底空白
    initOpenDays()
    return
  }
  openDayIds.value = new Set(days.map((d) => d.id))
}

// 行程大纲概览（天/站/预估花费）——首屏给一行可判断的量级
const itinerarySummary = computed(() => {
  const days = trip.value?.days || []
  let stops = 0
  let cost = 0
  for (const d of days) {
    for (const s of d.stops || []) {
      stops += 1
      cost += Number(s.estimated_cost) || 0
    }
  }
  return { days: days.length, stops, cost }
})

const itineraryMeta = computed(() =>
  // 只给「天 / 站」两个量级；花费一律交给侧栏预算明细（那里口径含往返交通，
  // 站点合计与它会差出一个交通费，同屏两个 ¥ 数字是纯噪音）
  t('tripDetail.itineraryMeta', {
    days: itinerarySummary.value.days,
    stops: itinerarySummary.value.stops,
  }),
)

// 带偏移的滚动：顶部导航是 sticky（桌面 64px / 移动 56px），
// scrollIntoView({block:'start'}) 会把目标顶到视口 0 点、被导航遮住 → 统一手算偏移
function scrollToEl(el) {
  if (!el) return false
  const navH = document.querySelector('.app-header')?.getBoundingClientRect().height || 0
  const top = el.getBoundingClientRect().top + window.scrollY - navH - 12
  window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  return true
}
// 目标元素可能是条件渲染的（如工作台/规划工具点击后才挂载）→ 轮询等待再滚，
// 固定 setTimeout 在慢设备上会滚到空气，是「点了没反应」的常见来源
function scrollToSelector(sel, tries = 0) {
  if (scrollToEl(document.querySelector(sel))) return
  if (tries >= 20) return
  setTimeout(() => scrollToSelector(sel, tries + 1), 50)
}

// 行中「打卡」：滚到今日视图；无今日视图则滚到当天日程并高亮
function scrollToToday() {
  if (scrollToEl(document.querySelector('.live-card'))) return
  const cur = currentDayNumber(trip.value)
  if (cur) openDayByNumber(cur)
  // 当天卡片的展开是异步渲染的 → 轮询到出现再滚
  let tries = 0
  const go = () => {
    const el = document.querySelectorAll('.day-card')[Math.max(0, (cur || 1) - 1)]
    if (el && scrollToEl(el)) return
    if (tries++ >= 20) return
    setTimeout(go, 50)
  }
  setTimeout(go, 50)
}

// 行中「追踪」：切到行中面板并滚到工作台
function openTrackTab() {
  wsPlanExtra.value = false
  wsShowAll.value = false
  // flag 关闭 / 当前时机没有「行中」tab（如已结束用「回顾」）时只滚到工具区，
  // 绝不写一个不存在的 wsTab（否则 activeTab 落空、工作台空白）
  if (iaV2.value && tabsV2.value && wsTabs.value.some((x) => x.key === 'live')) wsTab.value = 'live'
  scrollToSelector('.workspace')
}

function scrollToWorkspace() {
  scrollToSelector('.workspace')
}

// 「更多 → 调整行程」：聚焦到主路径上的 AI 调整卡片（任何时机都常驻），
// 顺带打开工作台的「规划」tab（时间校验 / 质检 / 住宿等次级规划工具在那里）。
function openPlanTool() {
  // v1 平铺对照组（总闸 off / tab 收纳 off）：没有 tab 可开，滚到工具区即可。
  // 不发 ai_revise 埋点——埋点口径是「面板被打开」，这里的点击并不能证明它被打开；
  // 面板自身带 @click capture，用户真展开时会照常上报。
  if (!iaV2.value || !tabsV2.value) {
    scrollToWorkspace()
    return
  }
  wsPlanExtra.value = true
  wsShowAll.value = false
  wsTab.value = 'plan'
  onToolOpen('ai_revise')
  if (planToolsVisible.value) scrollToSelector('.plan-tools')
  else scrollToWorkspace()
}

// 头部主操作（按时机换血，事件名保持与埋点一致）
function onHeaderAction(key) {
  switch (key) {
    case 'edit': onEditTrip(); break
    case 'askAi': askAI(); break
    case 'share': onShare(); break
    case 'checkin': scrollToToday(); break
    case 'track': openTrackTab(); break
    case 'export': doExportPdfAll(); break
    default: break
  }
}

// 导出前强制展开全部分区（forceOpen 接线），导出后恢复
async function withExportAll(fn) {
  exportAll.value = true
  try {
    await fn()
  } finally {
    exportAll.value = false
  }
}
// 底部导出按钮：截图/PDF 需要抓取完整行程（强制 exportAll）
async function doExportPdfAll() { await withExportAll(doExportPdf) }
async function doExportImageAll() { await withExportAll(doExportImage) }

// ── 展示派生（模板专用 computed / 状态） ─────────────────
const markers = computed(() => {
  const list = []
  for (const day of trip.value?.days || []) {
    for (const stop of day.stops || []) {
      if (stop.lat != null && stop.lng != null) {
        list.push({ lat: stop.lat, lng: stop.lng, name: stop.name, stop_type: stop.stop_type, description: stop.description, day_number: day.day_number, stop_id: stop.id, estimated_cost: stop.estimated_cost, details: stop.details || null })
      }
    }
  }
  return list
})

// 拖拽仅对 owner 开放（详情页路由为登录态 owner 视角；移动端由 TripMap 内部隐藏）
const canMapDrag = computed(() => !offlineFallback.value)

// 地图拖拽修订：拖动 marker 改坐标 → 最小 diff 原子应用
const mapDragBusy = ref(false)
const mapDragError = ref('')
async function onMapMove({ name, lat, lng, day_number }) {
  if (mapDragBusy.value || !trip.value?.id) return
  markLocalWrite()
  mapDragBusy.value = true
  mapDragError.value = ''
  try {
    const r = await api.mapEditTrip(trip.value.id, { name, lat, lng, day_number })
    if (r.applied) {
      ElMessage.success(t('tripDetail.mapDragMoved'))
      budget.value = null
      await load()
    } else {
      mapDragError.value = t('tripDetail.mapDragNoop')
      await load()
    }
  } catch (e) {
    const detail = e?.response?.data?.error?.detail
    const issues = Array.isArray(detail?.issues) ? detail.issues : []
    mapDragError.value = issues.length
      ? t('tripDetail.mapDragRejected', { msg: issues[0] })
      : t('tripDetail.mapDragFail')
    await load()
  } finally {
    mapDragBusy.value = false
  }
}

// 行程状态：展示 + 切换
const statusMap = computed(() => ({
  draft: { label: t('tripList.statusDraft'), type: 'info' },
  planning: { label: t('tripList.statusPlanning'), type: 'warning' },
  confirmed: { label: t('tripList.statusConfirmed'), type: 'success' },
  archived: { label: t('tripList.statusArchived'), type: 'info' },
}))
const statusOptions = computed(() => Object.entries(statusMap.value).map(([value, s]) => ({ value, label: s.label })))
const statusUpdating = ref(false)
async function changeStatus() {
  const newStatus = trip.value.status
  markLocalWrite()
  statusUpdating.value = true
  try {
    await api.updateTrip(route.params.id, { status: newStatus })
    ElMessage.success(t('tripDetail.statusChanged', { label: (statusMap.value[newStatus] || {}).label || newStatus }))
  } catch {
    await load()
  } finally {
    statusUpdating.value = false
  }
}

// ── 更多操作（低频/管理/危险动作收纳，避免顶栏按钮堆积） ──────
async function onMoreCommand(cmd) {
  if (cmd === 'favorite') {
    await toggleFavorite()
    return
  }
  switch (cmd) {
    case 'adjust':
      openPlanTool()
      break
    // 导出四态收进「更多」（原底部操作条的 split 下拉；页头 finished 时机另有 导出 PDF 主按钮）
    case 'export-pdf':
      await doExportPdfAll()
      break
    case 'export-image':
      await doExportImageAll()
      break
    case 'export-json':
      await doExportJson()
      break
    case 'export-ics':
      await doExportIcs()
      break
    case 'export-print':
      doPrint()
      break
    case 'import':
      importVisible.value = true
      break
    case 'gallery':
      await publishGallery()
      break
    case 'xhs':
      xhsNoteVisible.value = true
      break
    case 'share-settings':
      openShareSettings()
      break
    case 'share-edit':
      await doShareEdit()
      break
    case 'revoke-edit':
      await doRevokeShareEdit()
      break
    case 'delete':
      await removeTrip()
      break
    default:
      break
  }
}

// ── 顶栏：编辑（G5 埋点） ──
function onEditTrip() {
  trackEvent(ANALYTICS_EVENTS.topActionClick, { trip_id: trip.value?.id, trip_phase: phaseName.value, action: 'edit' })
  openEditTrip()
}

// ── 顶栏：分享（G5 埋点） ──
function onShare() {
  if (!trip.value?.id) return
  trackEvent(ANALYTICS_EVENTS.topActionClick, { trip_id: trip.value.id, trip_phase: phaseName.value, action: 'share' })
  doShare()
}

// ── 顶栏：问 AI（G5 埋点） ──
async function askAI() {
  if (!trip.value?.id) return
  trackEvent(ANALYTICS_EVENTS.topActionClick, { trip_id: trip.value.id, trip_phase: phaseName.value, action: 'ask_ai' })
  try {
    const s = await api.createChatSession({ context: { trip_id: trip.value.id } })
    ElMessage.success(t('tripDetail.askAiOpened'))
    // 跳转到聊天页并打开该会话（ChatView 按 query.session 打开）
    router.push({ name: 'chat', query: { session: s.id } })
  } catch {
    /* 拦截器已提示 */
  }
}

// ── 规划工具打开（G1 埋点：AI修订/PlanB/质检/批量生成） ──
function onToolOpen(tool) {
  if (!trip.value?.id) return
  trackEvent(ANALYTICS_EVENTS.planningToolOpen, { trip_id: trip.value.id, trip_phase: phaseName.value, tool })
}

// 按日期批量生成日程（原底部操作条的「按日期生成」；入口已上提到大纲标题行）
function onGenDaysClick() {
  genDaysVisible.value = true
  onToolOpen('batch_gen')
}

// ── 每日站点操作（上移/下移/删除收进更多，仅编辑常驻） ──────
function onStopCommand(day, stop, idx, cmd) {
  switch (cmd) {
    case 'up': moveStop(day, stop, -1); break
    case 'down': moveStop(day, stop, 1); break
    case 'delete': removeStop(day, stop); break
    default: break
  }
}
function onDayCommand(day, cmd) {
  if (cmd === 'delete') removeDay(day)
}

// ── 单日「按最优顺序重排」（task-auto-optimize-cta） ──────────
// 后端确定性最近邻（首站锚定）+ DrivingGate 前置 + 预算重算；约束未通过时内联提示，不放宽任何门。
const optimizingDay = ref('')
const optimizeErrors = ref({})
function setOptimizeError(dayId, msg) {
  optimizeErrors.value = { ...optimizeErrors.value, [dayId]: msg }
}
async function onOptimizeOrder(day) {
  if (!day?.id || !trip.value?.id || optimizingDay.value) return
  setOptimizeError(day.id, '')
  optimizingDay.value = day.id
  markLocalWrite()
  try {
    const res = await api.optimizeDayOrder(trip.value.id, day.id)
    if (!res.changed) {
      const key = res.reason === 'insufficient_coords'
        ? 'optimizeSkipCoords'
        : res.reason === 'too_few_stops' ? 'optimizeSkipFew' : 'optimizeNoChange'
      ElMessage.info(t(`tripDetail.${key}`))
      return
    }
    await load()
    ElMessage.success(t('tripDetail.optimizeDone', { km: res.saved_km }))
  } catch (e) {
    const err = e?.response?.data?.error || {}
    const issues = (err.detail?.issues || []).join('；')
    setOptimizeError(day.id, t('tripDetail.optimizeFail', {
      msg: issues || err.message || e?.message || '',
    }))
  } finally {
    optimizingDay.value = ''
  }
}

// ── 导出 split（主按钮 PDF，其余收进下拉；Tab 化后均强制展开全部分区） ─
async function onExportCommand(cmd) {
  switch (cmd) {
    case 'image': await doExportImageAll(); break
    case 'json': await doExportJson(); break
    case 'ics': await doExportIcs(); break
    case 'print': doPrint(); break
    default: break
  }
}

// ── 站点类型展示（共享 useTripTypes composable，供 LiveToday 使用） ──
const { typeLabel, typeEmoji } = useTripTypes()

// 预算环形
const budgetPercent = computed(() => {
  if (!budget.value?.total_estimated || !trip.value?.budget) return null
  return Math.min(100, Math.round((budget.value.total_estimated / trip.value.budget) * 100))
})

// 预算估算口径（诚实估算标注：来源 + 基准说明）
const basisText = computed(() => {
  const b = budget.value?.estimate_basis
  if (!b) return ''
  const parts = []
  if (b.hotel) {
    const n = b.hotel.estimated_count ?? 0
    const avg = b.hotel.avg_estimate ?? b.hotel.average_estimate ?? null
    parts.push(
      avg != null && n > 0
        ? t('share.basisHotel', { avg, n })
        : t('share.basisHotelShort')
    )
  }
  if (b.transport) {
    parts.push(
      b.transport.estimated_count
        ? t('share.basisTransport')
        : t('share.basisTransportShort')
    )
  }
  return parts.join(' · ')
})

// 酒店推荐（公共组件 HotelRecommend 接收 plan.hotels + trip.days）
const hotelCandidates = computed(() => plan.value?.hotels || [])

// 行程服务层（第二段 servicing 产物：交通/通勤/入住/折扣）
const servicingProps = computed(() => ({
  transport: plan.value?.transport || null,
  transit: plan.value?.transit || null,
  checkin: plan.value?.checkin || null,
  discountRules: plan.value?.discount_rules || [],
  discounts: plan.value?.discounts || null,
}))

// 备选方案预算（服务端已按站点汇总，与 budget_service 同构）
const planBBudget = computed(() => planB.value?.budget || null)
const planBTotal = computed(() => planBBudget.value?.total_estimated || 0)

// ── 批量生成日程（按日期范围） ─────────────────────────
const genDaysVisible = ref(false)
const genRange = ref([])
const genDaysLoading = ref(false)
async function genDays() {
  if (!genRange.value?.length) {
    ElMessage.warning(t('tripDetail.selectRange'))
    return
  }
  genDaysLoading.value = true
  markLocalWrite()
  try {
    const [start, end] = genRange.value
    const days = await api.generateDays(route.params.id, start, end)
    ElMessage.success(t('tripDetail.daysGenerated', { n: days.length }))
    genDaysVisible.value = false
    genRange.value = []
    await load()
  } finally {
    genDaysLoading.value = false
  }
}

// 分享设置弹窗展示完整链接用
const windowOrigin = window.location.origin

// 对话框透传属性（TripDetailDialogs v-bind）
// 注意：computed 返回对象内的 ref 不会自动解包（自动解包只作用于模板直接访问的顶层 ref），
// 必须 .value 取实际布尔值——否则 v-bind 展开后 RefImpl 对象恒为 truthy → 弹窗自动弹出且关不掉
const dialogsProps = computed(() => ({
  xhsNoteVisible: xhsNoteVisible.value,
  importVisible: importVisible.value,
}))

// ── 埋点：行程阶段（planning / live / finished） ──
const phaseName = computed(() => (trip.value ? tripPhase({ start_date: trip.value.start_date, end_date: trip.value.end_date }) : 'planning'))

// 埋点：滚动深度（25/50/75% 一次性 + 节流）
let scrollDepthFired = new Set()
let scrollTimer = null
function onScrollDepth() {
  if (!trip.value?.id) return
  if (scrollTimer) return
  scrollTimer = setTimeout(() => {
    scrollTimer = null
    const doc = document.documentElement
    const max = doc.scrollHeight - doc.clientHeight
    if (max <= 0) return
    const ratio = doc.scrollTop / max
    for (const depth of [25, 50, 75]) {
      if (ratio * 100 >= depth && !scrollDepthFired.has(depth)) {
        scrollDepthFired.add(depth)
        trackEvent(ANALYTICS_EVENTS.itineraryScrollDepth, { trip_id: trip.value.id, trip_phase: phaseName.value, depth })
      }
    }
  }, 300)
}

// 埋点：逐日行程首屏可见（load 完成后 IntersectionObserver）
let firstViewObs = null
let firstViewFired = false
function observeItineraryFirstView() {
  if (firstViewObs) { firstViewObs.disconnect(); firstViewObs = null }
  firstViewFired = false
  const el = document.querySelector('.day-section.day-card')
  if (!el || !trip.value?.id) return
  firstViewObs = new IntersectionObserver((entries) => {
    for (const ent of entries) {
      if (ent.isIntersecting && !firstViewFired) {
        firstViewFired = true
        trackEvent(ANALYTICS_EVENTS.itineraryFirstView, { trip_id: trip.value.id, trip_phase: phaseName.value, visible: true })
        firstViewObs?.disconnect()
      }
    }
  }, { threshold: 0.1 })
  firstViewObs.observe(el)
}

// ── 行中实时 feed：订阅行程协作频道，同伴操作时今日卡片自动刷新 ──
let collabClose = null
function watchCollabFeed() {
  if (!route.params.id) return
  collabClose = api.subscribeTripCollab(route.params.id, {
    onEvent: (evt) => {
      const type = evt?.type || ''
      // 行中相关事件（打卡/跳过/顺延）→ 刷新今日卡片；评论/投票事件不打扰
      if (type.startsWith('stop.') || type === 'trip.delayed') {
        loadLive()
      }
      // 行程内容被改动（同伴修订/打卡/跳过/顺延/记账/预订确认）→ 顶部轻提示，由用户决定何时刷新
      // 抑制窗内到达的是自己刚发起的写操作，不提示（事件流不带 actor）
      if (isCollabContentEvent(type) && Date.now() > suppressCollabUntil) {
        collabStale.value = true
      }
    },
  })
}
onMounted(() => {
  load()
  watchCollabFeed()
  window.addEventListener('scroll', onScrollDepth, { passive: true })
  window.addEventListener('online', syncOnline)
  window.addEventListener('offline', syncOnline)
})
// 首屏/切换行程后加载折叠头徽标数据（journey + passport 摘要）
watch(
  () => trip.value?.id,
  (id) => {
    if (id) loadSummaries()
  },
  { immediate: true },
)
// 逐日折叠默认态：行程/天数变化后重置（默认只展开当天或第一天）
watch(
  () => [trip.value?.id, trip.value?.days?.length || 0, phase.value],
  (id) => {
    if (id?.[0]) initOpenDays()
  },
  { immediate: true },
)
// 行程加载完成后观测逐日首屏（等 DOM 渲染，nextTick 后）
watch(
  () => trip.value?.id,
  () => {
    if (trip.value?.id) {
      setTimeout(observeItineraryFirstView, 500)
      scrollDepthFired = new Set()
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  if (collabClose) {
    collabClose()
    collabClose = null
  }
  if (firstViewObs) { firstViewObs.disconnect(); firstViewObs = null }
  window.removeEventListener('scroll', onScrollDepth)
  window.removeEventListener('online', syncOnline)
  window.removeEventListener('offline', syncOnline)
})
</script>

<template>
  <div v-loading="loading" class="detail-page">
    <!-- 合并头部（返回 / 封面 / 标题+状态 chip / 主操作≤3 / 更多） -->
    <TripDetailHeader
      v-if="trip"
      :trip="trip"
      :phase="phase"
      :status-map="statusMap"
      :status-options="statusOptions"
      :status-updating="statusUpdating"
      :trip-type-display="tripTypeDisplay"
      :sharing="sharing"
      :exporting="exporting"
      :is-favorite="isFavorite"
      :favoriting="favoriting"
      :has-shared-token="hasSharedToken"
      :edit-token="trip.edit_token || ''"
      @back="router.push('/trips')"
      @action="onHeaderAction"
      @more="onMoreCommand"
      @status-change="changeStatus"
    />
    <div v-else class="detail-back-fallback">
      <el-button link @click="router.push('/trips')">← {{ $t('tripDetail.backToTrips') }}</el-button>
    </div>

    <template v-if="trip">
      <!-- 离线模式标识（PWA：网络失败时读缓存展示；纯离线时提前告知地图降级） -->
      <el-alert
        v-if="offlineFallback || !online"
        class="offline-banner"
        type="warning"
        :closable="false"
        show-icon
      >
        <template #title>
          {{ $t('tripDetail.offlineMode') }} · {{ $t('tripDetail.offlineModeHint') }}
        </template>
      </el-alert>

      <!-- 协作变更提示：同伴改了行程 → 不自动刷新（会打断当前操作），交给用户点一下 -->
      <!-- 刻意放在 exportEl 之外：提示条不该进 PDF / 截图导出 -->
      <el-alert
        v-if="collabStale"
        class="collab-stale-banner"
        type="info"
        :closable="true"
        show-icon
        @close="collabStale = false"
      >
        <template #title>
          <span class="collab-stale-text">{{ $t('tripDetail.collabStale') }}</span>
          <el-button link type="primary" size="small" @click="reloadFromCollab">
            {{ $t('tripDetail.collabStaleAction') }}
          </el-button>
        </template>
      </el-alert>

      <!-- 导出区（截图/PDF 抓取范围） -->
      <div ref="exportEl" class="export-area">
        <!-- 行中「今日视图」（live 期间全宽置顶） -->
        <TripDetailLiveToday
          :live="live"
          :live-op="liveOp"
          :type-emoji="typeEmoji"
          :type-label="typeLabel"
          @check="doCheckStop"
          @skip="doSkipStop"
          @delay="doDelayTrip"
          @add-expense="expenseDialogVisible = true"
        />

        <!-- 行中「记一笔」：预算口径用于记账后的超预算提示（超了才提示，不做常驻预警） -->
        <AddExpenseDialog
          v-if="trip"
          v-model="expenseDialogVisible"
          :trip-id="trip.id"
          :budget-total="Number(trip.budget) || 0"
          :spent-total="Number(tripSummaries?.journey?.expense_total) || 0"
          @added="onExpenseAdded"
        />

        <!-- 主路径：地图 + 逐日大纲（永不进 tab）+ 侧栏仪表盘 -->
        <div class="detail-layout">
          <div class="main-col">
            <!-- 常驻预算条（Mindtrip 持久预算条 / DVGO 含·不含口径）：与今日卡片同屏，随时可见 -->
            <TripDetailBudgetBar
              :budget-planned="Number(trip?.budget) || 0"
              :estimated="Number(budget?.total_estimated) || 0"
              :spent="Number(tripSummaries?.journey?.expense_total) || 0"
              :by-type="budget?.by_type || {}"
              :basis="budget?.estimate_basis || {}"
              :travelers="Number(trip?.travelers) || 1"
            />

            <!-- 地图 -->
            <TripDetailMapCard
              :markers="markers"
              :active-day="activeDay"
              :can-map-drag="canMapDrag"
              :map-drag-error="mapDragError"
              :offline="!online"
              @clear-focus="activeDay = null"
              @map-move="onMapMove"
            />

            <!-- 规划工具：AI 调整行程 + 行程备选方案（地图下方，主路径上的高频操作） -->
            <TripDetailPlanTools
              v-if="planToolsVisible"
              :plan-b="planB"
              :active-plan="activePlan"
              :plan-options="planOptions"
              :plan-b-budget="planBBudget"
              :plan-b-total="planBTotal"
              :revise-msg="reviseMsg"
              :revising="revising"
              :revise-error="reviseError"
              :last-revise-summary="lastReviseSummary"
              :revise-done="reviseDone"
              :last-revise-diff="lastReviseDiff"
              :visible-revise-diff="visibleReviseDiff"
              :revise-diff-more="reviseDiffMore"
              :last-revise-quality="lastReviseQuality"
              :diff-text="diffText"
              @plan-change="onPlanChange"
              @revise="revise"
              @revise-input="(v) => (reviseMsg = v)"
              @tool-open="onToolOpen"
            />

            <!-- 逐日大纲：标题行（概览 + 日程操作 + 批量展开）+ 可折叠日程卡 -->
            <div class="itinerary-head">
              <span class="itinerary-title">
                <el-icon><Calendar /></el-icon>{{ $t('tripDetail.itineraryTitle') }}
              </span>
              <span class="itinerary-meta">{{ itineraryMeta }}</span>
              <!-- 日程操作跟随它们的对象（日程列表）放在标题行右侧：
                   旧版在列表之后单起一条底栏，把「大纲 → 工作台」切成两段，形成断档 -->
              <div class="itinerary-acts">
                <button class="itinerary-act" type="button" @click="openAddDay">
                  <el-icon><Plus /></el-icon>{{ $t('tripDetail.addDay') }}
                </button>
                <button class="itinerary-act" type="button" @click="onGenDaysClick">
                  <el-icon><Calendar /></el-icon>{{ $t('tripDetail.genDays') }}
                </button>
                <button
                  v-if="collapseDaysV2"
                  class="itinerary-toggle"
                  type="button"
                  @click="toggleAllDays"
                >
                  {{ allDaysOpen ? $t('tripDetail.collapseAllDays') : $t('tripDetail.expandAllDays') }}
                </button>
              </div>
            </div>

            <TripDetailDayCard
              v-for="(day, i) in trip.days"
              :key="day.id"
              :day="day"
              :active-day="activeDay"
              :day-index="i"
              :open="isDayOpen(day)"
              :optimizing="optimizingDay === day.id"
              :optimize-error="optimizeErrors[day.id] || ''"
              @toggle-open="toggleDayOpen"
              @focus-day="focusDay"
              @add-stop="openAddStop"
              @day-cmd="onDayCommand"
              @stop-cmd="onStopCommand"
              @stop-edit="openEditStop"
              @optimize-order="onOptimizeOrder"
            />

            <!-- 日程操作条已上提到大纲标题行（加天 / 批量生成），导出收进头部「更多」 -->

            <!-- 次级工作台：按时机收纳 12 个工具面板 -->
            <TripDetailWorkspace
              :tabs="wsTabs"
              :model-value="wsTab"
              :show-all="wsShowAll || exportAll"
              :title="$t('tripDetail.workspaceTitle')"
              @update:model-value="onWsTabChange"
              @toggle-all="toggleWsAll"
            >
              <TripDetailToolbox
                ref="toolboxRef"
                :trip="trip"
                :plan="plan"
                :plan-b="planB"
                :active-plan="activePlan"
                :plan-options="planOptions"
                :plan-b-budget="planBBudget"
                :plan-b-total="planBTotal"
                :hotel-candidates="hotelCandidates"
                :servicing-props="servicingProps"
                :booking-badge="bookingBadge"
                :journey-badge="journeyBadge"
                :passport-badge="passportBadge"
                :export-all="exportAll"
                :keys="wsKeys"
                :flat="!(wsShowAll || exportAll)"
                :hoisted-keys="hoistedPlanKeys"
                :revise-msg="reviseMsg"
                :revising="revising"
                :revise-error="reviseError"
                :last-revise-summary="lastReviseSummary"
                :revise-done="reviseDone"
                :last-revise-diff="lastReviseDiff"
                :visible-revise-diff="visibleReviseDiff"
                :revise-diff-more="reviseDiffMore"
                :last-revise-quality="lastReviseQuality"
                :diff-text="diffText"
                @plan-change="onPlanChange"
                @revise="revise"
                @revise-input="(v) => (reviseMsg = v)"
                @tool-open="onToolOpen"
                @changed="onToolboxChanged"
                @arranged="onToolboxChanged"
              />
            </TripDetailWorkspace>
          </div>

          <!-- 侧栏：仪表盘（sticky 常驻） -->
          <TripDetailSidebar
            ref="sidebarRef"
            :trip-id="trip.id"
            :budget="budget"
            :budget-percent="budgetPercent"
            :basis-text="basisText"
            :trip-budget="trip.budget"
            :travelers="trip.travelers"
          />
        </div>
      </div>

      <!-- 行程评分（收尾动作：行程结束后给这次行程打分 + 标记去过）
           刻意放在导出区之外：评分是私域操作，不该被截图 / PDF 导出带走 -->
      <TripDetailRatingCard :trip-id="trip.id" :phase="phase" />

      <!-- 行程问答（task-property-qa-eval 前端接线）：只答结构化事实，零 LLM 防编造
           同样放在导出区之外 —— 交互式提问/答案不该进截图 / PDF -->
      <TripDetailQaCard :trip-id="trip.id" />
    </template>

    <!-- 对话框（小红书 / 导入 / 批量生成 / 分享设置 / 编辑三合一） -->
    <TripDetailDialogs
      v-bind="dialogsProps"
      :trip="trip"
      :edit-type="editType"
      :dialog-visible="dialogVisible"
      :stop-form="stopForm"
      :day-form="dayForm"
      :trip-form="tripForm"
      :trip-type-options="tripTypeOptions"
      :trip-type-display="tripTypeDisplay"
      :gen-days-visible="genDaysVisible"
      :gen-range="genRange"
      :gen-days-loading="genDaysLoading"
      :share-settings-visible="shareSettingsVisible"
      :lifecycle-items="lifecycleItems"
      :lifecycle-loading="lifecycleLoading"
      :revoking-kind="revokingKind"
      :password-updating="passwordUpdating"
      :ttl-options="ttlOptions"
      :window-origin="windowOrigin"
      :lifecycle-status="lifecycleStatus"
      @update:dialog-visible="(v) => (dialogVisible = v)"
      @update:stop-form-ref="(el) => (stopFormRef.value = el)"
      @update:stop-form="(v) => Object.assign(stopForm, v)"
      @update:day-form="(v) => Object.assign(dayForm, v)"
      @update:trip-form="(v) => Object.assign(tripForm, v)"
      @save-trip="saveTrip"
      @save-day="saveDay"
      @save-stop="saveStop"
      @save-edit-stop="saveEditStop"
      @update:gen-days-visible="(v) => (genDaysVisible = v)"
      @update:gen-range="(v) => (genRange = v)"
      @gen-days="genDays"
      @update:share-settings-visible="(v) => (shareSettingsVisible = v)"
      @load-share-lifecycle="loadShareLifecycle"
      @copy-share-url="copyShareUrl"
      @set-ttl="setTtl"
      @revoke-share-link="revokeShareLink"
      @set-share-password="setSharePassword"
      @clear-share-password="clearSharePassword"
      @imported="load"
      @update:import-visible="(v) => (importVisible = v)"
      @update:xhs-visible="(v) => (xhsNoteVisible = v)"
    />
  </div>
</template>

<style scoped>
.detail-page { max-width: 1080px; margin: 0 auto; }

/* 未加载完成时的返回兜底 */
.detail-back-fallback { margin-bottom: 16px; }

/* PWA 离线模式标识 */
.offline-banner { margin-bottom: 16px; }
.collab-stale-banner { margin-bottom: 16px; }
.collab-stale-text { margin-right: 8px; }

/* 双栏布局：主列（地图 + 每日行程 + 工作台）/ 侧栏（仪表盘） */
.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
  margin-bottom: 20px;
}
.main-col { min-width: 0; }

/* 逐日大纲标题行：标题 + 概览 + 批量展开 */
.itinerary-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 18px 0 10px;
}
.itinerary-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.01em;
}
.itinerary-title .el-icon { color: var(--brand); }
.itinerary-meta {
  font-size: 12.5px;
  color: var(--muted);
}
.itinerary-acts {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
/* 日程操作（加天 / 按日期生成）：与「展开全部日程」同规格的 pill 按钮，
   紧贴被操作的对象（日程列表标题行），不再单独占一条底栏 */
.itinerary-act,
.itinerary-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
  background: none;
  border: 1px solid var(--line);
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: color 0.18s, border-color 0.18s, background 0.18s;
}
.itinerary-act:hover,
.itinerary-toggle:hover { color: var(--brand); border-color: var(--brand); }
.itinerary-act:focus-visible,
.itinerary-toggle:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.itinerary-act .el-icon { font-size: 13px; }

/* 窄屏：双栏降级单列 */
@media (max-width: 960px) {
  .detail-layout { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .itinerary-head { flex-wrap: wrap; gap: 6px 10px; margin: 14px 0 8px; }
  .itinerary-acts { margin-left: 0; width: 100%; }
}

/* 打印样式：只打印导出区，隐藏交互 */
@media print {
  .revise-card, .day-actions, .stop-quick, .live-card,
  .map-hint, .map-drag-error, .itinerary-toggle, .itinerary-act, .workspace .ws-all,
  .share-settings-hint, .share-settings-body, .gen-days-hint,
  .el-dialog__wrapper, .el-overlay,
  .trip-servicing, .packing-list, .trip-event-feed, .quality-card {
    display: none !important;
  }
  .detail-page { padding: 0; }
  .map-card { max-height: 320px; overflow: hidden; }
  .export-area { border: none; }
}
</style>