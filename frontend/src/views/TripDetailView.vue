<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  MoreFilled, Upload, Star, Promotion, Setting, EditPen, Lock, Delete,
  Picture, Document, Download, Printer, Top, Bottom, ChatDotRound,
} from '@element-plus/icons-vue'
import * as api from '@/api'
import TripMap from '@/components/TripMap.vue'
import HotelRecommend from '@/components/HotelRecommend.vue'
import TripServicing from '@/components/TripServicing.vue'
import BookingPanel from '@/components/BookingPanel.vue'
import JourneyTimeline from '@/components/JourneyTimeline.vue'
import PassportPanel from '@/components/PassportPanel.vue'
import StoryCardGenerator from '@/components/StoryCardGenerator.vue'
import PackingList from '@/components/PackingList.vue'
import TripEventFeed from '@/components/TripEventFeed.vue'
import QualityCard from '@/components/QualityCard.vue'
import XhsNoteDialog from '@/components/XhsNoteDialog.vue'
import ImportDialog from '@/components/ImportDialog.vue'
import CollapsibleSection from '@/components/CollapsibleSection.vue'
import TripDashboard from '@/components/TripDashboard.vue'
import { useTripDetailLoad } from '@/composables/useTripDetailLoad'
import { useRevise } from '@/composables/useRevise'
import { useEditDialog } from '@/composables/useEditDialog'
import { useTripShareActions } from '@/composables/useTripShareActions'
import { useExport } from '@/composables/useExport'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// ── 核心加载域（trip/budget/plan/离线降级/行中/Plan B） ──
const journeyRef = ref(null)  // JourneyTimeline 组件引用（打卡/跳过/顺延后刷新投影）
const passportRef = ref(null)  // PassportPanel 组件引用（同样刷新）
const dashRef = ref(null)  // TripDashboard 侧栏仪表盘（同样刷新）

function refreshJourney() {
  journeyRef.value?.load()
  passportRef.value?.load()
  dashRef.value?.load()
}

const core = useTripDetailLoad({ onJourneyChange: refreshJourney })
const {
  trip, loading, budget, plan, offlineFallback,
  live, liveLoading, liveOp,
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
// - 导出时 exportAll=true：全部分区展开（截图/PDF 与旧版一致）
const activeDay = ref(null)
const exportAll = ref(false)

function focusDay(dayNumber) {
  activeDay.value = activeDay.value === dayNumber ? null : dayNumber
}

// 导出前强制展开全部分区，导出后恢复
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

// ── 问 AI：携带本行程上下文创建绑定会话（方案 1：行程感知对话） ──
async function askAI() {
  if (!trip.value?.id) return
  try {
    const s = await api.createChatSession({ context: { trip_id: trip.value.id } })
    ElMessage.success(t('tripDetail.askAiOpened'))
    // 跳转到聊天页并打开该会话（ChatView 按 query.session 打开）
    router.push({ name: 'chat', query: { session: s.id } })
  } catch {
    /* 拦截器已提示 */
  }
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

const typeLabel = computed(() => ({
  attraction: t('common.typeAttraction'),
  food: t('common.typeFood'),
  hotel: t('common.typeHotel'),
  transport: t('common.typeTransport'),
}))
const typeColor = { attraction: 'var(--brand)', food: '#c2410c', hotel: '#0d8a5f', transport: '#5b6ee1' }
const typeEmoji = { attraction: '🏞️', food: '🍜', hotel: '🏨', transport: '🚄' }

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
})
onBeforeUnmount(() => {
  if (collabClose) {
    collabClose()
    collabClose = null
  }
})
</script>
<template>
  <div v-loading="loading" class="detail-page">
    <!-- 返回 -->
    <div class="topbar">
      <button class="back-btn" @click="router.push('/trips')">
        <el-icon><ArrowLeft /></el-icon> {{ $t('tripDetail.backToTrips') }}
      </button>
      <div class="topbar-actions">
        <el-button
          v-if="hasSharedToken"
          type="info"
          plain
          :loading="favoriting"
          @click="toggleFavorite"
        >
          <el-icon style="margin-right: 4px"><StarFilled v-if="isFavorite" /><Star v-else /></el-icon>{{ isFavorite ? $t('tripDetail.favorited') : $t('tripDetail.favorite') }}
        </el-button>
        <el-button @click="openEditTrip">{{ $t('tripDetail.editBasic') }}</el-button>
        <el-button type="primary" plain :loading="sharing" @click="askAI">
          <el-icon style="margin-right: 4px"><ChatDotRound /></el-icon>{{ $t('tripDetail.askAi') }}
        </el-button>
        <el-button type="primary" :loading="sharing" @click="doShare">
          <el-icon style="margin-right: 4px"><Share /></el-icon>{{ $t('tripDetail.shareTrip') }}
        </el-button>
        <el-dropdown trigger="click" @command="onMoreCommand">
          <el-button plain>
            <el-icon style="margin-right: 4px"><MoreFilled /></el-icon>{{ $t('tripDetail.more') }}
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="import" :icon="Upload">{{ $t('tripDetail.importContent') }}</el-dropdown-item>
              <el-dropdown-item command="gallery" :icon="Star">{{ $t('tripDetail.galleryPublish') }}</el-dropdown-item>
              <el-dropdown-item command="xhs" :icon="Promotion">{{ $t('tripDetail.shareToXhs') }}</el-dropdown-item>
              <el-dropdown-item command="share-settings" :icon="Setting" divided>{{ $t('tripDetail.shareSettings') }}</el-dropdown-item>
              <el-dropdown-item
                v-if="!trip?.edit_token"
                command="share-edit"
                :icon="EditPen"
              >{{ $t('tripDetail.openEdit') }}</el-dropdown-item>
              <el-dropdown-item
                v-else
                command="revoke-edit"
                :icon="Lock"
              >{{ $t('tripDetail.revokeEdit') }}</el-dropdown-item>
              <el-dropdown-item command="delete" :icon="Delete" divided class="detail-dropdown-danger">{{ $t('tripDetail.deleteTrip') }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

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
        <!-- ═══ 段1 · 头部：紧凑摘要条 ═══ -->
        <div class="hero-bar">
          <div class="hero-main">
            <div class="hero-cover-mini">{{ (trip.destination || '?')[0] }}</div>
            <div class="hero-info">
              <div class="hero-row1">
                <h1 class="hero-title">{{ trip.title }}</h1>
                <span class="status-badge" :class="(statusMap[trip.status] || statusMap.draft).type">
                  {{ (statusMap[trip.status] || statusMap.draft).label }}
                </span>
                <el-select
                  v-model="trip.status"
                  class="status-switch"
                  size="small"
                  :loading="statusUpdating"
                  @change="changeStatus"
                >
                  <el-option v-for="opt in statusOptions" :key="opt.value" :value="opt.value" :label="opt.label" />
                </el-select>
              </div>
              <div class="hero-meta">
                <span class="hero-pill"><el-icon><Location /></el-icon>{{ trip.destination }}</span>
                <span class="hero-pill" v-if="trip.departure"><el-icon><Promotion /></el-icon>{{ $t('tripDetail.fromDeparture', { dep: trip.departure }) }}</span>
                <span class="hero-pill"><el-icon><Calendar /></el-icon>{{ trip.start_date }} ~ {{ trip.end_date }}</span>
                <span class="hero-pill"><el-icon><User /></el-icon>{{ trip.travelers }} {{ $t('common.peopleUnit') }}</span>
                <span class="hero-pill" v-if="trip.budget != null"><el-icon><Wallet /></el-icon>¥{{ trip.budget }}</span>
                <span class="hero-pill" v-if="trip.trip_type"><el-icon><Briefcase /></el-icon>{{ tripTypeDisplay(trip.trip_type) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- ═══ 段2 · 主内容：地图 + 逐日大纲 + 侧栏仪表盘 ═══ -->
        <div class="detail-layout">
          <div class="main-col">
            <!-- 地图（activeDay 联动：点击某日高亮该日站点与路线） -->
            <div class="map-card" :class="{ 'day-focused': activeDay != null }">
              <div class="card-head">
                <span class="card-title"><el-icon style="margin-right: 6px"><MapLocation /></el-icon>{{ $t('common.mapTitle') }}</span>
                <span class="map-hint">
                  <template v-if="activeDay != null">{{ $t('tripDetail.mapFocusDay', { day: activeDay }) }} · </template>
                  {{ canMapDrag ? $t('tripDetail.mapDragHint') : $t('common.mapHint') }}
                  <el-button v-if="activeDay != null" link type="primary" size="small" @click="activeDay = null" style="margin-left: 6px">
                    {{ $t('tripDetail.mapClearFocus') }}
                  </el-button>
                </span>
              </div>
              <el-alert
                v-if="mapDragError"
                class="map-drag-error"
                type="warning"
                :closable="false"
                show-icon
                :title="mapDragError"
              />
              <TripMap
                :markers="markers"
                :active-day="activeDay"
                height="360px"
                :draggable="canMapDrag"
                :on-move="onMapMove"
              />
            </div>

            <!-- 逐日行程大纲（每 Day 可展开；头部点击聚焦地图） -->
            <div class="day-section day-card" v-for="day in trip.days" :key="day.id" :class="{ 'day-active': activeDay === day.day_number }">
              <div class="day-head">
                <div class="day-headline" :class="{ clickable: day.stops.length }" @click="day.stops.length && focusDay(day.day_number)">
                  <span class="day-badge" :class="{ 'day-badge-active': activeDay === day.day_number }">Day {{ day.day_number }}</span>
                  <div>
                    <div class="day-title">
                      {{ day.date || $t('common.dayN', { n: day.day_number }) }}
                      <el-icon v-if="day.stops.length" class="day-focus-icon" :size="13" :title="$t('tripDetail.mapFocusHint')"><MapLocation /></el-icon>
                    </div>
                    <div class="day-note">{{ day.note || $t('common.freeExplore') }}</div>
                  </div>
                </div>
                <div class="day-actions">
                  <el-button size="small" type="primary" plain @click="openAddStop(day.id)">+ {{ $t('tripDetail.addStop') }}</el-button>
                  <el-dropdown trigger="click" @command="(cmd) => onDayCommand(day, cmd)">
                    <el-button size="small" plain circle aria-label="Day actions">
                      <el-icon><MoreFilled /></el-icon>
                    </el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="delete" :icon="Delete" class="detail-dropdown-danger">{{ $t('tripDetail.removeDay') }}</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </div>

                <!-- 站点时间轴 -->
                <div class="stops-list" v-if="day.stops.length">
                  <div v-for="(stop, idx) in day.stops" :key="stop.id" class="stop-item">
                    <div class="stop-rail">
                      <span class="stop-index" :style="{ background: typeColor[stop.stop_type] || 'var(--brand)' }">{{ idx + 1 }}</span>
                      <span class="rail-line" v-if="idx < day.stops.length - 1" />
                    </div>
                    <div class="stop-body">
                      <div class="stop-head">
                        <span class="stop-name">{{ stop.name }}</span>
                        <el-tag size="small" round :style="{ color: typeColor[stop.stop_type] || 'var(--brand)', background: (typeColor[stop.stop_type] || 'var(--brand)') + '1a', border: 'none' }">
                          {{ typeEmoji[stop.stop_type] }} {{ typeLabel[stop.stop_type] || stop.stop_type }}
                        </el-tag>
                      </div>
                      <div class="stop-meta">
                        <span v-if="stop.estimated_cost != null"><el-icon><Wallet /></el-icon>¥{{ stop.estimated_cost }}</span>
                        <span v-if="stop.estimated_duration_minutes"><el-icon><Clock /></el-icon>{{ stop.estimated_duration_minutes }} {{ $t('common.minutes') }}</span>
                      </div>
                      <div v-if="stop.description" class="stop-desc">{{ stop.description }}</div>
                      <div class="stop-actions">
                        <el-button link type="primary" @click="openEditStop(day, stop)">{{ $t('tripDetail.editStop') }}</el-button>
                        <el-dropdown trigger="click" @command="(cmd) => onStopCommand(day, stop, idx, cmd)">
                          <el-button link circle aria-label="Stop actions">
                            <el-icon><MoreFilled /></el-icon>
                          </el-button>
                          <template #dropdown>
                            <el-dropdown-menu>
                              <el-dropdown-item command="up" :icon="Top" :disabled="idx === 0">{{ $t('tripDetail.moveUp') }}</el-dropdown-item>
                              <el-dropdown-item command="down" :icon="Bottom" :disabled="idx === day.stops.length - 1">{{ $t('tripDetail.moveDown') }}</el-dropdown-item>
                              <el-dropdown-item command="delete" :icon="Delete" divided class="detail-dropdown-danger">{{ $t('tripDetail.deleteStop') }}</el-dropdown-item>
                            </el-dropdown-menu>
                          </template>
                        </el-dropdown>
                      </div>
                    </div>
                  </div>
                </div>
                <el-empty v-else :description="$t('common.dayEmpty')" :image-size="60" />
              </div>

              <!-- ═══ 段3 · 工具箱：规划修订 ═══ -->
            <div class="toolbox-group">
              <div class="toolbox-label"><el-icon style="margin-right: 5px"><MagicStick /></el-icon>{{ $t('tripDetail.toolboxPlan') }}</div>
              <div class="aux-area">
                <!-- AI 调整行程（规划修订入口，默认展开） -->
                <CollapsibleSection
                  plain
                  :default-open="true"
                  :storage-key="`tripDetail.aux.revise.${trip.id}`"
                >
                  <template #title>{{ $t('tripDetail.reviseTitle') }}</template>
                  <div class="revise-card aux-child">
                    <div class="revise-head">
                      <span class="revise-title"><el-icon style="margin-right: 6px"><ChatDotRound /></el-icon>{{ $t('tripDetail.reviseTitle') }}</span>
                      <span class="revise-hint">{{ $t('tripDetail.reviseHint') }}</span>
                    </div>
                    <div class="revise-row">
                      <el-input
                        v-model="reviseMsg"
                        :placeholder="$t('tripDetail.revisePlaceholder')"
                        size="large"
                        clearable
                        :disabled="revising"
                        @keyup.enter="revise"
                      />
                      <el-button type="primary" size="large" :loading="revising" @click="revise">
                        <el-icon style="margin-right: 4px"><MagicStick /></el-icon>{{ $t('tripDetail.reviseBtn') }}
                      </el-button>
                    </div>
                    <!-- 加载态提示：修订进行中（AI 解析 + 原子应用） -->
                    <div v-if="revising" class="revise-loading">
                      <el-icon class="is-loading"><Loading /></el-icon>{{ $t('tripDetail.reviseLoading') }}
                    </div>
                    <!-- 错误态：内联横幅，保留用户输入便于修正后重试 -->
                    <transition name="el-fade-in">
                      <div v-if="reviseError" class="revise-error" role="alert">
                        <el-icon style="margin-right: 6px; flex-shrink: 0; margin-top: 2px"><WarningFilled /></el-icon>
                        <div class="revise-error-body">
                          <div>{{ reviseError }}</div>
                          <div class="revise-error-sub">{{ $t('tripDetail.reviseFailRetry') }}</div>
                        </div>
                      </div>
                    </transition>
                    <transition name="el-fade-in">
                      <div v-if="lastReviseSummary" class="revise-summary">
                        <el-icon style="margin-right: 4px; color: var(--success)"><CircleCheck /></el-icon>
                        {{ lastReviseSummary }}
                      </div>
                    </transition>
                    <!-- 变更动作预览（diff 列表） -->
                    <transition name="el-fade-in">
                      <div v-if="reviseDone" class="revise-diff">
                        <div class="revise-diff-head">
                          <span class="revise-diff-title"><el-icon style="margin-right: 5px"><List /></el-icon>{{ $t('tripDetail.diffTitle') }}</span>
                          <span class="revise-diff-count" v-if="lastReviseDiff.length">{{ $t('tripDetail.diffCount', { n: lastReviseDiff.length }) }}</span>
                        </div>
                        <template v-if="lastReviseDiff.length">
                          <div v-for="(a, i) in visibleReviseDiff" :key="i" class="revise-diff-item" :class="'op-' + (a.op || '')">
                            <el-icon class="revise-diff-icon"><template v-if="a.op === 'add'"><Plus /></template><template v-else-if="a.op === 'remove'"><Minus /></template><template v-else><Edit /></template></el-icon>
                            <span class="revise-diff-text">{{ diffText(a) }}</span>
                          </div>
                          <div v-if="reviseDiffMore" class="revise-diff-more">
                            {{ $t('tripDetail.reviseDiffMore', { n: reviseDiffMore }) }}
                          </div>
                        </template>
                        <div v-else class="revise-diff-empty">{{ $t('tripDetail.diffEmpty') }}</div>
                      </div>
                    </transition>
                    <!-- 修订质控闭环：修订后的 AI 质检报告（task-revise-qa-loop） -->
                    <transition name="el-fade-in">
                      <div v-if="lastReviseQuality" class="revise-quality">
                        <div class="revise-quality-head">
                          <el-icon style="margin-right: 5px"><DataAnalysis /></el-icon>
                          <span class="revise-quality-title">{{ $t('tripDetail.reviseQualityTitle') }}</span>
                          <span class="revise-quality-score" :class="{ pass: lastReviseQuality.passed, warn: !lastReviseQuality.passed }">
                            {{ lastReviseQuality.score }}/100
                          </span>
                          <span v-if="lastReviseQuality.fix_applied" class="revise-quality-badge">{{ $t('tripDetail.reviseQualityFixApplied') }}</span>
                          <span v-if="lastReviseQuality.degraded" class="revise-quality-badge degraded">{{ $t('tripDetail.reviseQualityDegraded') }}</span>
                        </div>
                        <div v-if="lastReviseQuality.summary" class="revise-quality-summary">{{ lastReviseQuality.summary }}</div>
                        <ul v-if="lastReviseQuality.issues && lastReviseQuality.issues.length" class="revise-quality-issues">
                          <li v-for="(issue, i) in lastReviseQuality.issues.slice(0, 3)" :key="i" class="revise-quality-issue">
                            <span class="revise-quality-sev" :class="issue.severity">{{ issue.severity }}</span>
                            {{ issue.message }}
                          </li>
                        </ul>
                      </div>
                    </transition>
                  </div>
                </CollapsibleSection>

                <!-- 行程：Plan B 备选 + TimeGate 时间校验 + AI 质检（行程域规划辅助） -->
                <CollapsibleSection
                  v-if="planB"
                  plain
                  :default-open="false"
                  :storage-key="`tripDetail.aux.planb.${trip.id}`"
                >
                  <template #title>{{ $t('tripDetail.planBTitle') }}</template>
                  <div class="planb-card aux-child">
                    <div class="planb-head">
                      <span class="planb-title"><el-icon style="margin-right: 6px"><Switch /></el-icon>{{ $t('tripDetail.planBTitle') }}</span>
                      <el-segmented v-model="activePlan" :options="planOptions" size="small" @change="onPlanChange" />
                    </div>
                    <div v-if="activePlan === 'plan_b'" class="planb-body">
                      <div class="planb-meta">
                        <span class="planb-label">{{ planB.label }}</span>
                        <span class="planb-desc">{{ planB.description }}</span>
                      </div>
                      <div class="planb-deltas">
                        <div v-for="(d, i) in planB.deltas" :key="i" class="planb-delta">
                          <el-icon style="margin-right: 6px; color: var(--brand)"><RefreshRight /></el-icon>{{ d }}
                        </div>
                      </div>
                      <div class="planb-budget" v-if="planBBudget">
                        <el-icon style="margin-right: 6px"><Wallet /></el-icon>
                        {{ $t('tripDetail.planBBudgetLabel') }} ¥{{ planBTotal }}
                        <span v-if="planBBudget.by_type?.hotel" class="planb-budget-sub">
                          {{ $t('common.typeHotel') }} ¥{{ planBBudget.by_type.hotel }}
                        </span>
                      </div>
                      <div class="planb-hint">{{ $t('tripDetail.planBHint') }}</div>
                    </div>
                  </div>
                </CollapsibleSection>

                <CollapsibleSection
                  v-if="plan?.time_gate?.issues?.length"
                  plain
                  :default-open="false"
                  :storage-key="`tripDetail.aux.timegate.${trip.id}`"
                >
                  <template #title>{{ $t('tripDetail.timeGateTitle') }}</template>
                  <div class="timegate-card aux-child">
                    <div class="timegate-head">
                      <span class="timegate-title"><el-icon style="margin-right: 6px"><Clock /></el-icon>{{ $t('tripDetail.timeGateTitle') }}</span>
                      <span class="timegate-badge">{{ $t('tripDetail.timeGateBasis') }}</span>
                    </div>
                    <ul class="timegate-list">
                      <li v-for="(iss, i) in plan.time_gate.issues.slice(0, 6)" :key="i" class="timegate-item">
                        <span class="timegate-sev">{{ $t('tripDetail.timeGateWarn') }}</span>
                        <span v-if="iss.day_number" class="timegate-day">Day {{ iss.day_number }}</span>
                        <span class="timegate-msg">{{ iss.message }}</span>
                        <span v-if="iss.suggestion" class="timegate-suggestion">→ {{ iss.suggestion }}</span>
                      </li>
                    </ul>
                  </div>
                </CollapsibleSection>

                <CollapsibleSection
                  plain
                  :default-open="false"
                  :storage-key="`tripDetail.aux.quality.${trip.id}`"
                >
                  <template #title>{{ $t('quality.reportTitle') }}</template>
                  <div class="aux-child detail-quality">
                    <QualityCard :quality="plan?.quality" />
                  </div>
                </CollapsibleSection>
              </div>
            </div>

            <!-- ═══ 段3 · 工具箱：旅程执行 ═══ -->
            <div class="toolbox-group">
              <div class="toolbox-label"><el-icon style="margin-right: 5px"><DataLine /></el-icon>{{ $t('tripDetail.toolboxOps') }}</div>
              <div class="aux-area">
                <!-- 预订（可预订建议 + 凭证回填 + 状态机，执行层高频默认展开） -->
                <CollapsibleSection
                  plain
                  :default-open="true"
                  :storage-key="`tripDetail.aux.booking.${trip.id}`"
                >
                  <template #title>{{ $t('booking.panelTitle') }}</template>
                  <BookingPanel
                    :trip-id="trip.id"
                    @changed="load"
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  plain
                  :default-open="true"
                  :storage-key="`tripDetail.aux.journey.${trip.id}`"
                >
                  <template #title>{{ $t('journey.panelTitle') }}</template>
                  <JourneyTimeline
                    ref="journeyRef"
                    :trip-id="trip.id"
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  plain
                  :default-open="false"
                  :storage-key="`tripDetail.aux.passport.${trip.id}`"
                >
                  <template #title>{{ $t('passport.panelTitle') }}</template>
                  <PassportPanel
                    ref="passportRef"
                    :trip-id="trip.id"
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  plain
                  :default-open="false"
                  :storage-key="`tripDetail.aux.story.${trip.id}`"
                >
                  <template #title>{{ $t('story.panelTitle') }}</template>
                  <StoryCardGenerator
                    :trip-id="trip.id"
                  />
                </CollapsibleSection>
              </div>
            </div>

            <!-- ═══ 段3 · 工具箱：装备素材 ═══ -->
            <div class="toolbox-group">
              <div class="toolbox-label"><el-icon style="margin-right: 5px"><Suitcase /></el-icon>{{ $t('tripDetail.toolboxGear') }}</div>
              <div class="aux-area">
                <CollapsibleSection
                  plain
                  :default-open="false"
                  :storage-key="`tripDetail.aux.packing.${trip.id}`"
                >
                  <template #title>{{ $t('packing.title') }}</template>
                  <PackingList
                    :trip-id="trip.id"
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  plain
                  :default-open="false"
                  :storage-key="`tripDetail.aux.servicing.${trip.id}`"
                >
                  <template #title>{{ $t('servicing.panelTitle') }}</template>
                  <TripServicing
                    :transport="servicingProps.transport"
                    :transit="servicingProps.transit"
                    :checkin="servicingProps.checkin"
                    :discount-rules="servicingProps.discountRules"
                    :discounts="servicingProps.discounts"
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  plain
                  :default-open="false"
                  :storage-key="`tripDetail.aux.hotel.${trip.id}`"
                >
                  <template #title>{{ $t('hotel.recommendTitle') }}</template>
                  <HotelRecommend
                    :hotels="hotelCandidates"
                    :days="trip.days"
                    actionable
                    @arranged="load"
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  plain
                  :default-open="false"
                  :storage-key="`tripDetail.aux.events.${trip.id}`"
                >
                  <template #title>{{ $t('events.title') }}</template>
                  <TripEventFeed :trip-id="trip.id" />
                </CollapsibleSection>
              </div>
            </div>
          </div>

          <!-- 侧栏：仪表盘 + 行中今日（sticky 常驻） -->
          <div class="side-col">
            <!-- 行中「今日视图」（live 期间；打卡/跳过/迟到顺延） -->
            <div v-if="live && live.phase === 'live'" class="live-card">
              <div class="live-head">
                <div>
                  <div class="live-title">📅 {{ $t('tripDetail.liveTodayTitle') }}</div>
                  <div class="live-sub">{{ $t('tripDetail.liveTodaySub', { day: live.day_number, date: live.date }) }}</div>
                </div>
                <div class="live-progress">
                  <span class="live-progress-num">{{ live.completed }}/{{ live.total }}</span>
                  <el-progress :percentage="live.total ? Math.round(live.completed / live.total * 100) : 0"
                               :stroke-width="6" :show-text="false" style="width: 90px" />
                </div>
              </div>

              <div class="live-stops">
                <div v-for="stop in live.stops" :key="stop.id" class="live-stop"
                     :class="{ done: stop.checked }">
                  <el-checkbox :model-value="stop.checked"
                               :disabled="!!liveOp"
                               @change="(v) => doCheckStop(stop, v)" />
                  <div class="live-stop-info">
                    <div class="live-stop-name" :class="{ muted: stop.checked }">{{ stop.name }}</div>
                    <div class="live-stop-type">{{ typeEmoji[stop.stop_type] }} {{ typeLabel[stop.stop_type] || stop.stop_type }}</div>
                  </div>
                  <div class="live-stop-actions">
                    <el-button size="small" text type="danger" :disabled="!!liveOp"
                               @click="doSkipStop(stop)">{{ $t('tripDetail.liveSkip') }}</el-button>
                  </div>
                </div>
              </div>

              <div class="live-footer">
                <el-button size="small" type="warning" plain :loading="liveOp === 'delay'"
                           @click="doDelayTrip">{{ $t('tripDetail.liveDelay') }}</el-button>
              </div>
            </div>

            <!-- 旅程仪表盘（预算 / 追踪进度 / 预订 / 徽章） -->
            <TripDashboard
              ref="dashRef"
              :trip-id="trip.id"
              :budget="budget"
              :budget-percent="budgetPercent"
              :basis-text="basisText"
              :trip-budget="trip.budget"
              :travelers="trip.travelers"
            />
          </div>
        </div>

        <!-- 概览辅助（预订已移至追踪 Tab · AI 调整已移至行程 Tab） -->
        <!-- 概览只保留高频决策信息：地图 + 侧栏仪表盘 -->
      </div>

      <!-- 底部操作 -->
      <div class="bottom-bar">
        <el-button @click="openAddDay"><el-icon style="margin-right: 4px"><Plus /></el-icon>{{ $t('tripDetail.addDay') }}</el-button>
        <el-button @click="genDaysVisible = true"><el-icon style="margin-right: 4px"><Calendar /></el-icon>{{ $t('tripDetail.genDays') }}</el-button>
        <el-dropdown split-button type="primary" :loading="exporting" @click="doExportPdfAll" @command="onExportCommand">
          <el-icon style="margin-right: 4px"><Document /></el-icon>{{ $t('tripDetail.exportPdf') }}
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="image" :icon="Picture">{{ $t('tripDetail.exportImage') }}</el-dropdown-item>
              <el-dropdown-item command="json" :icon="Download">{{ $t('tripDetail.exportJson') }}</el-dropdown-item>
              <el-dropdown-item command="print" :icon="Printer">{{ $t('tripDetail.exportPrint') }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </template>

    <!-- 小红书笔记（生成文案/封面 → 复制 → App 发布） -->
    <XhsNoteDialog v-model="xhsNoteVisible" :trip-id="trip?.id" :trip="trip" />

    <!-- 内容导入（笔记/截图/链接/邮件 → 候选并入当前行程） -->
    <ImportDialog v-model="importVisible" :preset-trip-id="trip?.id" @imported="load" />

    <!-- 批量生成日程对话框 -->
    <el-dialog v-model="genDaysVisible" :title="$t('tripDetail.genDaysTitle')" width="440px">
      <el-form label-width="80px">
        <el-form-item :label="$t('tripDetail.genRange')">
          <el-date-picker
            v-model="genRange"
            type="daterange"
            :range-separator="$t('tripDetail.genRangeSep')"
            :start-placeholder="$t('tripDetail.genStartPh')"
            :end-placeholder="$t('tripDetail.genEndPh')"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
        <div class="gen-days-hint">{{ $t('tripDetail.genDaysHint') }}</div>
      </el-form>
      <template #footer>
        <el-button @click="genDaysVisible = false">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="genDaysLoading" @click="genDays">{{ $t('tripDetail.genBtn') }}</el-button>
      </template>
    </el-dialog>

    <!-- 分享设置（生命周期：TTL / 吊销 / 审计） -->
    <el-dialog v-model="shareSettingsVisible" :title="$t('tripDetail.shareSettingsTitle')" width="680px" @open="loadShareLifecycle">
      <div class="share-settings-hint">{{ $t('tripDetail.shareSettingsHint') }}</div>
      <div v-loading="lifecycleLoading" class="share-settings-body">
        <div v-if="!lifecycleLoading && !lifecycleItems.length" class="share-settings-empty">
          {{ $t('tripDetail.shareLinkFetchFail') }}
        </div>
        <div v-for="item in lifecycleItems" :key="item.kind" class="share-setting-card" :class="lifecycleStatus(item)">
          <div class="ss-head">
            <span class="ss-kind">{{ item.kind === 'edit' ? $t('tripDetail.shareKindEdit') : $t('tripDetail.shareKindShare') }}</span>
            <el-tag size="small" round :type="lifecycleStatus(item) === 'revoked' ? 'danger' : lifecycleStatus(item) === 'expired' ? 'warning' : 'success'">
              {{ lifecycleStatus(item) === 'revoked' ? $t('tripDetail.shareStatusRevoked') : lifecycleStatus(item) === 'expired' ? $t('tripDetail.shareStatusExpired') : $t('tripDetail.shareStatusActive') }}
            </el-tag>
          </div>

          <div class="ss-row">
            <span class="ss-label">{{ $t('tripDetail.shareUrl') }}</span>
            <span class="ss-value ss-url">
              <template v-if="item.kind === 'edit'">{{ windowOrigin }}/share/{{ item.token }}?edit=1</template>
              <template v-else>{{ item.share_url }}</template>
            </span>
            <el-button link type="primary" size="small" @click="copyShareUrl(item)">{{ $t('tripDetail.copyLink') }}</el-button>
          </div>

          <div class="ss-row">
            <span class="ss-label">{{ $t('tripDetail.shareExpires') }}</span>
            <span class="ss-value">{{ item.expires_at ? new Date(item.expires_at).toLocaleString() : $t('tripDetail.shareNever') }}</span>
            <el-select
              :model-value="0"
              size="small"
              style="width: 120px"
              :disabled="lifecycleStatus(item) !== 'active'"
              @change="(v) => setTtl(item.kind, v)"
            >
              <el-option v-for="opt in ttlOptions" :key="opt.value" :value="opt.value" :label="opt.label" />
            </el-select>
          </div>

          <div class="ss-row">
            <span class="ss-label">{{ $t('tripDetail.shareLastUsed') }}</span>
            <span class="ss-value">{{ item.last_used_at ? new Date(item.last_used_at).toLocaleString() : $t('tripDetail.shareNeverUsed') }}</span>
          </div>

          <div class="ss-actions" v-if="lifecycleStatus(item) === 'active'">
            <el-button type="danger" plain size="small" :loading="revokingKind === item.kind" @click="revokeShareLink(item)">
              {{ $t('tripDetail.shareStatusRevoked') }}
            </el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="shareSettingsVisible = false">{{ $t('common.cancel') }}</el-button>
      </template>
    </el-dialog>

    <!-- 编辑对话框（三合一） -->
    <el-dialog
      v-model="dialogVisible"
      :title="editType === 'edit-trip' ? $t('tripDetail.editTripTitle') : editType === 'add-day' ? $t('tripDetail.addDayTitle') : editType === 'edit-stop' ? $t('tripDetail.editStopTitle') : $t('tripDetail.addStopTitle')"
      width="480px"
    >
      <el-form v-if="editType === 'edit-trip'" :model="tripForm" label-width="80px">
        <el-form-item :label="$t('tripDetail.lblTitle')"><el-input v-model="tripForm.title" /></el-form-item>
        <el-form-item :label="$t('tripDetail.lblDestination')"><el-input v-model="tripForm.destination" /></el-form-item>
        <el-form-item :label="$t('tripDetail.lblDeparture')">
          <el-input v-model="tripForm.departure" :placeholder="$t('tripDetail.departurePlaceholder')" />
        </el-form-item>
        <el-form-item :label="$t('tripDetail.lblTripType')">
          <el-select v-model="tripForm.trip_type" style="width: 100%">
            <el-option v-for="opt in tripTypeOptions" :key="opt.key" :label="t('tripList.' + opt.key)" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('tripDetail.lblTravelers')"><el-input-number v-model="tripForm.travelers" :min="1" /></el-form-item>
        <el-form-item :label="$t('tripDetail.lblBudget')"><el-input-number v-model="tripForm.budget" :min="0" :step="500" /></el-form-item>
      </el-form>

      <el-form v-else-if="editType === 'add-day'" :model="dayForm" label-width="80px">
        <el-form-item :label="$t('tripDetail.lblDayNumber')"><el-input-number v-model="dayForm.day_number" :min="1" /></el-form-item>
        <el-form-item :label="$t('tripDetail.lblDate')"><el-date-picker v-model="dayForm.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item>
        <el-form-item :label="$t('tripDetail.lblNote')"><el-input v-model="dayForm.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>

      <el-form v-else ref="stopFormRef" :model="stopForm" label-width="90px">
        <el-form-item :label="$t('tripDetail.lblName')" prop="name" :rules="[{ required: true, message: $t('tripDetail.stopNameRequired') }]">
          <el-input v-model="stopForm.name" :placeholder="$t('tripDetail.stopNamePh')" />
        </el-form-item>
        <el-form-item :label="$t('tripDetail.lblType')">
          <el-radio-group v-model="stopForm.stop_type">
            <el-radio-button value="attraction">{{ $t('common.typeAttraction') }}</el-radio-button>
            <el-radio-button value="food">{{ $t('common.typeFood') }}</el-radio-button>
            <el-radio-button value="hotel">{{ $t('common.typeHotel') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="$t('tripDetail.lblLatLng')">
          <div class="latlng">
            <el-input v-model="stopForm.lat" :placeholder="$t('tripDetail.latPh')" />
            <el-input v-model="stopForm.lng" :placeholder="$t('tripDetail.lngPh')" />
          </div>
        </el-form-item>
        <el-form-item :label="$t('tripDetail.lblEstCost')"><el-input-number v-model="stopForm.estimated_cost" :min="0" :step="50" /></el-form-item>
        <el-form-item :label="$t('tripDetail.lblDuration')"><el-input-number v-model="stopForm.estimated_duration_minutes" :min="0" :step="30" /></el-form-item>
        <el-form-item :label="$t('tripDetail.lblDesc')"><el-input v-model="stopForm.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<style scoped>
.detail-page { max-width: 1080px; margin: 0 auto; }

/* PWA 离线模式标识 */
.offline-banner { margin-bottom: 16px; }

.topbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 18px;
}
.back-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: none; border: none; cursor: pointer;
  font-size: 14px; color: var(--ink-2); font-weight: 500;
  padding: 8px 12px; border-radius: var(--radius-full);
  transition: all .2s;
}
.back-btn:hover { background: var(--fill); color: var(--ink); }

/* ── 段1 头部：紧凑摘要条（task-trip-detail-triptych） ── */
.hero-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
  padding: 14px 18px;
  background: linear-gradient(135deg, var(--brand-soft), var(--card) 55%);
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-card);
}
.hero-main { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 0; }
.hero-cover-mini {
  width: 48px; height: 48px; border-radius: var(--radius-lg); flex-shrink: 0;
  background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 55%, #a1c4fd 100%);
  color: #fff; font-size: 22px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--shadow-sm);
}
.hero-info { flex: 1; min-width: 0; }
.hero-row1 {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px;
}
.hero-title { margin: 0; font-size: 20px; font-weight: 700; color: var(--ink); letter-spacing: -0.02em; }
.status-badge {
  font-size: 11.5px; font-weight: 600; padding: 4px 10px;
  border-radius: var(--radius-full); background: rgba(255,255,255,0.9);
  border: 1px solid var(--line);
}
.status-badge.success { color: var(--success); }
.status-badge.warning { color: var(--warning); }
.status-badge.info { color: var(--muted); }
.status-switch { width: 108px; }
.hero-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.hero-pill {
  display: inline-flex; align-items: center; gap: 5px;
  background: var(--card); color: var(--ink-2);
  font-size: 12px; font-weight: 500;
  padding: 4px 10px; border-radius: var(--radius-full);
  border: 1px solid var(--line);
}

/* ── 地图 + 预算 ── */
.map-budget-row { display: grid; grid-template-columns: 1.6fr 1fr; gap: 16px; margin-bottom: 28px; }
.map-card, .budget-card {
  background: #fff; border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 18px; box-shadow: var(--shadow-card);
}
.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.card-title { font-size: 15px; font-weight: 600; color: var(--ink); }
.map-hint { font-size: 12px; color: var(--faint); }
.map-drag-error { margin-bottom: 10px; }
/* 地图聚焦态：activeDay 联动时品牌色描边提示 */
.map-card.day-focused {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft), var(--shadow-card);
}

.budget-ring-wrap { text-align: center; padding: 8px 0 4px; }
.budget-ring {
  --pct: 0;
  width: 120px; height: 120px; margin: 0 auto;
  border-radius: 50%;
  background: conic-gradient(var(--brand) calc(var(--pct) * 1%), var(--fill) 0);
  display: flex; align-items: center; justify-content: center;
}
.budget-ring-inner {
  width: 88px; height: 88px; border-radius: 50%; background: #fff;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
}
.ring-total { font-size: 17px; font-weight: 700; color: var(--ink); }
.ring-label { font-size: 11px; color: var(--faint); }
.ring-caption { font-size: 12px; color: var(--muted); margin-top: 6px; }

.budget-lines { margin-top: 12px; }
.budget-line { display: flex; align-items: center; gap: 8px; padding: 7px 0; font-size: 13px; color: var(--ink-2); }
.budget-dot { width: 8px; height: 8px; border-radius: 50%; }
.budget-line-val { margin-left: auto; font-weight: 600; color: var(--ink); }
.budget-line.total { border-top: 1px solid var(--line); margin-top: 4px; padding-top: 12px; font-weight: 600; }
.total-val { margin-left: auto; font-size: 17px; font-weight: 700; color: var(--brand); }
.budget-daily { margin-top: 10px; font-size: 12.5px; color: var(--success); display: inline-flex; align-items: center; gap: 4px; }
.budget-per-person { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--line); font-size: 12.5px; color: var(--ink-2); display: flex; align-items: center; gap: 4px; }
.budget-pp-sub { color: var(--muted); }
/* 预算估算口径（诚实估算标注） */
.budget-basis { display: flex; align-items: flex-start; gap: 6px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--line); font-size: 12px; color: var(--ink-2); line-height: 1.6; }
.budget-basis .el-icon { margin-top: 2px; flex-shrink: 0; }
.budget-basis-label { font-weight: 600; white-space: nowrap; color: var(--muted); }
.budget-basis-text { word-break: break-all; }

/* ── 双栏布局：主列（地图 + 每日行程）/ 侧栏（仪表盘 + 今日） ── */
.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
  margin-bottom: 20px;
}
.main-col { min-width: 0; }
.side-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: sticky;
  top: 76px; /* 顶部导航高度留白 */
}
.aux-area {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.aux-child { margin-bottom: 0; }

/* ── 段2 逐日行程卡（task-trip-detail-triptych）── */
.day-section.day-card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 16px 18px;
  margin-bottom: 14px;
  box-shadow: var(--shadow-sm);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.day-card.day-active {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft), var(--shadow-card);
}
.day-headline.clickable { cursor: pointer; border-radius: var(--radius-md); }
.day-headline.clickable:hover { background: var(--fill); }
.day-badge {
  width: 48px; height: 48px; border-radius: var(--radius-md); flex-shrink: 0;
  background: var(--ink); color: #fff; font-weight: 700; font-size: 13px;
  display: flex; align-items: center; justify-content: center;
  letter-spacing: 0.02em;
  transition: background 0.2s;
}
.day-badge.day-badge-active {
  background: var(--brand);
}
.day-focus-icon { color: var(--faint); margin-left: 6px; vertical-align: -2px; }
.day-card.day-active .day-focus-icon { color: var(--brand); }

/* ── 段3 工具箱分组（task-trip-detail-triptych）── */
.toolbox-group {
  margin-top: 22px;
  border-top: 1px dashed var(--line);
  padding-top: 14px;
}
.toolbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* 窄屏：双栏降级单列，侧栏顺序调整（仪表盘在每日行程后自然跟随） */
@media (max-width: 960px) {
  .detail-layout { grid-template-columns: 1fr; }
  .side-col { position: static; }
}

/* ── 时间校验卡片（TimeGate：营业时间/游玩时长提示） ── */
.timegate-card {
  margin-top: 4px; border: 1px solid var(--el-color-warning-light-7);
  background: var(--el-color-warning-light-9);
  border-radius: var(--radius-lg); padding: 12px 14px;
}
.timegate-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.timegate-title { font-size: 14px; font-weight: 600; color: var(--warning); display: inline-flex; align-items: center; }
.timegate-badge { font-size: 11px; color: var(--warning); background: var(--el-color-warning-light-7); border-radius: 999px; padding: 1px 8px; }
.timegate-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.timegate-item { display: flex; align-items: baseline; gap: 6px; font-size: 13px; color: var(--ink-2); }
.timegate-sev { flex-shrink: 0; font-size: 11px; color: var(--warning); background: var(--el-color-warning-light-8); border-radius: 4px; padding: 0 6px; }
.timegate-day { flex-shrink: 0; font-weight: 600; }
.timegate-msg { flex: 1; min-width: 0; }
.timegate-suggestion { color: var(--warning); font-size: 12px; }

/* ── AI 调整行程（方案 B） ── */
.revise-card {
  background: linear-gradient(135deg, var(--brand-soft), var(--card) 60%);
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  padding: 16px 20px;
  margin-bottom: 20px;
}
.revise-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.revise-title {
  font-size: 15px; font-weight: 600; color: var(--ink);
  display: inline-flex; align-items: center;
}
.revise-hint { font-size: 12px; color: var(--muted); }
.revise-row { display: flex; gap: 10px; }
.revise-loading {
  margin-top: 10px; font-size: 13px; color: var(--muted);
  display: inline-flex; align-items: center; gap: 6px;
}
.revise-error {
  margin-top: 10px; font-size: 13px; color: var(--warning);
  background: var(--el-color-warning-light-9); border: 1px solid var(--el-color-warning-light-7);
  border-radius: var(--radius-sm); padding: 8px 10px;
  display: flex; align-items: flex-start;
}
.revise-error .el-icon { flex-shrink: 0; color: var(--warning); margin-top: 2px; }
.revise-error-body { display: flex; flex-direction: column; gap: 2px; }
.revise-error-sub { font-size: 12px; color: var(--muted); }
.revise-summary {
  margin-top: 10px; font-size: 13px; color: var(--success);
  background: var(--el-color-success-light-9); padding: 8px 12px;
  border: 1px solid var(--el-color-success-light-7);
  border-radius: var(--radius-sm);
  display: inline-flex; align-items: center;
}
.revise-diff {
  margin-top: 10px; background: #fff; border: 1px solid var(--line);
  border-radius: var(--radius-md); padding: 10px 12px;
}
.revise-diff-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 8px;
}
.revise-diff-title { font-size: 13px; font-weight: 600; color: var(--ink); display: inline-flex; align-items: center; }
.revise-diff-count { font-size: 12px; color: var(--faint); }
.revise-diff-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: var(--radius-sm);
  font-size: 13px; color: var(--ink-2);
}
.revise-diff-item + .revise-diff-item { margin-top: 2px; }
.revise-diff-item.op-add { background: rgba(16,185,129,.07); }
.revise-diff-item.op-remove { background: rgba(239,68,68,.07); }
.revise-diff-item.op-replace { background: rgba(217,119,6,.08); }
.revise-diff-icon { font-size: 14px; flex-shrink: 0; }
.revise-diff-item.op-add .revise-diff-icon { color: var(--success); }
.revise-diff-item.op-remove .revise-diff-icon { color: var(--danger); }
.revise-diff-item.op-replace .revise-diff-icon { color: var(--warning); }
.revise-diff-text { line-height: 1.45; }
.revise-diff-empty {
  font-size: 12.5px; color: var(--faint);
  padding: 6px 8px; background: rgba(0,0,0,.02);
  border-radius: var(--radius-sm);
}
.revise-diff-more {
  margin-top: 6px; font-size: 12px; color: var(--faint);
  padding: 4px 8px; border-top: 1px dashed var(--line);
}
.detail-quality { margin-top: 4px; }

/* ── 行中「今日视图」（live 期间置顶卡片） ── */
.live-card {
  margin-bottom: 24px;
  border: 1.5px solid var(--brand);
  border-radius: var(--radius-lg);
  padding: 16px 18px;
  background: linear-gradient(180deg, var(--card), transparent);
  box-shadow: var(--shadow-sm);
}
.live-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.live-title { font-size: 16px; font-weight: 700; color: var(--ink); }
.live-sub { font-size: 12.5px; color: var(--muted); margin-top: 2px; }
.live-progress { display: flex; align-items: center; gap: 10px; }
.live-progress-num { font-size: 14px; font-weight: 700; color: var(--brand); }
.live-stops { display: flex; flex-direction: column; gap: 8px; }
.live-stop {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--card);
}
.live-stop.done { opacity: 0.6; }
.live-stop-info { flex: 1; min-width: 0; }
.live-stop-name { font-size: 14px; font-weight: 600; color: var(--ink); }
.live-stop-name.muted { text-decoration: line-through; color: var(--muted); }
.live-stop-type { font-size: 12px; color: var(--muted); margin-top: 2px; }
.live-stop-actions { flex-shrink: 0; }
.live-footer { margin-top: 14px; display: flex; justify-content: flex-end; }

/* 移动端（≤640px）：卡片压满、进度条换行 */
@media (max-width: 640px) {
  .live-head { flex-direction: column; align-items: flex-start; }
  .live-progress { width: 100%; justify-content: space-between; }
}

/* ── 每日行程 ── */
.day-section { margin-bottom: 24px; }
.day-head { display: flex; align-items: center; justify-content: space-between; margin: 0 0 14px; gap: 12px; }
.day-headline { display: flex; align-items: center; gap: 12px; }
.day-badge {
  width: 52px; height: 52px; border-radius: var(--radius-md); flex-shrink: 0;
  background: var(--ink); color: #fff; font-weight: 700; font-size: 13px;
  display: flex; align-items: center; justify-content: center;
  letter-spacing: 0.02em;
}
.day-title { font-size: 15px; font-weight: 600; color: var(--ink); }
.day-note { font-size: 12.5px; color: var(--muted); }
.day-actions { display: flex; gap: 8px; }

.stops-list { display: flex; flex-direction: column; }
.stop-item { display: flex; gap: 14px; }
.stop-rail { display: flex; flex-direction: column; align-items: center; width: 28px; flex-shrink: 0; }
.stop-index {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  color: #fff; font-size: 13px; font-weight: 600; z-index: 1;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 0 4px #fff;
}
.rail-line { flex: 1; width: 2px; background: var(--line); margin: 4px 0; }

.stop-body {
  flex: 1; min-width: 0; background: #fff;
  border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 14px 18px; margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
  transition: box-shadow .2s;
}
.stop-body:hover { box-shadow: var(--shadow-card); }
.stop-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.stop-name { font-size: 15px; font-weight: 600; color: var(--ink); }
.stop-meta { display: flex; gap: 14px; font-size: 12.5px; color: var(--muted); margin-top: 6px; align-items: center; }
.stop-meta .el-icon { font-size: 13px; color: var(--faint); }
.stop-desc { margin-top: 6px; font-size: 13px; color: var(--ink-2); line-height: 1.55; }
.stop-actions { margin-top: 6px; display: flex; justify-content: flex-end; }

/* ── 底部 ── */
.bottom-bar { display: flex; gap: 12px; margin-top: 20px; padding: 8px 0 20px; flex-wrap: wrap; }

.latlng { display: flex; gap: 8px; width: 100%; }

/* ── 备选方案对比（Plan B） ── */
.planb-card {
  background: linear-gradient(135deg, var(--brand-soft), var(--card) 60%);
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  padding: 14px 20px;
  margin-bottom: 20px;
}
.planb-head {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  flex-wrap: wrap;
}
.planb-title {
  font-size: 15px; font-weight: 600; color: var(--ink);
  display: inline-flex; align-items: center;
}
.planb-body { margin-top: 12px; }
.planb-meta { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.planb-label {
  font-size: 13px; font-weight: 700; color: var(--brand);
  background: var(--brand-soft); padding: 3px 10px; border-radius: var(--radius-full);
}
.planb-desc { font-size: 13px; color: var(--ink-2); }
.planb-deltas {
  margin-top: 10px; background: #fff; border: 1px solid var(--line);
  border-radius: var(--radius-md); padding: 8px 12px;
}
.planb-delta {
  display: flex; align-items: flex-start; gap: 4px;
  font-size: 13px; color: var(--ink-2); line-height: 1.5; padding: 4px 0;
}
.planb-delta .el-icon { flex-shrink: 0; margin-top: 3px; }
.planb-budget {
  margin-top: 10px; font-size: 13px; color: var(--ink); font-weight: 600;
  display: inline-flex; align-items: center;
}
.planb-budget-sub {
  margin-left: 10px; font-weight: 500; color: var(--muted);
}
.planb-hint { margin-top: 8px; font-size: 12px; color: var(--faint); }

/* ── 分享设置弹窗（生命周期：TTL / 吊销 / 审计） ── */
.share-settings-hint { font-size: 13px; color: var(--muted); margin-bottom: 14px; }
.share-settings-body { min-height: 80px; }
.share-settings-empty { text-align: center; color: var(--faint); padding: 24px 0; }
.share-setting-card {
  border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 14px 16px; margin-bottom: 12px; background: #fff;
}
.share-setting-card.revoked { opacity: 0.65; background: #fafafa; }
.ss-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.ss-kind { font-size: 14px; font-weight: 600; color: var(--ink); }
.ss-row {
  display: flex; align-items: center; gap: 10px;
  font-size: 13px; color: var(--ink-2); padding: 5px 0;
  flex-wrap: wrap;
}
.ss-label { color: var(--faint); flex-shrink: 0; min-width: 64px; }
.ss-value { flex: 1; min-width: 0; word-break: break-all; }
.ss-url { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--brand); }
.ss-actions { margin-top: 6px; display: flex; justify-content: flex-end; }

/* 响应式 */
@media (max-width: 860px) {
  .hero-cover { height: 160px; }
  .hero-overlay { padding: 24px; }
  .hero-title { font-size: 24px; }
}

/* ── 移动端（≤640px）断点适配（task-mobile-views）：375px 可用、可滚动、无水平滚动 ── */
@media (max-width: 640px) {
  .detail-page { padding: 0 12px; }
  /* 顶栏：返回按钮与操作区分行，操作按钮换行不溢出；触控目标 ≥40px */
  .topbar { flex-direction: column; align-items: stretch; gap: 8px; }
  .topbar-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
  .topbar-actions :deep(.el-button) { margin-left: 0; min-height: 40px; }
  /* 头图：垂直堆叠（标题区 + 底部状态区），状态不再绝对定位重叠标题 */
  .hero-cover { height: auto; min-height: 150px; flex-direction: column; align-items: stretch; }
  /* 移动端：min-height 150px，字形 100px×1.4=140px，bottom 正值完整容纳 */
  .hero-city { font-size: 100px; bottom: 20px; }
  .hero-overlay { padding: 20px 16px 12px; }
  .hero-title { font-size: 20px; margin-bottom: 10px; }
  .hero-pill { font-size: 11.5px; padding: 5px 10px; }
  .status-group { position: static; order: 2; display: flex; justify-content: flex-end; gap: 6px; padding: 8px 12px 12px; }
  /* 卡片内边距收窄 */
  .map-card, .budget-card { padding: 14px; }
  .map-hint { font-size: 11px; }
  /* AI 调整区：输入与按钮纵向堆叠，按钮全宽 + 44px 触控 */
  .revise-card { padding: 14px; }
  .revise-row { flex-direction: column; gap: 8px; }
  .revise-row :deep(.el-button) { width: 100%; margin-left: 0; min-height: 44px; }
  /* 每日行程：日期头纵向 + 操作右对齐换行；徽章缩小 */
  .day-head { flex-direction: column; align-items: stretch; gap: 8px; }
  .day-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; }
  .day-actions :deep(.el-button) { margin-left: 0; min-height: 40px; }
  .day-badge { width: 44px; height: 44px; font-size: 12px; }
  .day-headline { gap: 10px; }
  .stop-body { padding: 12px 14px; }
  .stop-actions { flex-wrap: wrap; }
  .stop-actions :deep(.el-button) { min-height: 40px; }
  /* 底部操作：2 列网格 + 44px 触控目标；导出 split 占整行 */
  .bottom-bar { gap: 8px; }
  .bottom-bar > :deep(.el-button) { flex: 1 1 calc(50% - 4px); margin-left: 0; min-height: 44px; }
  .bottom-bar > :deep(.el-dropdown) { flex: 1 1 100%; }
  .bottom-bar > :deep(.el-dropdown) :deep(.el-button-group) { width: 100%; }
  /* 编辑对话框：经纬度输入纵向（对话框已由全局断点收窄） */
  .latlng { flex-direction: column; }
}

/* ── 打印样式（task-export-offline：浏览器打印 → 存 PDF） ──
 * 只打印导出区（头图/概览/地图/预算/每日行程），隐藏操作控件与交互区；
 * 打印走浏览器原生分页（无需 html2canvas 长图裁切）。 */
@media print {
  .topbar, .bottom-bar, .revise-card, .day-actions, .stop-actions,
  .map-hint, .status-switch, .map-drag-error,
  .share-settings-hint, .share-settings-body, .gen-days-hint,
  .el-dialog__wrapper, .el-overlay,
  .trip-servicing, .packing-list, .trip-event-feed, .quality-card {
    display: none !important;
  }
  .detail-page { padding: 0; }
  .hero-cover { height: auto !important; min-height: 0 !important; }
  .hero-city { display: none; }
  .map-card { max-height: 320px; overflow: hidden; }
  /* 避免叶子节点/分页处截断 */
  .day-card, .stop-item { break-inside: avoid; }
  .export-area { border: none; }
}
</style>