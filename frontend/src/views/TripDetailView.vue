<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api'
import TripMap from '@/components/TripMap.vue'
import HotelRecommend from '@/components/HotelRecommend.vue'
import QualityCard from '@/components/QualityCard.vue'
import { exportImage, exportPdf } from '@/utils/export'

const route = useRoute()
const router = useRouter()

const trip = ref(null)
const loading = ref(false)
const budget = ref(null)
const plan = ref(null)
const exporting = ref(false)
const exportEl = ref(null)

// ── AI 调整行程（方案 B：对话式修订） ─────────────────────
const reviseMsg = ref('')
const revising = ref(false)
const lastReviseSummary = ref('')
const lastReviseDiff = ref([])

// diff 动作 → 人类可读文案（后端已给 op_label/target_name/day_number/fields）
const diffLabel = {
  replace: '修改',
  add: '新增',
  remove: '删除',
  reorder: '调整顺序',
}
function diffText(a) {
  const day = a.day_number ? `Day${a.day_number} · ` : ''
  const target = a.target_name || ''
  if (a.op === 'reorder') {
    return `${day}调整站点顺序（移至第 ${(a.index ?? 0) + 1} 位）`
  }
  const fieldKeys = Object.keys(a.fields || {})
  const fieldText = fieldKeys.length ? `（${fieldKeys.join('、')}）` : ''
  return `${day}${diffLabel[a.op] || a.op}「${target}」${fieldText}`
}

async function revise() {
  const msg = reviseMsg.value.trim()
  if (!msg) {
    ElMessage.warning('先告诉我你想怎么调整')
    return
  }
  revising.value = true
  lastReviseDiff.value = []
  try {
    const r = await api.reviseTrip(route.params.id, { message: msg, provider: 'auto' })
    lastReviseSummary.value = r.summary || ''
    lastReviseDiff.value = Array.isArray(r.diff) ? r.diff : []
    ElMessage.success(r.summary || '行程已更新')
    reviseMsg.value = ''
    budget.value = null
    await load()
  } catch (e) {
    // api 拦截器已 toast 具体错误；补充可操作的下一步提示
    lastReviseSummary.value = ''
    ElMessage.error('调整失败：请确认描述里的站点名称与当前行程一致后重试')
  } finally {
    revising.value = false
  }
}

// ── 编辑对话框状态 ─────────────────────────
const editType = ref(null)
const editDayId = ref(null)
const editStopId = ref(null)
const stopForm = ref({ name: '', stop_type: 'attraction', lat: null, lng: null, description: '', estimated_cost: null, estimated_duration_minutes: null })
const dayForm = ref({ day_number: 1 })
const tripForm = ref({ title: '', destination: '', travelers: 1, budget: null })
const dialogVisible = ref(false)
const stopFormRef = ref(null)

// 编辑/添加共用表单；编辑时把 stop 字段拷入（null 转空串便于输入框清空）
function blankStopForm() {
  return { name: '', stop_type: 'attraction', lat: null, lng: null, description: '', estimated_cost: null, estimated_duration_minutes: null }
}
function openEditStop(day, stop) {
  editDayId.value = day.id
  editStopId.value = stop.id
  stopForm.value = {
    name: stop.name,
    stop_type: stop.stop_type || 'attraction',
    lat: stop.lat ?? '',
    lng: stop.lng ?? '',
    description: stop.description ?? '',
    estimated_cost: stop.estimated_cost ?? null,
    estimated_duration_minutes: stop.estimated_duration_minutes ?? null,
  }
  editType.value = 'edit-stop'
  dialogVisible.value = true
}
async function saveEditStop() {
  await stopFormRef.value.validate()
  const payload = { ...stopForm.value }
  if (payload.lat === '' || payload.lat == null) payload.lat = null
  if (payload.lng === '' || payload.lng == null) payload.lng = null
  if (payload.estimated_cost === '' || payload.estimated_cost == null) payload.estimated_cost = null
  if (payload.estimated_duration_minutes === '' || payload.estimated_duration_minutes == null) payload.estimated_duration_minutes = null
  await api.updateStop(editDayId.value, editStopId.value, payload)
  ElMessage.success('站点已更新')
  dialogVisible.value = false
  load()
}

// ── 上移 / 下移（整日顺序重排） ────────────
async function moveStop(day, stop, dir) {
  const stops = day.stops
  const idx = stops.findIndex((s) => s.id === stop.id)
  const target = idx + dir
  if (idx < 0 || target < 0 || target >= stops.length) return
  const order = stops.map((s) => s.id)
  ;[order[idx], order[target]] = [order[target], order[idx]]
  try {
    await api.reorderStops(day.id, order)
    ElMessage.success(dir < 0 ? '已上移' : '已下移')
    load()
  } catch (e) {
    // api 拦截器已 toast
  }
}

const markers = computed(() => {
  const list = []
  for (const day of trip.value?.days || []) {
    for (const stop of day.stops || []) {
      if (stop.lat != null && stop.lng != null) {
        list.push({ lat: stop.lat, lng: stop.lng, name: stop.name, stop_type: stop.stop_type, description: stop.description })
      }
    }
  }
  return list
})

// 行程状态：展示 + 切换
const statusMap = {
  draft: { label: '草稿', type: 'info' },
  planning: { label: '规划中', type: 'warning' },
  confirmed: { label: '已确认', type: 'success' },
  archived: { label: '已归档', type: 'info' },
}
const statusOptions = Object.entries(statusMap).map(([value, s]) => ({ value, label: s.label }))

// ── 状态切换（PATCH /trips/{id} status 字段，后端已支持） ──
const statusUpdating = ref(false)
async function changeStatus() {
  const newStatus = trip.value.status
  statusUpdating.value = true
  try {
    await api.updateTrip(route.params.id, { status: newStatus })
    ElMessage.success(`已切换为「${(statusMap[newStatus] || {}).label || newStatus}」`)
  } catch {
    // 失败时回滚为当前真实状态
    await load()
  } finally {
    statusUpdating.value = false
  }
}

const typeLabel = { attraction: '景点', food: '餐饮', hotel: '住宿' }
const typeColor = { attraction: 'var(--brand)', food: '#c2410c', hotel: '#0d8a5f' }
const typeEmoji = { attraction: '🏞️', food: '🍜', hotel: '🏨' }

// 预算环形
const budgetPercent = computed(() => {
  if (!budget.value?.total_estimated || !trip.value?.budget) return null
  return Math.min(100, Math.round((budget.value.total_estimated / trip.value.budget) * 100))
})

async function load() {
  loading.value = true
  try {
    trip.value = await api.getTrip(route.params.id)
    budget.value = await api.getBudget(route.params.id)
    // 尽力加载 AI 规划方案（含酒店推荐候选）；404/报错不阻断详情页
    try {
      plan.value = await api.getTripPlan(route.params.id)
    } catch {
      plan.value = null
    }
  } finally {
    loading.value = false
  }
}

// ── 酒店推荐（公共组件 HotelRecommend 接收 plan.hotels + trip.days） ──
const hotelCandidates = computed(() => plan.value?.hotels || [])

// ── 导出 ───────────────────────────────────
async function doExportImage() {
  exporting.value = true
  try {
    await nextTick()
    await exportImage(exportEl.value, `${trip.value.destination}-行程`)
    ElMessage.success('图片已导出')
  } catch (e) {
    ElMessage.error('导出失败: ' + e.message)
  } finally {
    exporting.value = false
  }
}
async function doExportPdf() {
  exporting.value = true
  try {
    await nextTick()
    await exportPdf(exportEl.value, `${trip.value.destination}-行程`)
    ElMessage.success('PDF 已导出')
  } catch (e) {
    ElMessage.error('导出失败: ' + e.message)
  } finally {
    exporting.value = false
  }
}

// ── 分享（只读链接） ─────────────────────────────────────
const sharing = ref(false)
async function doShare() {
  sharing.value = true
  try {
    const r = await api.createShare(trip.value.id)
    const url = r.share_url
    try {
      await navigator.clipboard.writeText(url)
      ElMessage.success('分享链接已复制，持链接者可只读查看行程')
    } catch {
      ElMessage.success(`分享链接：${url}`)
    }
  } catch (e) {
    ElMessage.error('生成分享链接失败')
  } finally {
    sharing.value = false
  }
}

// ── 批量生成日程（按日期范围） ──────────────
const genDaysVisible = ref(false)
const genRange = ref([])
const genDaysLoading = ref(false)
async function genDays() {
  if (!genRange.value?.length) {
    ElMessage.warning('请选择日期范围')
    return
  }
  genDaysLoading.value = true
  try {
    const [start, end] = genRange.value
    const days = await api.generateDays(route.params.id, start, end)
    ElMessage.success(`已生成 ${days.length} 天日程`)
    genDaysVisible.value = false
    genRange.value = []
    await load()
  } finally {
    genDaysLoading.value = false
  }
}

// ── 编辑行程基本信息 ───────────────────────
function openEditTrip() {
  tripForm.value = {
    title: trip.value.title,
    destination: trip.value.destination,
    travelers: trip.value.travelers,
    budget: trip.value.budget,
  }
  editType.value = 'edit-trip'
  dialogVisible.value = true
}
async function saveTrip() {
  const data = {}
  if (tripForm.value.title !== trip.value.title) data.title = tripForm.value.title
  if (tripForm.value.destination !== trip.value.destination) data.destination = tripForm.value.destination
  if (tripForm.value.travelers !== trip.value.travelers) data.travelers = tripForm.value.travelers
  if (tripForm.value.budget !== trip.value.budget) data.budget = tripForm.value.budget
  await api.updateTrip(trip.value.id, data)
  ElMessage.success('已保存')
  dialogVisible.value = false
  load()
}

// ── 添加日程 ───────────────────────────────
function openAddDay() {
  const maxDay = trip.value.days.reduce((m, d) => Math.max(m, d.day_number), 0)
  dayForm.value = { day_number: maxDay + 1 }
  editType.value = 'add-day'
  dialogVisible.value = true
}
async function saveDay() {
  await api.addDay(trip.value.id, dayForm.value)
  ElMessage.success('已添加日程')
  dialogVisible.value = false
  load()
}

// ── 添加站点 ───────────────────────────────
function openAddStop(dayId) {
  editDayId.value = dayId
  editStopId.value = null
  stopForm.value = blankStopForm()
  editType.value = 'add-stop'
  dialogVisible.value = true
}
async function saveStop() {
  await stopFormRef.value.validate()
  const payload = { ...stopForm.value }
  if (payload.lat === '' || payload.lat == null) payload.lat = null
  if (payload.lng === '' || payload.lng == null) payload.lng = null
  if (payload.estimated_cost === '' || payload.estimated_cost == null) payload.estimated_cost = null
  if (payload.estimated_duration_minutes === '' || payload.estimated_duration_minutes == null) payload.estimated_duration_minutes = null
  await api.addStop(editDayId.value, payload)
  ElMessage.success('已添加站点')
  dialogVisible.value = false
  load()
}

// ── 删除 ───────────────────────────────────
async function removeStop(day, stop) {
  try {
    await ElMessageBox.confirm(`删除站点「${stop.name}」？`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteStop(day.id, stop.id)
  ElMessage.success('已删除站点')
  load()
}
async function removeDay(day) {
  try {
    await ElMessageBox.confirm(`删除第 ${day.day_number} 天日程？其下所有站点将一并删除。`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteDay(day.id)
  ElMessage.success('已删除日程')
  load()
}
async function removeTrip() {
  try {
    await ElMessageBox.confirm(`删除整个行程「${trip.value.title}」？`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteTrip(trip.value.id)
  ElMessage.success('已删除')
  router.push('/')
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="detail-page">
    <!-- 返回 -->
    <div class="topbar">
      <button class="back-btn" @click="router.push('/')">
        <el-icon><ArrowLeft /></el-icon> 我的行程
      </button>
      <div class="topbar-actions">
        <el-button type="success" plain :loading="sharing" @click="doShare">
          <el-icon style="margin-right: 4px"><Share /></el-icon>分享行程
        </el-button>
        <el-button @click="openEditTrip">编辑基本信息</el-button>
        <el-button type="danger" plain @click="removeTrip">删除行程</el-button>
      </div>
    </div>

    <template v-if="trip">
      <!-- 导出区（截图/PDF 抓取范围） -->
      <div ref="exportEl" class="export-area">
        <!-- 头图 + 概览 -->
        <div class="hero-card">
          <div class="hero-cover">
            <div class="hero-city">{{ (trip.destination || '?')[0] }}</div>
            <div class="hero-overlay">
              <h1 class="hero-title">{{ trip.title }}</h1>
              <div class="hero-meta">
                <span class="hero-pill"><el-icon><Location /></el-icon>{{ trip.destination }}</span>
                <span class="hero-pill"><el-icon><Calendar /></el-icon>{{ trip.start_date }} ~ {{ trip.end_date }}</span>
                <span class="hero-pill"><el-icon><User /></el-icon>{{ trip.travelers }} 人</span>
                <span class="hero-pill" v-if="trip.budget != null"><el-icon><Wallet /></el-icon>预算 ¥{{ trip.budget }}</span>
              </div>
            </div>
            <span class="status-group">
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
            </span>
          </div>
        </div>

        <!-- 地图 + 预算 -->
        <div class="map-budget-row">
          <div class="map-card">
            <div class="card-head">
              <span class="card-title">行程地图</span>
              <span class="map-hint">按游玩顺序连线 · 点击标记查看详情</span>
            </div>
            <TripMap :markers="markers" height="420px" />
          </div>
          <div class="budget-card">
            <div class="card-head"><span class="card-title">预算明细</span></div>
            <template v-if="budget">
              <div class="budget-ring-wrap">
                <div class="budget-ring" :style="{ '--pct': budgetPercent != null ? budgetPercent : 0 }">
                  <div class="budget-ring-inner">
                    <div class="ring-total">¥{{ budget.total_estimated }}</div>
                    <div class="ring-label">已估算</div>
                  </div>
                </div>
                <div class="ring-caption" v-if="budgetPercent != null">
                  占设定预算 {{ budgetPercent }}%
                </div>
              </div>
              <div class="budget-lines">
                <div v-for="(label, k) in { attraction: '景点', food: '餐饮', hotel: '住宿' }" :key="k" class="budget-line">
                  <span class="budget-dot" :style="{ background: typeColor[k] }" />
                  <span>{{ label }}</span>
                  <span class="budget-line-val">¥{{ budget.by_type?.[k] || 0 }}</span>
                </div>
                <div class="budget-line total">
                  <span>合计</span>
                  <span class="total-val">¥{{ budget.total_estimated }}</span>
                </div>
              </div>
              <div class="budget-daily" v-if="budget.daily_average">
                <el-icon><TrendCharts /></el-icon> 日均约 ¥{{ budget.daily_average }}
              </div>
            </template>
            <el-empty v-else description="暂无预算数据" :image-size="60" />
          </div>
        </div>

        <!-- AI 调整行程（方案 B：对话式修订） -->
        <div class="revise-card">
          <div class="revise-head">
            <span class="revise-title"><el-icon style="margin-right: 6px"><ChatDotRound /></el-icon>让 AI 调整行程</span>
            <span class="revise-hint">用一句话告诉它你想怎么改</span>
          </div>
          <div class="revise-row">
            <el-input
              v-model="reviseMsg"
              placeholder="例如：第三天太赶了，西湖只留半天，晚上加个知味观"
              size="large"
              clearable
              @keyup.enter="revise"
            />
            <el-button type="primary" size="large" :loading="revising" @click="revise">
              <el-icon style="margin-right: 4px"><MagicStick /></el-icon>调整
            </el-button>
          </div>
          <transition name="el-fade-in">
            <div v-if="lastReviseSummary" class="revise-summary">
              <el-icon style="margin-right: 4px; color: var(--success)"><CircleCheck /></el-icon>
              {{ lastReviseSummary }}
            </div>
          </transition>
          <!-- 变更动作预览（diff 列表） -->
          <transition name="el-fade-in">
            <div v-if="lastReviseDiff.length" class="revise-diff">
              <div class="revise-diff-head">
                <span class="revise-diff-title"><el-icon style="margin-right: 5px"><List /></el-icon>本次改动</span>
                <span class="revise-diff-count">{{ lastReviseDiff.length }} 项</span>
              </div>
              <div v-for="(a, i) in lastReviseDiff" :key="i" class="revise-diff-item" :class="'op-' + (a.op || '')">
                <el-icon class="revise-diff-icon"><template v-if="a.op === 'add'"><Plus /></template><template v-else-if="a.op === 'remove'"><Minus /></template><template v-else><Edit /></template></el-icon>
                <span class="revise-diff-text">{{ diffText(a) }}</span>
              </div>
            </div>
          </transition>
        </div>

        <!-- 生成时的 AI 质检报告 -->
        <QualityCard :quality="plan?.quality" class="detail-quality" />

        <!-- 住宿推荐（来自 AI 规划方案的酒店候选） -->
        <HotelRecommend
          :hotels="hotelCandidates"
          :days="trip.days"
          actionable
          @arranged="load"
        />

        <!-- 每日行程 -->
        <div class="day-section" v-for="day in trip.days" :key="day.id">
          <div class="day-head">
            <div class="day-headline">
              <span class="day-badge">Day {{ day.day_number }}</span>
              <div>
                <div class="day-title">{{ day.date || `第 ${day.day_number} 天` }}</div>
                <div class="day-note">{{ day.note || '自由探索' }}</div>
              </div>
            </div>
            <div class="day-actions">
              <el-button size="small" type="primary" plain @click="openAddStop(day.id)">+ 添加站点</el-button>
              <el-button size="small" type="danger" plain @click="removeDay(day)">删除日程</el-button>
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
                  <span v-if="stop.estimated_duration_minutes"><el-icon><Clock /></el-icon>{{ stop.estimated_duration_minutes }} 分钟</span>
                </div>
                <div v-if="stop.description" class="stop-desc">{{ stop.description }}</div>
                <div class="stop-actions">
                  <el-button link size="small" @click="moveStop(day, stop, -1)" :disabled="idx === 0">上移</el-button>
                  <el-button link size="small" @click="moveStop(day, stop, 1)" :disabled="idx === day.stops.length - 1">下移</el-button>
                  <el-button link type="primary" @click="openEditStop(day, stop)">编辑</el-button>
                  <el-button link type="danger" @click="removeStop(day, stop)">删除</el-button>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else description="这一天还没有站点" :image-size="60" />
        </div>
      </div>

      <!-- 底部操作 -->
      <div class="bottom-bar">
        <el-button @click="openAddDay"><el-icon style="margin-right: 4px"><Plus /></el-icon>添加日程</el-button>
        <el-button @click="genDaysVisible = true"><el-icon style="margin-right: 4px"><Calendar /></el-icon>按日期生成日程</el-button>
        <el-button type="success" plain :loading="exporting" @click="doExportImage">
          <el-icon style="margin-right: 4px"><Picture /></el-icon>导出图片
        </el-button>
        <el-button type="primary" plain :loading="exporting" @click="doExportPdf">
          <el-icon style="margin-right: 4px"><Document /></el-icon>导出 PDF
        </el-button>
      </div>
    </template>

    <!-- 批量生成日程对话框 -->
    <el-dialog v-model="genDaysVisible" title="按日期批量生成日程" width="440px">
      <el-form label-width="80px">
        <el-form-item label="日期范围">
          <el-date-picker
            v-model="genRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
        <div class="gen-days-hint">将按范围内每一天生成一个日程（跳过已存在的天数）</div>
      </el-form>
      <template #footer>
        <el-button @click="genDaysVisible = false">取消</el-button>
        <el-button type="primary" :loading="genDaysLoading" @click="genDays">生成</el-button>
      </template>
    </el-dialog>

    <!-- 编辑对话框（三合一） -->
    <el-dialog
      v-model="dialogVisible"
      :title="editType === 'edit-trip' ? '编辑行程信息' : editType === 'add-day' ? '添加日程' : editType === 'edit-stop' ? '编辑站点' : '添加站点'"
      width="480px"
    >
      <el-form v-if="editType === 'edit-trip'" :model="tripForm" label-width="80px">
        <el-form-item label="标题"><el-input v-model="tripForm.title" /></el-form-item>
        <el-form-item label="目的地"><el-input v-model="tripForm.destination" /></el-form-item>
        <el-form-item label="人数"><el-input-number v-model="tripForm.travelers" :min="1" /></el-form-item>
        <el-form-item label="预算"><el-input-number v-model="tripForm.budget" :min="0" :step="500" /></el-form-item>
      </el-form>

      <el-form v-else-if="editType === 'add-day'" :model="dayForm" label-width="80px">
        <el-form-item label="天数编号"><el-input-number v-model="dayForm.day_number" :min="1" /></el-form-item>
        <el-form-item label="日期"><el-date-picker v-model="dayForm.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="dayForm.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>

      <el-form v-else ref="stopFormRef" :model="stopForm" label-width="90px">
        <el-form-item label="名称" prop="name" :rules="[{ required: true, message: '请输入名称' }]">
          <el-input v-model="stopForm.name" placeholder="如：西湖、楼外楼" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="stopForm.stop_type">
            <el-radio-button value="attraction">景点</el-radio-button>
            <el-radio-button value="food">餐饮</el-radio-button>
            <el-radio-button value="hotel">住宿</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="经纬度">
          <div class="latlng">
            <el-input v-model="stopForm.lat" placeholder="纬度 lat (可选)" />
            <el-input v-model="stopForm.lng" placeholder="经度 lng (可选)" />
          </div>
        </el-form-item>
        <el-form-item label="预估费用"><el-input-number v-model="stopForm.estimated_cost" :min="0" :step="50" /></el-form-item>
        <el-form-item label="时长(分钟)"><el-input-number v-model="stopForm.estimated_duration_minutes" :min="0" :step="30" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="stopForm.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="editType === 'edit-trip' ? saveTrip() : editType === 'add-day' ? saveDay() : editType === 'edit-stop' ? saveEditStop() : saveStop()">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.detail-page { max-width: 1080px; margin: 0 auto; }

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
.status-group {
  position: absolute; top: 16px; right: 16px; z-index: 2;
  display: flex; align-items: center; gap: 8px;
}
.status-badge {
  font-size: 12px; font-weight: 600; padding: 5px 12px;
  border-radius: var(--radius-full); background: rgba(255,255,255,0.9);
}
.status-badge.success { color: var(--success); }
.status-badge.warning { color: var(--warning); }
.status-badge.info { color: var(--muted); }
.status-switch { width: 108px; }

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

/* ── AI 调整行程（方案 B） ── */
.revise-card {
  background: linear-gradient(135deg, var(--brand-soft), #fff 60%);
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
.revise-summary {
  margin-top: 10px; font-size: 13px; color: var(--success);
  background: rgba(16,185,129,.08); padding: 8px 12px;
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
.revise-diff-item.op-replace { background: rgba(250,204,21,.10); }
.revise-diff-icon { font-size: 14px; flex-shrink: 0; }
.revise-diff-item.op-add .revise-diff-icon { color: var(--success); }
.revise-diff-item.op-remove .revise-diff-icon { color: #ef4444; }
.revise-diff-item.op-replace .revise-diff-icon { color: #d97706; }
.revise-diff-text { line-height: 1.45; }
.detail-quality { margin-top: 4px; }

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

/* 响应式 */
@media (max-width: 860px) {
  .map-budget-row { grid-template-columns: 1fr; }
  .hero-cover { height: 160px; }
  .hero-overlay { padding: 24px; }
  .hero-title { font-size: 24px; }
}
</style>