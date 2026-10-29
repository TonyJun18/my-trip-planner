<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import * as api from '@/api'
// 阶段一拆分：TripDetailView 收敛为 orchestrator（装配 + 共享状态 + 对话框）
// 组件树见 docs/plans/2026-10-29-trip-detail-refactor-solution.md §1.1
import TripDetailTopBar from '@/components/trip-detail/TripDetailTopBar.vue'
import TripDetailHero from '@/components/trip-detail/TripDetailHero.vue'
import TripDetailLiveToday from '@/components/trip-detail/TripDetailLiveToday.vue'
import TripDetailMapCard from '@/components/trip-detail/TripDetailMapCard.vue'
import TripDetailDayCard from '@/components/trip-detail/TripDetailDayCard.vue'
import TripDetailToolbox from '@/components/trip-detail/TripDetailToolbox.vue'
import TripDetailSidebar from '@/components/trip-detail/TripDetailSidebar.vue'
import TripDetailBottomBar from '@/components/trip-detail/TripDetailBottomBar.vue'
import TripDetailDialogs from '@/components/trip-detail/TripDetailDialogs.vue'
import { useTripDetailLoad } from '@/composables/useTripDetailLoad'
import { useRevise } from '@/composables/useRevise'
import { useEditDialog } from '@/composables/useEditDialog'
import { useTripShareActions } from '@/composables/useTripShareActions'
import { useExport } from '@/composables/useExport'
import { useTripTypes } from '@/composables/useTripTypes'
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
  // 子组件内部面板刷新（Toolbox 内 JourneyTimeline/PassportPanel + Sidebar 内 TripDashboard）
  toolboxRef.value?.loadJourney()
  toolboxRef.value?.loadPassport()
  sidebarRef.value?.load()
  loadSummaries()
}

const core = useTripDetailLoad({ onJourneyChange: refreshJourney })
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
  isFavorite, favoriting, hasSharedToken, toggleFavorite,
} = share

// load 内部在行程已分享时检查收藏状态（注入 share 域的实现）
core.setCheckFavorite(share.checkFavorite)

// ── AI 对话式修订行程（方案 B：revise） ──────────────────
const reviseState = useRevise({
  afterRevise: () => {
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
const { exporting, doExportImage, doExportPdf, doExportJson, doPrint } = exp

// ── 三段式旅程工作台（task-trip-detail-triptych：主路径 + 工具分离） ──
// 段1 头部：紧凑摘要条（hero-bar）
// 段2 主内容：地图（activeDay 联动高亮）+ 逐日卡大纲 + 右侧 sticky 仪表盘
// 段3 工具箱：次级功能统一容器收纳（规划修订 / 旅程执行 / 装备素材）
// - activeDay：聚焦某日 → 地图高亮该日 marker + 视野聚焦；null = 全部
// - 导出时 exportAll=true → 透传 CollapsibleSection.forceOpen（修复 §0 forceOpen 未接线问题）
const activeDay = ref(null)
const exportAll = ref(false)

function focusDay(dayNumber) {
  activeDay.value = activeDay.value === dayNumber ? null : dayNumber
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

// ── 导出 split（主按钮 PDF，其余收进下拉；Tab 化后均强制展开全部分区） ─
async function onExportCommand(cmd) {
  switch (cmd) {
    case 'image': await doExportImageAll(); break
    case 'json': await doExportJson(); break
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
const dialogsProps = computed(() => ({
  xhsNoteVisible,
  importVisible,
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
      // 行中相关事件（打卡/跳过/顺延）→ 刷新今日卡片；评论/投票事件不打扰
      if (evt && ((evt.type || '').startsWith('stop.') || (evt.type || '') === 'trip.delayed')) {
        loadLive()
      }
    },
  })
}
onMounted(() => {
  load()
  watchCollabFeed()
  window.addEventListener('scroll', onScrollDepth, { passive: true })
})
// 首屏/切换行程后加载折叠头徽标数据（journey + passport 摘要）
watch(
  () => trip.value?.id,
  (id) => {
    if (id) loadSummaries()
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
})
</script>

<template>
  <div v-loading="loading" class="detail-page">
    <!-- 顶栏（返回 / 编辑 / 问AI / 分享 / 更多） -->
    <TripDetailTopBar
      :sharing="sharing"
      :is-favorite="isFavorite"
      :favoriting="favoriting"
      :has-shared-token="hasSharedToken"
      :edit-token="trip?.edit_token || ''"
      @back="router.push('/trips')"
      @edit="onEditTrip"
      @ask-ai="askAI"
      @share="onShare"
      @more="onMoreCommand"
    />

    <template v-if="trip">
      <!-- 离线模式标识（PWA：网络失败时读缓存展示） -->
      <el-alert
        v-if="offlineFallback"
        class="offline-banner"
        type="warning"
        :closable="false"
        show-icon
      >
        <template #title>
          {{ $t('tripDetail.offlineMode') }} · {{ $t('tripDetail.offlineModeHint') }}
        </template>
      </el-alert>

      <!-- 导出区（截图/PDF 抓取范围） -->
      <div ref="exportEl" class="export-area">
        <!-- 段1 头部：紧凑摘要条 -->
        <TripDetailHero
          :trip="trip"
          :status-map="statusMap"
          :status-options="statusOptions"
          :status-updating="statusUpdating"
          :trip-type-display="tripTypeDisplay"
          @status-change="changeStatus"
        />

        <!-- 行中「今日视图」（live 期间全宽置顶） -->
        <TripDetailLiveToday
          :live="live"
          :live-op="liveOp"
          :type-emoji="typeEmoji"
          :type-label="typeLabel"
          @check="doCheckStop"
          @skip="doSkipStop"
          @delay="doDelayTrip"
        />

        <!-- 段2 主内容：地图 + 逐日大纲 + 侧栏仪表盘 -->
        <div class="detail-layout">
          <div class="main-col">
            <!-- 地图 -->
            <TripDetailMapCard
              :markers="markers"
              :active-day="activeDay"
              :can-map-drag="canMapDrag"
              :map-drag-error="mapDragError"
              @clear-focus="activeDay = null"
              @map-move="onMapMove"
            />

            <!-- 逐日行程大纲 -->
            <TripDetailDayCard
              v-for="(day, i) in trip.days"
              :key="day.id"
              :day="day"
              :active-day="activeDay"
              :day-index="i"
              @focus-day="focusDay"
              @add-stop="openAddStop"
              @day-cmd="onDayCommand"
              @stop-cmd="onStopCommand"
              @stop-edit="openEditStop"
            />

            <!-- 段3 工具箱（规划修订 / 旅程执行 / 装备素材） -->
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
              @changed="load"
              @arranged="load"
            />
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

      <!-- 底部操作 -->
      <TripDetailBottomBar
        :exporting="exporting"
        @add-day="openAddDay"
        @gen-days="genDaysVisible = true; onToolOpen('batch_gen')"
        @export="doExportPdfAll"
        @export-cmd="onExportCommand"
      />
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
      @imported="load"
      @update:import-visible="(v) => (importVisible = v)"
      @update:xhs-visible="(v) => (xhsNoteVisible = v)"
    />
  </div>
</template>

<style scoped>
.detail-page { max-width: 1080px; margin: 0 auto; }

/* PWA 离线模式标识 */
.offline-banner { margin-bottom: 16px; }

/* 双栏布局：主列（地图 + 每日行程）/ 侧栏（仪表盘） */
.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
  margin-bottom: 20px;
}
.main-col { min-width: 0; }

/* 窄屏：双栏降级单列 */
@media (max-width: 960px) {
  .detail-layout { grid-template-columns: 1fr; }
}

/* 打印样式：只打印导出区，隐藏交互 */
@media print {
  .topbar, .bottom-bar, .revise-card, .day-actions, .stop-quick, .live-card,
  .map-hint, .status-switch, .map-drag-error,
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