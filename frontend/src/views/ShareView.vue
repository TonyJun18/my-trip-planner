<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api'
import { readCachedJson, isOnline } from '@/utils/pwa'
import TripMap from '@/components/TripMap.vue'

const route = useRoute()
const { t } = useI18n()
const loading = ref(false)
const error = ref('')
const trip = ref(null)
// PWA 离线降级：网络失败时从 Cache API 读分享缓存（SW 的 api 缓存），仅展示缓存快照
const offlineFallback = ref(false)
// 离线恢复：online 事件回来且当前展示的是缓存快照 → 自动重新拉取并清除标识
function handleOnline() {
  if (offlineFallback.value) load()
}

// ── 受邀编辑模式：URL 带 ?edit=1（owner 生成的 edit_url）→ 用 edit_token 访问 ──
const editMode = computed(() => route.query.edit === '1')
// 行内编辑缓冲：stop_id -> { name, description }
const editingStop = ref(null)
const editBuf = ref({ name: '', description: '' })
const savingStop = ref(false)

// ── 分享页协作：评论 ──
const comments = ref([])
const commentLoading = ref(false)
const commentName = ref('')
const commentText = ref('')
const commentSubmitting = ref(false)

// ── 分享页协作：站点投票 ──
const votes = ref({}) // stop_id -> { up, down, my_value? }
const voting = ref({}) // stop_id -> true（提交中防抖）

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const markers = computed(() => {
  const list = []
  for (const day of trip.value?.days || []) {
    for (const stop of day.stops || []) {
      if (stop.lat != null && stop.lng != null) {
        list.push({ lat: stop.lat, lng: stop.lng, name: stop.name, stop_type: stop.stop_type, description: stop.description, day_number: day.day_number, stop_id: stop.id })
      }
    }
  }
  return list
})

// ── 地图拖拽修订（task-map-drag-edit 前端接线 · 分享页） ──────
// 拖拽能力随受邀编辑权开放：分享页非 editMode 只读（不发请求）；
// editMode 下拖拽 → POST /map-edit → 整体刷新（markers 派生自 trip，
// 引用替换触发 TripMap watch 重绘回正）。失败回弹由后端 4xx + 刷新保证。
const mapMoving = ref(false)
async function onMapMove(payload) {
  if (!editMode.value || mapMoving.value || !trip.value) return
  mapMoving.value = true
  try {
    // 受邀编辑模式：凭 edit_token 免登录调 map-edit（与受邀编辑 stop 更新同链路）
    const r = await api.mapEditInvitedTrip(route.params.token, {
      name: payload.name,
      lat: payload.lat,
      lng: payload.lng,
      day_number: payload.day_number ?? null,
    })
    await load()
    if (r?.summary) ElMessage.success(r.summary)
    if (r?.driving?.critical_count) {
      ElMessage.warning(
        t('tripDetail.mapEditDrivingWarn', {
          count: r.driving.critical_count,
        }),
      )
    }
  } catch {
    // 4xx（自驾约束门/令牌失效等）拦截器已 toast；刷新保证服务端状态一致
    await load()
  } finally {
    mapMoving.value = false
  }
}

const statusMap = computed(() => ({
  draft: { label: t('tripList.statusDraft'), type: 'info' },
  planning: { label: t('tripList.statusPlanning'), type: 'warning' },
  confirmed: { label: t('tripList.statusConfirmed'), type: 'success' },
  archived: { label: t('tripList.statusArchived'), type: 'info' },
}))

const typeLabel = computed(() => ({
  attraction: t('common.typeAttraction'),
  food: t('common.typeFood'),
  hotel: t('common.typeHotel'),
  transport: t('common.typeTransport'),
}))
const typeColor = { attraction: 'var(--brand)', food: '#c2410c', hotel: '#0d8a5f', transport: '#5b6ee1' }
const typeEmoji = { attraction: '🏞️', food: '🍜', hotel: '🏨', transport: '🚄' }

// ── 预算：公开分享接口（GET /trips/share/{token}）返回 budget_summary 汇总，无需本地重复计算 ──
const budget = computed(() => trip.value?.budget_summary || null)

const budgetPercent = computed(() => {
  if (!budget.value?.total_estimated || !trip.value?.budget) return null
  return Math.min(100, Math.round((budget.value.total_estimated / trip.value.budget) * 100))
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    try {
      trip.value = editMode.value
        ? await api.getEditableTrip(route.params.token)
        : await api.getSharedTrip(route.params.token)
      offlineFallback.value = false // 在线成功：清除离线标识
    } catch (e) {
      // 离线/网络失败：尝试从 Cache API 读分享缓存（SW 缓存 share/edit 读取），读不到再上抛
      const key = editMode.value ? `/api/v1/trips/edit/${route.params.token}` : `/api/v1/trips/share/${route.params.token}`
      const cached = await readCachedJson(key)
      if (cached) {
        trip.value = cached
        offlineFallback.value = true
      } else {
        // 无缓存可降级：向用户明示（无缓存 ≠ 静默失败）
        if (!isOnline()) {
          ElMessage.warning(t('share.offlineNoCache'))
        }
        throw e
      }
    }
    // 离线降级：跳过协作接口（评论/投票离线语义无意义，且避免连续弹错）
    if (offlineFallback.value) {
      comments.value = []
      votes.value = {}
      return
    }
    await Promise.all([loadComments(), loadVotes()])
    // 行中「今日视图」+ WS feed（仅受邀编辑模式；只读分享无操作权限）
    if (editMode.value) {
      await loadLive()
    }
    watchCollabFeed()
  } catch (e) {
    error.value = editMode.value ? t('share.editLinkInvalid') : t('share.linkInvalid')
  } finally {
    loading.value = false
  }
}

// ── 协作加载 / 提交 ──
async function loadComments() {
  commentLoading.value = true
  try {
    comments.value = await api.getSharedTripComments(route.params.token)
  } catch (e) {
    comments.value = []
  } finally {
    commentLoading.value = false
  }
}

async function loadVotes() {
  try {
    votes.value = await api.getSharedTripVotes(route.params.token)
  } catch (e) {
    votes.value = {}
  }
}

async function submitComment() {
  const content = commentText.value.trim()
  if (!content || commentSubmitting.value) return
  commentSubmitting.value = true
  try {
    const created = await api.postSharedTripComment(route.params.token, {
      author_name: commentName.value.trim() || null,
      content,
    })
    comments.value.push(created)
    commentText.value = ''
  } catch (e) {
    // 拦截器已弹出错误提示
  } finally {
    commentSubmitting.value = false
  }
}

async function castVote(stopId, value) {
  if (voting.value[stopId]) return
  voting.value[stopId] = true
  try {
    const result = await api.castSharedTripVote(route.params.token, stopId, value)
    votes.value[stopId] = result
  } catch (e) {
    // 拦截器已弹出错误提示
  } finally {
    voting.value[stopId] = false
  }
}

function voteCount(stopId, kind) {
  return votes.value?.[stopId]?.[kind] || 0
}

function myVote(stopId) {
  return votes.value?.[stopId]?.my_value || 0
}

// ── 预算估算口径：estimate_basis（hotel: 城市基准价静态估算 / transport: 采集参考价×2）──
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

// 渐进式共识：后端 list_stop_votes 已计算 consensus（过半成员表态且赞成多于反对）
function hasConsensus(stopId) {
  return !!votes.value?.[stopId]?.consensus
}

// ── 受邀编辑（editMode）：勾选 / 行内改名备注 / 上移下移顺序 ──
async function toggleChecked(stop) {
  try {
    const updated = await api.updateInvitedStop(route.params.token, stop.id, { checked: !stop.checked })
    stop.checked = updated.checked
  } catch (e) {
    // 拦截器已 toast（如链接已收回）
  }
}
function startEditStop(stop) {
  editingStop.value = stop.id
  editBuf.value = { name: stop.name || '', description: stop.description || '' }
}
function cancelEditStop() {
  editingStop.value = null
  editBuf.value = { name: '', description: '' }
}
async function saveEditStop(stop) {
  const name = (editBuf.value.name || '').trim()
  if (!name) {
    ElMessage.warning(t('share.nameRequired'))
    return
  }
  savingStop.value = true
  try {
    const updated = await api.updateInvitedStop(route.params.token, stop.id, {
      name,
      description: (editBuf.value.description || '').trim() || null,
    })
    stop.name = updated.name
    stop.description = updated.description
    editingStop.value = null
  } catch (e) {
    // 拦截器已 toast
  } finally {
    savingStop.value = false
  }
}
async function moveStop(day, stop, dir) {
  const stops = day.stops
  const idx = stops.findIndex((s) => s.id === stop.id)
  const target = idx + dir
  if (idx < 0 || target < 0 || target >= stops.length) return
  const order = stops.map((s) => s.id)
  ;[order[idx], order[target]] = [order[target], order[idx]]
  try {
    // 用服务端返回的新顺序更新本地（避免整页重载闪烁）
    day.stops = await api.reorderInvitedStops(route.params.token, day.id, order)
  } catch (e) {
    // 拦截器已 toast（如链接已收回）
  }
}

onMounted(() => {
  load()
  window.addEventListener('online', handleOnline)
})
onBeforeUnmount(() => {
  window.removeEventListener('online', handleOnline)
  if (collabClose) {
    collabClose()
    collabClose = null
  }
})

// ── 行中「今日视图」受邀编辑版（免登录，凭 edit_token；同伴打卡/顺延） ──
// 只读分享模式（!editMode）不展示行中卡片：无操作权限，且编辑令牌才是协作语义。
const live = ref(null)
const liveLoading = ref(false)
const liveOp = ref('') // 正在执行的行中操作，防重复点击
let collabClose = null

async function loadLive() {
  if (!editMode.value || offlineFallback.value || !route.params.token) return
  liveLoading.value = true
  try {
    live.value = await api.getLiveSnapshotByToken(route.params.token)
  } catch {
    live.value = null // 失败不打扰只读浏览
  } finally {
    liveLoading.value = false
  }
}

async function doCheckLiveStop(stop, checked) {
  if (liveOp.value || !editMode.value) return
  liveOp.value = 'check'
  try {
    live.value = await api.checkLiveStopByToken(route.params.token, stop.id, checked)
  } catch {
    // 拦截器已 toast（如链接已收回）
  } finally {
    liveOp.value = ''
  }
}

async function doSkipLiveStop(stop) {
  if (liveOp.value || !editMode.value) return
  try {
    await ElMessageBox.confirm(
      t('share.liveSkipConfirmMsg', { name: stop.name }),
      t('share.liveSkipConfirmTitle'),
      { type: 'warning' }
    )
  } catch { return }
  liveOp.value = 'skip'
  try {
    live.value = await api.skipLiveStopByToken(route.params.token, stop.id)
    await load()
  } catch {
  } finally {
    liveOp.value = ''
  }
}

async function doDelayLiveTrip() {
  if (liveOp.value || !editMode.value) return
  try {
    await ElMessageBox.confirm(
      t('share.liveDelayConfirmMsg'),
      t('share.liveDelayConfirmTitle'),
      { type: 'warning' }
    )
  } catch { return }
  liveOp.value = 'delay'
  try {
    live.value = await api.delayLiveTripByToken(route.params.token)
    await load()
    ElMessage.success(t('share.liveDelayed'))
  } catch {
  } finally {
    liveOp.value = ''
  }
}

// WS feed：同伴打卡/顺延实时刷新今日卡片（免登录 token 鉴权）
function watchCollabFeed() {
  if (!editMode.value || !trip.value?.id || collabClose) return
  collabClose = api.subscribeTripCollab(trip.value.id, {
    token: route.params.token,
    edit: true,
    onEvent: (evt) => {
      const type = evt?.type || ''
      if (type.startsWith('stop.') || type === 'trip.delayed') {
        loadLive()
      }
    },
  })
}
</script>

<template>
  <div v-loading="loading" class="share-page">
    <!-- 提示条：只读 or 受邀编辑 -->
    <div class="share-banner" :class="{ edit: editMode }">
      <el-icon style="margin-right: 6px"><component :is="editMode ? 'EditPen' : 'View'" /></el-icon>
      <span v-if="!editMode">{{ $t('share.readonlyBanner') }}</span>
      <span v-else>{{ $t('share.editBanner') }}</span>
    </div>

    <div v-if="error" class="share-error">
      <el-result icon="warning" :title="error">
        <template #extra>
          <span class="share-error-hint">{{ $t('share.errorHint') }}</span>
        </template>
      </el-result>
    </div>

    <!-- 离线模式标识（PWA：网络失败时读缓存展示，联网自动恢复） -->
    <el-alert
      v-if="offlineFallback"
      class="offline-banner"
      type="warning"
      :closable="false"
      show-icon
    >
      <template #title>
        {{ $t('share.offlineMode') }} · {{ $t('share.offlineModeHint') }}
      </template>
    </el-alert>

    <template v-else-if="trip">
      <!-- 头图 + 概览 -->
      <div class="hero-card">
        <div class="hero-cover">
          <div class="hero-city">{{ (trip.destination || '?')[0] }}</div>
          <div class="hero-overlay">
            <h1 class="hero-title">{{ trip.title }}</h1>
            <div class="hero-meta">
              <span class="hero-pill"><el-icon><Location /></el-icon>{{ trip.destination }}</span>
              <span class="hero-pill"><el-icon><Calendar /></el-icon>{{ trip.start_date }} ~ {{ trip.end_date }}</span>
              <span class="hero-pill"><el-icon><User /></el-icon>{{ trip.travelers }} {{ $t('common.peopleUnit') }}</span>
              <span class="hero-pill" v-if="trip.budget != null"><el-icon><Wallet /></el-icon>{{ $t('common.budget') }} ¥{{ trip.budget }}</span>
            </div>
          </div>
          <span class="status-badge" :class="(statusMap[trip.status] || statusMap.draft).type">
            {{ (statusMap[trip.status] || statusMap.draft).label }}
          </span>
        </div>
      </div>

      <!-- 地图 + 预算 -->
      <div class="map-budget-row">
        <div class="map-card">
          <div class="card-head">
            <span class="card-title">{{ $t('common.mapTitle') }}</span>
            <span class="map-hint">{{ $t('common.mapHint') }}</span>
          </div>
          <TripMap :markers="markers" height="420px" :draggable="editMode" :on-move="onMapMove" />
        </div>
        <div class="budget-card">
          <div class="card-head"><span class="card-title">{{ $t('common.budgetTitle') }}</span></div>
          <template v-if="budget">
            <div class="budget-ring-wrap">
              <div class="budget-ring" :style="{ '--pct': budgetPercent != null ? budgetPercent : 0 }">
                <div class="budget-ring-inner">
                  <div class="ring-total">¥{{ budget.total_estimated }}</div>
                  <div class="ring-label">{{ $t('common.estimated') }}</div>
                </div>
              </div>
              <div class="ring-caption" v-if="budgetPercent != null">
                {{ $t('common.percentOfBudget', { pct: budgetPercent }) }}
              </div>
            </div>
            <div class="budget-lines">
              <div v-for="(label, k) in { attraction: $t('common.typeAttraction'), food: $t('common.typeFood'), hotel: $t('common.typeHotel'), transport: $t('common.typeTransport') }" :key="k" class="budget-line">
                <span class="budget-dot" :style="{ background: typeColor[k] }" />
                <span>{{ label }}</span>
                <span class="budget-line-val">¥{{ budget.by_type?.[k] || 0 }}</span>
              </div>
              <div class="budget-line total">
                <span>{{ $t('common.total') }}</span>
                <span class="total-val">¥{{ budget.total_estimated }}</span>
              </div>
            </div>
            <div class="budget-daily" v-if="budget.daily_average">
              <el-icon><TrendCharts /></el-icon> {{ $t('common.dailyAvg', { amount: budget.daily_average }) }}
            </div>
            <!-- 人均分摊（task-budget-split：多人出行按 travelers 分摊） -->
            <div v-if="budget.per_person_total != null && trip.travelers > 1" class="budget-per-person">
              <el-icon><User /></el-icon>
              {{ $t('common.perPersonLabel') }} {{ $t('common.perPersonTotal', { amount: budget.per_person_total }) }}
              <span v-if="budget.per_person_daily != null" class="budget-pp-sub">
                · {{ $t('common.perPersonDaily', { amount: budget.per_person_daily }) }}
              </span>
            </div>
            <!-- 预算估算口径（诚实估算：来源 + 基准说明，对齐「预算必须可审计」哲学） -->
            <div v-if="basisText" class="budget-basis">
              <el-icon><InfoFilled /></el-icon>
              <span class="budget-basis-label">{{ $t('share.basisLabel') }}</span>
              <span class="budget-basis-text">{{ basisText }}</span>
            </div>
          </template>
          <el-empty v-else :description="$t('common.noBudget')" :image-size="60" />
        </div>
      </div>

      <!-- 行中「今日视图」（受邀编辑模式：同伴打卡/跳过/迟到顺延，免登录） -->
      <div v-if="editMode && live && live.phase === 'live'" class="live-card">
        <div class="live-head">
          <div>
            <div class="live-title">📅 {{ $t('share.liveTodayTitle') }}</div>
            <div class="live-sub">{{ $t('share.liveTodaySub', { day: live.day_number, date: live.date }) }}</div>
          </div>
          <div class="live-progress">
            <span class="live-progress-num">{{ live.completed }}/{{ live.total }}</span>
            <el-progress :percentage="live.total ? Math.round(live.completed / live.total * 100) : 0"
                         :stroke-width="6" :show-text="false" style="width: 90px" />
          </div>
        </div>

        <div class="live-stops">
          <div v-for="stop in live.stops" :key="stop.id" class="live-stop" :class="{ done: stop.checked }">
            <el-checkbox :model-value="stop.checked"
                         :disabled="!!liveOp"
                         @change="(v) => doCheckLiveStop(stop, v)" />
            <div class="live-stop-info">
              <div class="live-stop-name" :class="{ muted: stop.checked }">{{ stop.name }}</div>
              <div class="live-stop-type">{{ typeEmoji[stop.stop_type] }} {{ typeLabel[stop.stop_type] || stop.stop_type }}</div>
            </div>
            <div class="live-stop-actions">
              <el-button size="small" text type="danger" :disabled="!!liveOp"
                         @click="doSkipLiveStop(stop)">{{ $t('share.liveSkip') }}</el-button>
            </div>
          </div>
        </div>

        <div class="live-footer">
          <el-button size="small" type="warning" plain :loading="liveOp === 'delay'"
                     @click="doDelayLiveTrip">{{ $t('share.liveDelay') }}</el-button>
        </div>
      </div>

      <!-- 每日行程 -->
      <div class="day-section" v-for="day in trip.days" :key="day.id">
        <div class="day-head">
          <div class="day-headline">
            <span class="day-badge">Day {{ day.day_number }}</span>
            <div>
              <div class="day-title">{{ day.date || $t('common.dayN', { n: day.day_number }) }}</div>
              <div class="day-note">{{ day.note || $t('common.freeExplore') }}</div>
            </div>
          </div>
        </div>

        <!-- 站点时间轴 -->
        <div class="stops-list" v-if="day.stops.length">
          <div v-for="(stop, idx) in day.stops" :key="stop.id" class="stop-item" :class="{ checked: stop.checked }">
            <div class="stop-rail">
              <span class="stop-index" :style="{ background: typeColor[stop.stop_type] || 'var(--brand)' }">{{ idx + 1 }}</span>
              <span class="rail-line" v-if="idx < day.stops.length - 1" />
            </div>
            <div class="stop-body">
              <div class="stop-head">
                <span class="stop-name">
                  <!-- 受邀编辑：勾选 + 行内编辑名称 -->
                  <el-checkbox
                    v-if="editMode"
                    :model-value="!!stop.checked"
                    @change="toggleChecked(stop)"
                    style="margin-right: 6px"
                  />
                  <template v-if="editMode && editingStop === stop.id">
                    <el-input v-model="editBuf.name" size="small" maxlength="200" class="inline-edit-name" />
                  </template>
                  <template v-else>{{ stop.name }}</template>
                </span>
                <el-tag size="small" round :style="{ color: typeColor[stop.stop_type] || 'var(--brand)', background: (typeColor[stop.stop_type] || 'var(--brand)') + '1a', border: 'none' }">
                  {{ typeEmoji[stop.stop_type] }} {{ typeLabel[stop.stop_type] || stop.stop_type }}
                </el-tag>
              </div>
              <div class="stop-meta">
                <span v-if="stop.estimated_cost != null"><el-icon><Wallet /></el-icon>¥{{ stop.estimated_cost }}</span>
                <span v-if="stop.estimated_duration_minutes"><el-icon><Clock /></el-icon>{{ stop.estimated_duration_minutes }} {{ $t('common.minutes') }}</span>
                <span v-if="!editMode" class="vote-group">
                  <span v-if="votes[stop.id]?.consensus" class="consensus-badge" :title="$t('share.consensusTip')">✅ {{ $t('share.consensus') }}</span>
                  <button
                    class="vote-btn"
                    :class="{ active: myVote(stop.id) === 1 }"
                    :disabled="voting[stop.id]"
                    @click="castVote(stop.id, 1)"
                    :title="$t('share.wantGo')"
                  >👍 {{ voteCount(stop.id, 'up') }}</button>
                  <button
                    class="vote-btn"
                    :class="{ active: myVote(stop.id) === -1 }"
                    :disabled="voting[stop.id]"
                    @click="castVote(stop.id, -1)"
                    :title="$t('share.notGo')"
                  >👎 {{ voteCount(stop.id, 'down') }}</button>
                  <!-- 渐进式共识徽标：过半成员表态且赞成多于反对 →「小组一致」 -->
                  <span v-if="hasConsensus(stop.id)" class="consensus-badge" :title="$t('share.consensusTip')">
                    <el-icon style="margin-right: 2px"><CircleCheck /></el-icon>{{ $t('share.consensus') }}
                  </span>
                </span>
                <!-- 受邀编辑：行内编辑 + 上移下移 -->
                <span v-else class="edit-group">
                  <template v-if="editingStop === stop.id">
                    <el-button size="small" type="primary" text :loading="savingStop" @click="saveEditStop(stop)">{{ $t('common.save') }}</el-button>
                    <el-button size="small" text @click="cancelEditStop">{{ $t('common.cancel') }}</el-button>
                  </template>
                  <template v-else>
                    <el-button size="small" text @click="startEditStop(stop)">{{ $t('share.editNameNote') }}</el-button>
                  </template>
                  <el-button size="small" text :disabled="idx === 0" @click="moveStop(day, stop, -1)">↑</el-button>
                  <el-button size="small" text :disabled="idx >= day.stops.length - 1" @click="moveStop(day, stop, 1)">↓</el-button>
                </span>
              </div>
              <!-- 受邀编辑：行内编辑备注文本域 -->
              <div v-if="editMode && editingStop === stop.id" class="stop-desc">
                <el-input
                  v-model="editBuf.description"
                  type="textarea"
                  :rows="2"
                  maxlength="2000"
                  :placeholder="$t('share.notePh')"
                />
              </div>
              <div v-else-if="stop.description" class="stop-desc">{{ stop.description }}</div>
            </div>
          </div>
        </div>
        <el-empty v-else :description="$t('common.dayEmpty')" :image-size="60" />
      </div>

      <!-- 分享页协作：评论区（免登录，凭分享链接） -->
      <div class="comments-card">
        <div class="card-head">
          <span class="card-title">{{ $t('share.comments') }}</span>
          <span class="map-hint">{{ $t('share.commentsHint') }}</span>
        </div>

        <div v-if="comments.length" class="comment-list">
          <div v-for="c in comments" :key="c.id" class="comment-item">
            <div class="comment-avatar">{{ (c.author_name || $t('share.anon'))[0] }}</div>
            <div class="comment-main">
              <div class="comment-head">
                <span class="comment-name">{{ c.author_name || $t('share.anonGuest') }}</span>
                <span class="comment-time">{{ fmtTime(c.created_at) }}</span>
              </div>
              <div class="comment-text">{{ c.content }}</div>
            </div>
          </div>
        </div>
        <el-empty v-else-if="!commentLoading" :description="$t('share.noComments')" :image-size="50" />

        <div class="comment-composer">
          <el-input v-model="commentName" :placeholder="$t('share.namePh')" class="comment-name-input" maxlength="50" clearable />
          <el-input
            v-model="commentText"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            :placeholder="$t('share.commentPh')"
          />
          <div class="comment-actions">
            <el-button type="primary" :loading="commentSubmitting" :disabled="!commentText.trim()" @click="submitComment">
              {{ $t('share.postComment') }}
            </el-button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
<style scoped>
.share-page { max-width: 1080px; margin: 0 auto; padding-top: 8px; }

/* PWA 离线模式标识（task-pwa-cache-deep） */
.offline-banner { margin-bottom: 16px; }

.share-banner {
  display: flex; align-items: center;
  background: var(--brand-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 10px 16px; margin-bottom: 18px;
  font-size: 13px; color: var(--ink-2);
}
.share-banner.edit {
  background: #fff7e6;
  border-color: #f5c97b;
  color: #8a5a00;
}
/* 受邀编辑：勾选后的站点置灰 */
.stop-item.checked .stop-body { opacity: 0.62; }
.stop-item.checked .stop-name { text-decoration: line-through; }
.inline-edit-name { width: 220px; display: inline-flex; vertical-align: middle; }
.edit-group { margin-left: auto; display: inline-flex; align-items: center; gap: 2px; }

.share-error { padding: 40px 0; }
.share-error-hint { color: var(--faint); font-size: 13px; }

/* ── 头图 ── */
.hero-card { margin-bottom: 20px; }
.hero-cover {
  position: relative;
  height: 200px;
  border-radius: var(--radius-xl);
  background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 55%, #a1c4fd 100%);
  overflow: hidden;
  display: flex; align-items: center;
  box-shadow: var(--shadow-card);
}
.hero-city {
  position: absolute; right: 6%; bottom: -36px;
  font-size: 210px; font-weight: 800; color: rgba(255,255,255,0.35);
  line-height: 1; user-select: none;
}
.hero-overlay { position: relative; z-index: 1; padding: 32px 36px; }
.hero-title { margin: 0 0 14px; font-size: 30px; font-weight: 700; color: #fff; text-shadow: 0 2px 14px rgba(0,0,0,0.18); letter-spacing: -0.02em; }
.hero-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.hero-pill {
  display: inline-flex; align-items: center; gap: 5px;
  background: rgba(255,255,255,0.88); color: var(--ink-2);
  font-size: 12.5px; font-weight: 500;
  padding: 6px 12px; border-radius: var(--radius-full);
  backdrop-filter: blur(4px);
}
.status-badge {
  position: absolute; top: 16px; right: 16px; z-index: 2;
  font-size: 12px; font-weight: 600; padding: 5px 12px;
  border-radius: var(--radius-full); background: rgba(255,255,255,0.9);
}
.status-badge.success { color: var(--success); }
.status-badge.warning { color: var(--warning); }
.status-badge.info { color: var(--muted); }

/* ── 地图 + 预算 ── */
.map-budget-row { display: grid; grid-template-columns: 1.6fr 1fr; gap: 16px; margin-bottom: 28px; }
.map-card, .budget-card {
  background: #fff; border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 18px; box-shadow: var(--shadow-card);
}
.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.card-title { font-size: 15px; font-weight: 600; color: var(--ink); }
.map-hint { font-size: 12px; color: var(--faint); }

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

.detail-quality { margin-top: 4px; }

/* ── 行中「今日视图」（受邀编辑模式：同伴打卡/跳过/迟到顺延） ── */
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

/* ── 站点投票 ── */
.vote-group { margin-left: auto; display: inline-flex; gap: 6px; }
.consensus-badge {
  display: inline-flex; align-items: center; gap: 2px;
  background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0;
  border-radius: var(--radius-full); padding: 2px 10px; font-size: 12px;
  font-weight: 600; cursor: default;
}
.vote-btn {
  appearance: none; border: 1px solid var(--line); background: #fff;
  border-radius: var(--radius-full); padding: 3px 10px; font-size: 12.5px;
  color: var(--ink-2); cursor: pointer; transition: all .15s;
  line-height: 1.4;
}
.vote-btn:hover:not(:disabled) { border-color: var(--brand); color: var(--brand); }
.vote-btn.active { background: var(--brand-soft); border-color: var(--brand); color: var(--brand); font-weight: 600; }
.vote-btn:disabled { opacity: .55; cursor: default; }
/* 渐进式共识徽标：过半成员表态且赞成多于反对 */
.consensus-badge {
  display: inline-flex; align-items: center; gap: 2px;
  font-size: 12px; font-weight: 600;
  color: var(--success, #16a34a);
  background: color-mix(in srgb, var(--success, #16a34a) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--success, #16a34a) 35%, transparent);
  border-radius: 10px; padding: 1px 8px;
  line-height: 1.6; white-space: nowrap;
}
/* 预算估算口径（诚实估算标注） */
.budget-basis {
  display: flex; align-items: flex-start; gap: 6px;
  margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border, #e5e7eb);
  font-size: 12px; color: var(--ink-2, #6b7280); line-height: 1.6;
}
.budget-basis .el-icon { margin-top: 2px; flex-shrink: 0; }
.budget-basis-label { font-weight: 600; white-space: nowrap; color: var(--ink-3, #9ca3af); }
.budget-basis-text { word-break: break-all; }

/* ── 分享页协作评论 ── */
.comments-card {
  background: #fff; border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 18px; box-shadow: var(--shadow-card); margin-bottom: 24px;
}
.comment-list { display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px; }
.comment-item { display: flex; gap: 10px; }
.comment-avatar {
  width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
  background: var(--brand-soft); color: var(--brand); font-size: 13px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.comment-main { flex: 1; min-width: 0; }
.comment-head { display: flex; align-items: baseline; gap: 8px; }
.comment-name { font-size: 13px; font-weight: 600; color: var(--ink); }
.comment-time { font-size: 11.5px; color: var(--faint); }
.comment-text {
  margin-top: 3px; font-size: 13.5px; color: var(--ink-2); line-height: 1.55;
  white-space: pre-wrap; word-break: break-word;
}
.comment-composer { border-top: 1px dashed var(--line); padding-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.comment-name-input { max-width: 220px; }
.comment-actions { display: flex; justify-content: flex-end; }

/* 响应式 */
@media (max-width: 860px) {
  .map-budget-row { grid-template-columns: 1fr; }
  .hero-cover { height: 160px; }
  .hero-overlay { padding: 24px; }
  .hero-title { font-size: 24px; }
}

/* ── 移动端（≤640px）断点适配（task-mobile-views）：分享/受邀编辑 375px 可用、无水平滚动 ── */
@media (max-width: 640px) {
  .share-page { padding: 6px 12px 0; }
  /* 头图：垂直堆叠，状态徽标落到内容底部（不再绝对定位重叠标题） */
  .hero-cover { height: auto; min-height: 150px; flex-direction: column; align-items: stretch; }
  .hero-city { font-size: 110px; bottom: -20px; }
  .hero-overlay { padding: 20px 16px 12px; }
  .hero-title { font-size: 20px; margin-bottom: 10px; }
  .hero-pill { font-size: 11.5px; padding: 5px 10px; }
  .status-badge { position: static; align-self: flex-end; margin: 0 12px 12px; }
  .map-card, .budget-card { padding: 14px; }
  .map-hint { font-size: 11px; }
  .day-badge { width: 44px; height: 44px; font-size: 12px; }
  .stop-body { padding: 12px 14px; }
  /* 站点 meta：允许换行（钱/时长 + 投票/编辑操作不再挤一行溢出） */
  .stop-meta { flex-wrap: wrap; gap: 8px; }
  .vote-group { margin-left: 0; }
  .vote-btn { min-height: 40px; padding: 5px 12px; }
  .edit-group { margin-left: 0; flex-wrap: wrap; }
  .edit-group :deep(.el-button) { min-height: 40px; margin-left: 0; }
  .inline-edit-name { width: 100%; max-width: 100%; }
  .comment-name-input { max-width: 100%; }
}
</style>