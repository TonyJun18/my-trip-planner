<script setup>
import { ref, reactive, computed, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import * as api from '@/api'
import HotelRecommend from '@/components/HotelRecommend.vue'
import QualityCard from '@/components/QualityCard.vue'
import TripServicing from '@/components/TripServicing.vue'

const router = useRouter()
const { t } = useI18n()

const formRef = ref(null)
const submitting = ref(false)
const result = ref(null)
const activeStep = ref(0)
const taskStatus = ref('pending')
const errorMsg = ref('')
let pollTimer = null
let wsClose = null
let wsFailed = false  // WS 连接失败/关闭 → 切轮询兜底

// ── 实时事件流（WS 优先；events 也由轮询快照回填） ────────
const liveEvents = ref([])      // phase / artifact / trace 事件（按到达顺序）
const liveState = ref(null)     // 阶段状态机：{ collecting: {status, summary}, ... }
const artifacts = ref({})       // artifact 名 → data（最新一条覆盖）

// 阶段定义与状态归并
const PHASES = ['collecting', 'assembling', 'reviewing', 'completed']
const PHASE_META = {
  collecting: { icon: 'Search', key: 'phaseCollecting' },
  assembling: { icon: 'MagicStick', key: 'phaseAssembling' },
  reviewing: { icon: 'CircleCheck', key: 'phaseReviewing' },
  completed: { icon: 'Trophy', key: 'phaseCompleted' },
}

// 整体进度：已完成阶段占比（用于顶部进度条）
const donePhaseCount = computed(() => PHASES.filter((p) => (liveState.value || {})[p]?.status === 'completed').length)
const progressPercent = computed(() => Math.round((donePhaseCount.value / PHASES.length) * 100))

function applyEvent(evt) {
  if (!evt || !evt.type) return
  liveEvents.value = [...liveEvents.value, evt]
  if (evt.type === 'phase') {
    const st = { ...(liveState.value || {}) }
    st[evt.phase] = { status: evt.status || 'running', summary: evt.summary || null }
    liveState.value = st
  } else if (evt.type === 'artifact') {
    artifacts.value = { ...artifacts.value, [evt.artifact]: evt.data }
  }
}

// 阶段状态机视图：collecting → assembling → reviewing → completed
const phaseView = computed(() =>
  PHASES.map((p) => {
    const meta = PHASE_META[p]
    const st = (liveState.value || {})[p] || { status: 'pending' }
    const info = collectArtifactInfo(p)
    return { phase: p, ...meta, ...st, ...info }
  })
)

// 各阶段关联的制品信息（供阶段卡片展示"选中 N 个"）
function collectArtifactInfo(phase) {
  if (phase === 'collecting') {
    return {
      count: ['attractions', 'weather', 'hotels', 'foods'].reduce(
        (n, k) => n + (Array.isArray(artifacts.value[k]) ? artifacts.value[k].length : 0), 0),
      subItems: [
        { key: 'attractions', label: t('planWizard.artAttractions'), n: artifacts.value.attractions?.length || 0 },
        { key: 'weather', label: t('planWizard.artWeather'), n: artifacts.value.weather?.length || 0 },
        { key: 'hotels', label: t('planWizard.artHotels'), n: artifacts.value.hotels?.length || 0 },
        { key: 'foods', label: t('planWizard.artFoods'), n: artifacts.value.foods?.length || 0 },
      ],
    }
  }
  if (phase === 'assembling') {
    const draft = artifacts.value.draft
    return { count: draft?.days || 0, subItems: [], draft }
  }
  if (phase === 'reviewing') {
    const q = artifacts.value.quality
    return {
      count: q?.score != null ? 1 : 0,
      subItems: [],
      score: q?.score,
      passed: q?.passed,
      issueCount: Array.isArray(q?.issues) ? q.issues.length : 0,
    }
  }
  return { count: 0, subItems: [] }
}

// 制品展开（收集候选 chips）
const collectingArtifacts = computed(() => [
  { key: 'attractions', label: t('planWizard.artAttractions'), items: artifacts.value.attractions || [] },
  { key: 'weather', label: t('planWizard.artWeather'), items: artifacts.value.weather || [] },
  { key: 'hotels', label: t('planWizard.artHotels'), items: artifacts.value.hotels || [] },
  { key: 'foods', label: t('planWizard.artFoods'), items: artifacts.value.foods || [] },
])

const form = reactive({
  destination: '',
  start_date: '',
  end_date: '',
  travelers: 2,
  budget: 3000,
  preferences: ['food', 'nature'],
  provider: 'auto',
})

// ── 主动提问（马蜂窝 AI 路书差异化：规划前动态追问需求澄清） ──
// 问题/选项定义用 i18n key，答案存独立状态（qaAnswers）：
// 切换语言不丢已填答案；提交时把 key 解析为当前语言的自然语言 label。
const qaDefs = [
  { key: 'q1', options: ['q1o1', 'q1o2', 'q1o3', 'q1o4', 'q1o5'] },
  { key: 'q2', options: ['q2o1', 'q2o2', 'q2o3'] },
  { key: 'q3', options: ['q3o1', 'q3o2', 'q3o3'] },
  { key: 'q4', options: [] },
]
const qaAnswers = reactive({ q1: '', q2: '', q3: '', q4: '' })

function pickQuestion(q, option) {
  qaAnswers[q.key] = qaAnswers[q.key] === option ? '' : option
}

function answeredQuestions() {
  return qaDefs
    .filter((q) => (qaAnswers[q.key] || '').trim())
    .map((q) => ({
      question: t(`planWizard.${q.key}`),
      options: q.options.map((o) => t(`planWizard.${o}`)),
      answer: qaAnswers[q.key] ? t(`planWizard.${qaAnswers[q.key]}`) : '',
    }))
}

function defaultDates() {
  // 用本地日期格式化（toISOString 是 UTC 日期：UTC+8 晚间 20:00 后
  // 本地已过午夜但 UTC 未过，默认出发日期会变成「昨天」）
  const fmt = (d) => {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }
  const start = new Date()
  const end = new Date()
  end.setDate(end.getDate() + 2)
  form.start_date = fmt(start)
  form.end_date = fmt(end)
}
defaultDates()

const rules = {
  destination: [{ required: true, message: t('planWizard.reqDestMsg'), trigger: 'blur' }],
  start_date: [{ required: true, message: t('planWizard.reqStartMsg') }],
  end_date: [{ required: true, message: t('planWizard.reqEndMsg') }],
}

// 偏好项存内部 key；语言切换时高亮不丢；提交时映射当前语言 label
const prefLabelKeyMap = {
  food: 'prefFood', nature: 'prefNature', history: 'prefHistory',
  shopping: 'prefShopping', family: 'prefFamily', hiking: 'prefHiking',
  museum: 'prefMuseum', nightlife: 'prefNightlife', photo: 'prefPhoto',
  hotspring: 'prefHotspring',
}
const preferenceKeys = ['food', 'nature', 'history', 'shopping', 'family', 'hiking', 'museum', 'nightlife', 'photo', 'hotspring']
function prefLabel(k) {
  return t(`planWizard.${prefLabelKeyMap[k]}`)
}
const prefEmoji = {
  food: '🍜', nature: '🏔️', history: '🏯', shopping: '🛍️', family: '👨‍👩‍👧', hiking: '🥾',
  museum: '🏛️', nightlife: '🌃', photo: '📷', hotspring: '♨️',
}
const preferenceOptions = computed(() => preferenceKeys.map((k) => ({ key: k, label: prefLabel(k), emoji: prefEmoji[k] })))

function togglePref(p) {
  const i = form.preferences.indexOf(p.key)
  if (i >= 0) form.preferences.splice(i, 1)
  else form.preferences.push(p.key)
}

// 仪表盘样预算滑块（label 走 i18n）
const budgetPresets = [
  { labelKey: 'budgetEconomy', value: 1500 },
  { labelKey: 'budgetComfort', value: 3000 },
  { labelKey: 'budgetQuality', value: 6000 },
  { labelKey: 'budgetLuxury', value: 12000 },
]
function pickBudget(v) { form.budget = v }

async function submit() {
  await formRef.value.validate()
  submitting.value = true
  result.value = null
  errorMsg.value = ''
  liveEvents.value = []
  liveState.value = null
  artifacts.value = {}
  wsFailed = false
  activeStep.value = 1
  taskStatus.value = 'running'
  try {
    const payload = {
      ...form,
      // 偏好 key → 当前语言 label（默认中文，保持后端契约）
      preferences: form.preferences.map((k) => prefLabel(k)),
      questions: answeredQuestions(),
    }
    const task = await api.planTrip(payload)
    startRealtime(task.task_id)
    // 兜底：无论 WS 是否可用，都启动轮询（WS 存活时轮询幂等、开销小）
    schedulePoll(task.task_id)
  } catch (e) {
    submitting.value = false
    activeStep.value = 0
  }
}

// WS 优先：连接成功则靠 push 实时更新；失败/关闭自动切轮询
function startRealtime(taskId) {
  cleanupWs()
  wsFailed = false
  wsClose = api.subscribePlanTask(taskId, {
    onEvent: (evt) => {
      // 快照里的 trace 是数组，直接回填 result（兼容旧服务无 phase/artifact）
      if (evt.type === 'trace' && Array.isArray(evt.trace)) {
        result.value = { ...result.value, trace: evt.trace }
      } else {
        applyEvent(evt)
      }
    },
    onStatus: (msg) => onTaskStatus(msg),
    onClose: () => {
      wsFailed = true  // 切轮询兜底（schedulePoll 已在跑）
    },
  })
}

function cleanupWs() {
  if (wsClose) {
    try { wsClose() } catch { /* noop */ }
    wsClose = null
  }
}

function onTaskStatus(task) {
  // 终态：统一走轮询的结果合并（两者数据一致）
  if (task.status === 'completed') {
    wsFailed = true  // 停止 WS 增量（结果已齐）
    finishSuccess(task)
  } else if (task.status === 'failed') {
    wsFailed = true
    finishFail(task.error)
  } else {
    // running：把新 trace 合并进 result（中间态）
    if (task.trace?.length) result.value = { ...result.value, trace: task.trace }
  }
}

function finishSuccess(task) {
  submitting.value = false
  result.value = { ...task, trace: task.trace || [] }
  if (!liveState.value && task.events?.length) {
    // 轮询路径（WS 未通）：用服务端持久化 events 重建阶段视图
    task.events.forEach(applyEvent)
  }
  activeStep.value = 2
  ElMessage.success(t('planWizard.planSucceed'))
}

function finishFail(err) {
  errorMsg.value = err || t('planWizard.planFailed')
  submitting.value = false
  activeStep.value = 0
  ElMessage.error(errorMsg.value)
}

function schedulePoll(taskId) {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = setTimeout(() => pollTask(taskId), 700)
}

async function pollTask(taskId) {
  try {
    const task = await api.getPlanTask(taskId)
    // WS 已关闭（断线/失败）→ 用轮询数据补齐阶段视图
    if (wsFailed && task.events?.length) {
      task.events.forEach(applyEvent)
    }
    if (task.trace?.length) {
      result.value = { ...result.value, trace: task.trace }
    }
    if (task.status === 'completed') {
      finishSuccess(task)
      return
    }
    if (task.status === 'failed') {
      finishFail(task.error)
      return
    }
    // 保底轮询（WS 存活时是幂等兜底；WS 断线时是主通道）
    schedulePoll(taskId)
  } catch (e) {
    // 网络抖动：等 2s 重试
    pollTimer = setTimeout(() => pollTask(taskId), 2000)
  }
}

onBeforeUnmount(() => {
  cleanupWs()
  if (pollTimer) clearTimeout(pollTimer)
})

const traceSteps = computed(() => result.value?.trace || [])
const planDays = computed(() => result.value?.plan?.days || [])
const planBudget = computed(() => result.value?.plan?.budget || {})
// 向导页酒店推荐展示（未落库，暂不安排；详情页可安排）
const planHotels = computed(() => result.value?.plan?.hotels || [])

// ── 行程服务层（方案 B 第二段 servicing 产物：交通/通勤/入住/折扣） ──
const servicingProps = computed(() => ({
  transport: result.value?.plan?.transport || null,
  transit: result.value?.plan?.transit || null,
  checkin: result.value?.plan?.checkin || null,
  discountRules: result.value?.plan?.discount_rules || [],
  discounts: result.value?.plan?.discounts || null,
}))

const typeLabelKeys = { attraction: 'typeAttraction', food: 'typeFood', hotel: 'typeHotel' }
const typeLabel = computed(() => ({
  attraction: t('common.typeAttraction'),
  food: t('common.typeFood'),
  hotel: t('common.typeHotel'),
}))
const typeEmoji = { attraction: '🏞️', food: '🍜', hotel: '🏨' }
const typeColor = { attraction: 'var(--brand)', food: '#c2410c', hotel: '#0d8a5f' }

// Agent 名称映射（trace.thought 存了 agent 名）
const agentLabelKeys = {
  AttractionSearchAgent: 'agentAttraction',
  WeatherQueryAgent: 'agentWeather',
  HotelAgent: 'agentHotel',
  PlannerAgent: 'agentPlanner',
  TravelCriticAgent: 'agentCritic',
  orchestrator: 'agentOrchestrator',
}
function agentName(s) {
  const key = agentLabelKeys[s.thought]
  return key ? t(`planWizard.${key}`) : s.thought || 'Agent'
}

// trace 是否失败（后端 observation 为中文「失败」字样；兼容中英文）
function isTraceFailed(s) {
  return /(失败|failed|error)/i.test(s.observation || '')
}

function goDetail() {
  router.push(`/trips/${result.value.trip_id}`)
}
</script>

<template>
  <div class="wizard">
    <div class="wizard-head">
      <h2 class="page-title">{{ $t('planWizard.pageTitle') }}</h2>
      <p class="page-sub">{{ $t('planWizard.pageSub') }}</p>
      <span class="ai-badge"><el-icon :size="13"><MagicStick /></el-icon> AI</span>
    </div>

    <!-- Step 指示器 -->
    <div class="steps" :class="{ done: activeStep === 2 }">
      <div class="step" :class="{ active: activeStep === 0, done: activeStep > 0 }">
        <span class="step-num">1</span>
        <span class="step-label">{{ $t('planWizard.stepFill') }}</span>
      </div>
      <div class="step-line" :class="{ filled: activeStep >= 1 }" />
      <div class="step" :class="{ active: activeStep === 1, done: activeStep > 1 }">
        <span class="step-num">
          <el-icon v-if="activeStep === 1" class="is-loading"><Loading /></el-icon>
          <template v-else><el-icon><Check /></el-icon></template>
        </span>
        <span class="step-label">{{ $t('planWizard.stepPlanning') }}</span>
      </div>
      <div class="step-line" :class="{ filled: activeStep >= 2 }" />
      <div class="step" :class="{ active: activeStep === 2, done: activeStep > 2 }">
        <span class="step-num">3</span>
        <span class="step-label">{{ $t('planWizard.stepDone') }}</span>
      </div>
    </div>

    <!-- Step 1: 表单 -->
    <div v-show="activeStep === 0" class="panel">
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        class="plan-form"
        @submit.prevent
      >
        <!-- 分区：基础信息 -->
        <div class="form-section">
          <div class="section-head">
            <span class="section-ico"><el-icon :size="15"><Location /></el-icon></span>
            <span class="section-title">{{ $t('planWizard.sectionBasics') }}</span>
          </div>

          <!-- 目的地 -->
          <div class="field">
            <label class="field-label">{{ $t('planWizard.destLabel') }} <span class="req">*</span></label>
            <div class="dest-row">
              <el-input
                v-model="form.destination"
                size="large"
                :placeholder="$t('planWizard.destPlaceholder')"
                clearable
                class="dest-input"
              >
                <template #prefix><el-icon><Location /></el-icon></template>
              </el-input>
              <div class="hot-cities">
                <button v-for="c in ['杭州', '成都', '北京', '上海', '大理', '厦门']" :key="c"
                        type="button" class="chip" :class="{ picked: form.destination === c }" @click="form.destination = c">
                  {{ c }}
                </button>
              </div>
            </div>
          </div>

          <!-- 日期 -->
          <div class="field">
            <label class="field-label">{{ $t('planWizard.dateLabel') }}</label>
            <div class="date-row">
              <el-date-picker
                v-model="form.start_date" type="date" value-format="YYYY-MM-DD"
                :placeholder="$t('planWizard.dateDepart')" style="flex:1" size="large"
              />
              <span class="date-sep">→</span>
              <el-date-picker
                v-model="form.end_date" type="date" value-format="YYYY-MM-DD"
                :placeholder="$t('planWizard.dateReturn')" style="flex:1" size="large"
              />
            </div>
          </div>

          <div class="two-col">
            <!-- 人数 -->
            <div class="field">
              <label class="field-label">{{ $t('planWizard.travelersLabel') }}</label>
              <el-input-number v-model="form.travelers" :min="1" :max="20" size="large" style="width: 100%" />
            </div>
            <!-- 预算 -->
            <div class="field">
              <label class="field-label">{{ $t('planWizard.budgetLabel') }}</label>
              <el-input-number v-model="form.budget" :min="0" :step="500" size="large" style="width: 100%" />
            </div>
          </div>

          <!-- 预算快捷档 -->
          <div class="budget-presets">
            <button v-for="p in budgetPresets" :key="p.value"
                    type="button" class="chip" :class="{ picked: form.budget === p.value }"
                    @click="pickBudget(p.value)">{{ $t('planWizard.' + p.labelKey) }} ¥{{ p.value }}</button>
          </div>
        </div>

        <!-- 分区：需求偏好 -->
        <div class="form-section">
          <div class="section-head">
            <span class="section-ico"><el-icon :size="15"><Star /></el-icon></span>
            <span class="section-title">{{ $t('planWizard.sectionPrefs') }}</span>
          </div>

          <!-- 偏好 -->
          <div class="field">
            <label class="field-label">{{ $t('planWizard.prefLabel') }}</label>
            <div class="pref-list">
              <button v-for="p in preferenceOptions" :key="p.key"
                      type="button" class="chip pref" :class="{ picked: form.preferences.includes(p.key) }"
                      @click="togglePref(p)">
                <span class="pref-emoji">{{ p.emoji }}</span>
                <span class="pref-check" v-if="form.preferences.includes(p.key)">✓</span>
                {{ p.label }}
              </button>
            </div>
          </div>
        </div>

        <!-- 分区：补充说明 -->
        <div class="form-section">
          <div class="section-head">
            <span class="section-ico"><el-icon :size="15"><ChatDotRound /></el-icon></span>
            <span class="section-title">{{ $t('planWizard.sectionExtra') }}</span>
          </div>
          <!-- 主动提问：规划前需求澄清（可选，未答不提交） -->
          <div class="field qa-field">
            <label class="field-label">
              {{ $t('planWizard.qaTitle') }}
              <span class="qa-tip">{{ $t('planWizard.qaTip') }}</span>
            </label>
            <div class="qa-list">
              <div v-for="q in qaDefs" :key="q.key" class="qa-item">
                <div class="qa-q">{{ $t('planWizard.' + q.key) }}</div>
                <div v-if="q.options.length" class="qa-opts">
                  <button v-for="opt in q.options" :key="opt"
                          type="button" class="chip" :class="{ picked: qaAnswers[q.key] === opt }"
                          @click="pickQuestion(q, opt)">
                    <span v-if="qaAnswers[q.key] === opt" style="margin-right: 4px">✓</span>{{ $t('planWizard.' + opt) }}
                  </button>
                </div>
                <el-input
                  v-else
                  v-model="qaAnswers[q.key]"
                  size="default"
                  :placeholder="$t('planWizard.q4Placeholder')"
                  clearable
                  class="qa-input"
                />
              </div>
            </div>
          </div>
        </div>

        <button class="btn-primary big" :disabled="submitting" @click.prevent="submit">
          <el-icon style="margin-right: 8px"><MagicStick /></el-icon>{{ $t('planWizard.startBtn') }}
        </button>
      </el-form>
    </div>

    <!-- Step 2: 规划中 -->
    <div v-if="submitting" class="panel planning">
      <div class="planning-hero">
        <div class="pulse-ring">
          <div class="pulse-inner">
            <el-icon class="is-loading" :size="30" color="#fff"><Loading /></el-icon>
          </div>
        </div>
        <h3>{{ $t('planWizard.planningTitle', { dest: form.destination || $t('planWizard.planningDestFallback') }) }}</h3>
        <p class="planning-sub">{{ $t('planWizard.planningSub') }}</p>
      </div>

      <!-- 整体进度条 -->
      <div class="progress-wrap">
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: progressPercent + '%' }" />
        </div>
        <div class="progress-meta">
          <span>{{ $t('planWizard.phaseStepsDone', { done: donePhaseCount, total: PHASES.length }) }}</span>
          <span class="progress-pct">{{ progressPercent }}%</span>
        </div>
      </div>

      <!-- 阶段状态机（WS 实时 / events 回填） -->
      <div class="phase-steps">
        <div v-for="(phase, i) in phaseView" :key="phase.phase" class="phase-step"
             :class="{ pending: phase.status === 'pending', running: phase.status === 'running', done: phase.status === 'completed' }">
          <span class="phase-rail" />
          <div class="phase-head">
            <span class="phase-icon"><el-icon :size="17"><component :is="phase.icon" /></el-icon></span>
            <span class="phase-label">{{ $t('planWizard.' + phase.key) }}</span>
            <span v-if="phase.status === 'running'" class="phase-running"><el-icon class="is-loading"><Loading /></el-icon></span>
            <span v-else-if="phase.status === 'completed'" class="phase-check"><el-icon><Check /></el-icon></span>
            <span v-else class="phase-pending">{{ $t('planWizard.phasePending') }}</span>
            <span v-if="phase.status === 'completed' && phase.summary" class="phase-summary">{{ phase.summary }}</span>
          </div>

          <!-- 收集阶段制品：候选 chips -->
          <div v-if="phase.phase === 'collecting' && phase.status !== 'pending'" class="phase-body">
            <div v-for="art in collectingArtifacts" :key="art.key" class="artifact-row">
              <span class="artifact-label">{{ art.label }}</span>
              <span class="artifact-count">{{ art.items.length }}</span>
              <div class="artifact-chips">
                <span v-for="(item, idx) in art.items.slice(0, 8)" :key="idx" class="chip-mini">
                  {{ item.name }}{{ item.estimated_cost ? ' · ¥' + item.estimated_cost : '' }}
                </span>
                <span v-if="!art.items.length" class="chip-mini empty">{{ $t('planWizard.pending') }}</span>
              </div>
            </div>
          </div>

          <!-- 编排阶段：天数草案 -->
          <div v-if="phase.phase === 'assembling' && phase.draft" class="phase-body">
            <div class="draft-days">
              <span class="chip-mini draft">{{ $t('planWizard.draftDays', { n: phase.draft.days }) }}</span>
              <span v-for="(th, idx) in phase.draft.themes" :key="idx" class="chip-mini theme">{{ th }}</span>
            </div>
          </div>

          <!-- 质检阶段：评分 -->
          <div v-if="phase.phase === 'reviewing' && phase.score != null" class="phase-body">
            <div class="quality-row">
              <span class="quality-score" :class="{ pass: phase.passed }">{{ phase.score }}/100</span>
              <span class="quality-issues">{{ $t('planWizard.issuesCount', { n: phase.issueCount }) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 实时轨迹（折叠，保留技术日志） -->
      <div v-if="liveEvents.length" class="trace-live">
        <el-collapse class="trace-collapse">
          <el-collapse-item :title="$t('planWizard.traceLive')" name="live">
            <div class="agent-steps">
              <div v-for="(evt, i) in liveEvents.filter(e => e.type === 'trace')" :key="i" class="agent-step" :class="{ done: !isTraceFailed(evt.trace) }">
                <span class="agent-dot" />
                <div class="agent-content">
                  <div class="agent-row">
                    <span class="agent-name">{{ agentName(evt.trace) }}</span>
                    <span class="agent-action">{{ evt.trace.action }}</span>
                  </div>
                  <div class="agent-obs">{{ evt.trace.observation }}</div>
                </div>
              </div>
              <div v-if="!liveEvents.filter(e => e.type === 'trace').length" class="planning-wait">
                <span class="dots"><span>.</span><span>.</span><span>.</span></span> {{ $t('planWizard.waking') }}
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
      <div v-else class="planning-wait">
        <span class="dots"><span>.</span><span>.</span><span>.</span></span> {{ $t('planWizard.waking') }}
      </div>
    </div>

    <!-- Step 3: 完成 -->
    <div v-if="result && !submitting && activeStep === 2" class="panel result">
      <!-- 成功横幅 -->
      <div class="success-banner">
        <div class="success-icon">
          <el-icon :size="40" color="#fff"><Check /></el-icon>
        </div>
        <div>
          <h3 class="success-title">{{ $t('planWizard.successTitle') }}</h3>
          <p class="success-sub">{{ $t('planWizard.successSub', { dest: result.plan?.destination, days: planDays.length, budget: planBudget.total_estimated || 0 }) }}</p>
        </div>
        <div class="success-actions">
          <button class="btn-primary" @click="goDetail">{{ $t('planWizard.viewDetail') }}</button>
          <button class="btn-ghost" @click="activeStep = 0">{{ $t('planWizard.planAnother') }}</button>
        </div>
      </div>

      <!-- 行程摘要 -->
      <div class="summary-grid">
        <div class="summary-card">
          <span class="summary-ico"><el-icon :size="19"><Location /></el-icon></span>
          <div class="summary-body">
            <div class="summary-label">{{ $t('planWizard.summaryDest') }}</div>
            <div class="summary-value">{{ result.plan?.destination }}</div>
          </div>
        </div>
        <div class="summary-card">
          <span class="summary-ico"><el-icon :size="19"><Calendar /></el-icon></span>
          <div class="summary-body">
            <div class="summary-label">{{ $t('planWizard.summaryDays') }}</div>
            <div class="summary-value">{{ planDays.length }} {{ $t('common.days') }}</div>
          </div>
        </div>
        <div class="summary-card accent">
          <span class="summary-ico"><el-icon :size="19"><Money /></el-icon></span>
          <div class="summary-body">
            <div class="summary-label">{{ $t('planWizard.summaryBudget') }}</div>
            <div class="summary-value">¥{{ planBudget.total_estimated || 0 }}</div>
          </div>
        </div>
      </div>

      <!-- 每日计划 -->
      <div class="day-flow">
        <div v-for="day in planDays" :key="day.day_number" class="day-card">
          <div class="day-badge">
            <span class="day-badge-num">{{ day.day_number }}</span>
            <span class="day-badge-label">DAY</span>
          </div>
          <div class="day-content">
            <div class="day-headline">
              <h4 class="day-theme">{{ day.theme || $t('common.freeExplore') }}</h4>
              <span class="day-date">{{ day.date || '' }}</span>
            </div>
            <div class="stops">
              <div v-for="(stop, idx) in day.stops" :key="idx" class="stop">
                <span class="stop-dot" :style="{ background: typeColor[stop.type] || 'var(--brand)' }">{{ idx + 1 }}</span>
                <div class="stop-main">
                  <div class="stop-name-line">
                    <span class="stop-name">{{ stop.name }}</span>
                    <el-tag size="small" round :style="{ color: typeColor[stop.type] || 'var(--brand)', background: (typeColor[stop.type] || 'var(--brand)') + '1a', border: 'none' }">
                      {{ typeEmoji[stop.type] }} {{ typeLabel[stop.type] || stop.type }}
                    </el-tag>
                  </div>
                  <div class="stop-meta">
                    <span v-if="stop.estimated_cost" class="stop-meta-item cost">¥{{ stop.estimated_cost }}</span>
                    <span v-if="stop.duration_minutes" class="stop-meta-item">{{ stop.duration_minutes }} {{ $t('common.minutes') }}</span>
                    <span v-if="stop.description" class="stop-desc">{{ stop.description }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 行程质检报告（AI 质检专家评审结果） -->
      <QualityCard :quality="result.plan?.quality" class="wizard-quality" />

      <!-- 住宿推荐（来自 AI 酒店专家的候选；详情页可一键安排） -->
      <HotelRecommend
        :hotels="planHotels"
        :days="planDays"
        class="wizard-hotel"
      />

      <!-- 行程服务层（大交通 / 市内通勤 / 入住办理 / 折扣） -->
      <TripServicing
        :transport="servicingProps.transport"
        :transit="servicingProps.transit"
        :checkin="servicingProps.checkin"
        :discount-rules="servicingProps.discountRules"
        :discounts="servicingProps.discounts"
        class="wizard-servicing"
      />

      <!-- 预算明细 -->
      <div class="budget-card">
        <h4 class="budget-title"><el-icon :size="16"><PieChart /></el-icon>{{ $t('common.budgetTitle') }}</h4>
        <div class="budget-bars">
          <div v-for="(label, k) in { attraction: $t('common.typeAttraction'), food: $t('common.typeFood'), hotel: $t('common.typeHotel') }" :key="k" class="budget-bar-row">
            <span class="budget-bar-label">{{ label }}</span>
            <div class="budget-bar-track">
              <div class="budget-bar-fill" :style="{
                width: planBudget.total_estimated ? Math.round((planBudget.by_type?.[k] || 0) / planBudget.total_estimated * 100) + '%' : '0%',
                background: typeColor[k] || 'var(--brand)'
              }" />
            </div>
            <span class="budget-bar-value">¥{{ planBudget.by_type?.[k] || 0 }}</span>
          </div>
          <div class="budget-total-row">
            <span>{{ $t('common.total') }}</span>
            <span class="budget-total">¥{{ planBudget.total_estimated || 0 }}</span>
          </div>
        </div>
      </div>

      <!-- Agent 轨迹（折叠） -->
      <el-collapse class="trace-collapse">
        <el-collapse-item :title="$t('planWizard.traceTitle')" name="trace">
          <div class="agent-steps">
            <div v-for="(s, i) in traceSteps" :key="i" class="agent-step done">
              <span class="agent-dot" />
              <div class="agent-content">
                <div class="agent-row">
                  <span class="agent-name">{{ agentName(s) }}</span>
                  <span class="agent-action">{{ s.action }}</span>
                </div>
                <div class="agent-obs">{{ s.observation }}</div>
              </div>
            </div>
          </div>
          <el-empty v-if="!traceSteps.length" :description="$t('planWizard.traceEmpty')" :image-size="60" />
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>

<style scoped>
.wizard { max-width: 800px; margin: 0 auto; }
.wizard-head { margin-bottom: 24px; position: relative; }
.page-title { margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); }
.page-sub { margin: 6px 0 0; font-size: 14px; color: var(--muted); }
.ai-badge {
  position: absolute; top: 2px; right: 0;
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; font-weight: 700; letter-spacing: .06em; color: var(--brand);
  background: var(--brand-soft); border: 1px solid var(--el-color-primary-light-8);
  padding: 4px 10px; border-radius: var(--radius-full);
}

/* ── 表单分区 ── */
.form-section {
  border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 18px 20px; margin-bottom: 18px; background: var(--surface);
  transition: border-color .2s, box-shadow .2s;
}
.form-section:focus-within { border-color: var(--el-color-primary-light-8); box-shadow: 0 2px 8px rgba(255,56,92,0.05); }
.section-head { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.section-ico {
  width: 28px; height: 28px; border-radius: 8px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--brand-soft); color: var(--brand);
}
.section-title { font-size: 15px; font-weight: 700; color: var(--ink); letter-spacing: -0.01em; }

/* ── Step 指示器 ── */
.steps { display: flex; align-items: center; margin: 8px 0 32px; }
.step { display: flex; align-items: center; gap: 8px; }
.step-num {
  width: 30px; height: 30px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--fill); color: var(--muted); font-weight: 600; font-size: 14px;
  border: 1px solid transparent;
  transition: all .3s;
}
.step.active .step-num { background: #fff; color: var(--brand); border-color: var(--brand); box-shadow: 0 0 0 4px var(--brand-soft); }
.step.done .step-num { background: var(--success); color: #fff; border-color: var(--success); }
.step-label { font-size: 13px; color: var(--muted); }
.step.active .step-label { color: var(--ink); font-weight: 600; }
.step-line { flex: 1; height: 2px; background: var(--line); margin: 0 14px; border-radius: 2px; }
.step-line.filled { background: var(--success); }

/* ── 面板 ── */
.panel {
  background: var(--surface);
  border-radius: var(--radius-xl);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-card);
  padding: 32px 36px;
}
.field { margin-bottom: 22px; }
.field-label {
  display: block; font-size: 14px; font-weight: 600; color: var(--ink);
  margin-bottom: 8px;
}
.req { color: var(--brand); }
.dest-row { display: flex; flex-direction: column; gap: 10px; }
.hot-cities { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  border: 1px solid var(--line); background: #fff; cursor: pointer;
  font-size: 13px; color: var(--ink-2); padding: 7px 15px;
  border-radius: var(--radius-full);
  transition: all .2s;
}
.chip:hover { border-color: var(--brand); color: var(--brand); transform: translateY(-1px); }
.chip.picked { background: var(--brand); border-color: var(--brand); color: #fff; box-shadow: 0 2px 8px rgba(255,56,92,0.25); }
.chip.pref { display: inline-flex; align-items: center; gap: 6px; }
.pref-emoji { font-size: 14px; line-height: 1; }
.pref-check { font-size: 11px; }
.date-row { display: flex; align-items: center; gap: 10px; }
.date-sep { color: var(--faint); font-size: 16px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.budget-presets { display: flex; flex-wrap: wrap; gap: 8px; margin: -8px 0 22px; }
.pref-list { display: flex; flex-wrap: wrap; gap: 8px; }

/* ── 主动提问（需求澄清） ── */
.qa-field { background: var(--canvas); border: 1px solid var(--line); border-radius: var(--radius-lg); padding: 16px 18px; }
.qa-tip { font-size: 12px; color: var(--faint); font-weight: 400; margin-left: 4px; }
.qa-list { display: flex; flex-direction: column; gap: 14px; }
.qa-item { display: flex; flex-direction: column; gap: 8px; }
.qa-q { font-size: 14px; font-weight: 600; color: var(--ink); }
.qa-opts { display: flex; flex-wrap: wrap; gap: 8px; }
.qa-input { max-width: 480px; }

.btn-primary {
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--brand); color: #fff; border: none; cursor: pointer;
  font-size: 15px; font-weight: 600; padding: 14px 30px;
  border-radius: var(--radius-full);
  box-shadow: 0 4px 14px rgba(255,56,92,0.3);
  transition: all .2s;
}
.btn-primary:hover:not(:disabled) { background: var(--brand-dark); transform: translateY(-1px); box-shadow: 0 6px 20px rgba(255,56,92,0.4); }
.btn-primary:disabled { opacity: .6; cursor: not-allowed; }
.btn-primary.big { width: 100%; margin-top: 6px; font-size: 16px; padding: 15px; letter-spacing: .02em; }

.btn-ghost {
  background: transparent; border: 1px solid var(--line); cursor: pointer;
  font-size: 14px; font-weight: 500; color: var(--ink-2);
  padding: 10px 18px; border-radius: var(--radius-full);
  transition: all .2s;
}
.btn-ghost:hover { border-color: var(--brand); color: var(--brand); }

/* ── 规划中 ── */
.planning { text-align: center; }
.planning-hero { padding: 20px 0 18px; }
.pulse-ring {
  width: 84px; height: 84px; margin: 0 auto 18px;
  border-radius: 50%; background: var(--brand-soft);
  display: flex; align-items: center; justify-content: center;
  animation: pulse 1.6s ease-in-out infinite;
}
.pulse-inner {
  width: 60px; height: 60px; border-radius: 50%;
  background: var(--brand); color: #fff;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 12px rgba(255,56,92,0.35);
}
@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255,56,92,0.28); }
  50% { box-shadow: 0 0 0 18px rgba(255,56,92,0); }
}
.planning-hero h3 { margin: 0 0 6px; font-size: 19px; font-weight: 700; color: var(--ink); letter-spacing: -0.01em; }
.planning-sub { margin: 0; font-size: 13.5px; color: var(--muted); }
.planning-wait { margin-top: 20px; color: var(--faint); font-size: 13px; }
.dots span { animation: blink 1.4s infinite; }
.dots span:nth-child(2) { animation-delay: .2s; }
.dots span:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%,100% { opacity: .2; } 50% { opacity: 1; } }

/* ── 整体进度条 ── */
.progress-wrap { margin: 6px 0 22px; }
.progress-track {
  height: 10px; border-radius: var(--radius-full);
  background: var(--fill); overflow: hidden;
}
.progress-fill {
  height: 100%; border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--brand), #ff7a5c);
  transition: width .6s ease;
  box-shadow: 0 0 8px rgba(255,56,92,0.3);
}
.progress-meta {
  margin-top: 8px; display: flex; justify-content: space-between;
  font-size: 12px; color: var(--muted);
}
.progress-pct { font-weight: 700; color: var(--brand); }

/* ── 规划中：阶段状态机 + 制品卡片 ── */
.phase-steps { margin-top: 8px; text-align: left; display: flex; flex-direction: column; gap: 12px; }
.phase-step {
  position: relative; overflow: hidden;
  border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 15px 18px; background: #fff;
  box-shadow: 0 1px 2px rgba(0,0,0,0.02);
  transition: all .25s;
}
.phase-rail {
  position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
  background: var(--line);
}
.phase-step.running {
  border-color: var(--brand); box-shadow: 0 4px 16px rgba(255,56,92,0.10);
}
.phase-step.running .phase-rail { background: var(--brand); }
.phase-step.running::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(105deg, transparent 40%, rgba(255,56,92,0.08) 50%, transparent 60%);
  background-size: 200% 100%;
  animation: shimmer 1.8s linear infinite;
  pointer-events: none;
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
.phase-step.done .phase-rail { background: var(--success); }
.phase-step.pending { opacity: .6; }
.phase-head { display: flex; align-items: center; gap: 10px; position: relative; z-index: 1; }
.phase-icon {
  width: 30px; height: 30px; border-radius: 9px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--fill); color: var(--muted);
}
.phase-step.running .phase-icon { background: var(--brand-soft); color: var(--brand); }
.phase-step.done .phase-icon { background: rgba(13,138,95,0.12); color: var(--success); }
.phase-label { font-size: 14px; font-weight: 600; color: var(--ink); }
.phase-running { color: var(--brand); display: inline-flex; animation: pulse-soft 1.2s ease-in-out infinite; }
@keyframes pulse-soft { 0%,100% { opacity: 1; } 50% { opacity: .45; } }
.phase-check { color: var(--success); display: inline-flex; }
.phase-pending { font-size: 11px; color: var(--faint); text-transform: uppercase; letter-spacing: .04em; margin-left: 4px; }
.phase-summary { margin-left: auto; font-size: 12px; color: var(--muted); }
.phase-body { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; position: relative; z-index: 1; }
.artifact-row { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.artifact-label { font-size: 12px; font-weight: 600; color: var(--ink-2); min-width: 52px; }
.artifact-count {
  font-size: 11px; font-weight: 600; color: var(--brand);
  background: var(--brand-soft); border-radius: var(--radius-full);
  padding: 1px 8px;
}
.artifact-chips { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; }
.chip-mini {
  font-size: 11.5px; color: var(--ink-2); background: var(--fill);
  border-radius: var(--radius-full); padding: 3px 10px; white-space: nowrap;
}
.chip-mini.empty { color: var(--faint); background: transparent; font-style: italic; }
.chip-mini.draft { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
.chip-mini.theme { background: #f2f7ff; color: var(--ink-2); }
.draft-days { display: flex; flex-wrap: wrap; gap: 6px; }
.quality-row { display: flex; align-items: center; gap: 12px; }
.quality-score {
  font-size: 22px; font-weight: 700; color: #d97706;
}
.quality-score.pass { color: var(--success); }
.quality-issues { font-size: 12.5px; color: var(--muted); }
.trace-live { margin-top: 14px; text-align: left; }
.trace-live .agent-steps { margin-top: 8px; }

/* ── Agent 步骤轨迹 ── */
.agent-steps { text-align: left; margin-top: 24px; display: flex; flex-direction: column; gap: 0; }
.agent-step { display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px dashed var(--line); }
.agent-step:last-child { border-bottom: none; }
.agent-dot {
  width: 10px; height: 10px; border-radius: 50%; margin-top: 5px; flex-shrink: 0;
  background: var(--faint);
}
.agent-step.done .agent-dot { background: var(--success); }
.agent-row { display: flex; align-items: center; gap: 8px; }
.agent-name { font-size: 13px; font-weight: 600; color: var(--ink); }
.agent-action {
  font-size: 11px; color: var(--brand); background: var(--brand-soft);
  padding: 2px 8px; border-radius: var(--radius-full);
}
.agent-obs { font-size: 12.5px; color: var(--muted); margin-top: 3px; }

/* ── 结果 ── */
.success-banner {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  background: linear-gradient(135deg, var(--brand-soft), #fff 55%);
  border: 1px solid #ffdbe0; border-radius: var(--radius-xl);
  padding: 24px 28px; margin-bottom: 24px;
  box-shadow: 0 2px 10px rgba(255,56,92,0.06);
}
.success-icon {
  width: 60px; height: 60px; border-radius: 50%; flex-shrink: 0;
  background: var(--brand); display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 18px rgba(255,56,92,0.35);
}
.success-title { margin: 0 0 4px; font-size: 20px; font-weight: 700; color: var(--ink); letter-spacing: -0.01em; }
.success-sub { margin: 0; font-size: 13.5px; color: var(--muted); }
.success-actions { margin-left: auto; display: flex; gap: 10px; }

.summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 30px; }
.summary-card {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 18px 20px; display: flex; align-items: center; gap: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
  transition: transform .2s, box-shadow .2s, border-color .2s;
}
.summary-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-hover); border-color: var(--el-color-primary-light-8); }
.summary-card.accent { background: linear-gradient(135deg, var(--brand-soft), #fff); border-color: #ffdbe0; }
.summary-ico {
  width: 42px; height: 42px; border-radius: 12px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--fill); color: var(--muted);
}
.summary-card.accent .summary-ico { background: #fff; color: var(--brand); }
.summary-body { min-width: 0; }
.summary-label { font-size: 12px; color: var(--muted); margin-bottom: 3px; letter-spacing: .02em; }
.summary-value { font-size: 19px; font-weight: 700; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.summary-card.accent .summary-value { color: var(--brand); }

.day-flow { display: flex; flex-direction: column; gap: 16px; margin-bottom: 30px; }
.day-card {
  display: flex; gap: 20px; border: 1px solid var(--line);
  border-radius: var(--radius-lg); padding: 22px 24px; background: #fff;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
  transition: box-shadow .2s, transform .2s, border-color .2s;
}
.day-card:hover { box-shadow: var(--shadow-hover); border-color: var(--el-color-primary-light-8); }
.day-card + .day-card { margin-top: 0; }
.day-badge {
  flex-shrink: 0; width: 60px; height: 60px; border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--ink), #444); color: #fff;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  box-shadow: 0 4px 10px rgba(0,0,0,0.12);
}
.day-badge-num { font-size: 22px; font-weight: 800; line-height: 1; }
.day-badge-label { font-size: 10px; letter-spacing: .08em; margin-top: 3px; opacity: .75; }
.day-content { flex: 1; min-width: 0; }
.day-headline { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px dashed var(--line); }
.day-theme { margin: 0; font-size: 16px; font-weight: 600; color: var(--ink); }
.day-date { font-size: 12.5px; color: var(--faint); }
.stops { display: flex; flex-direction: column; }
.stop { display: flex; gap: 14px; position: relative; padding-bottom: 18px; }
.stop:last-child { padding-bottom: 0; }
/* 纵向连接线（时间轴） */
.stop::before {
  content: ''; position: absolute; left: 11px; top: 26px; bottom: -2px;
  width: 2px; background: var(--line); border-radius: 2px;
}
.stop:last-child::before { display: none; }
.stop-dot {
  width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0;
  color: #fff; font-size: 12px; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 0 3px #fff, 0 0 0 4px var(--line);
  z-index: 1;
}
.stop-main { flex: 1; min-width: 0; }
.stop-name-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.stop-name { font-size: 14.5px; font-weight: 600; color: var(--ink); }
.stop-meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: 12.5px; color: var(--muted); margin-top: 4px; }
.stop-meta-item.cost { color: var(--brand); font-weight: 600; }
.stop-desc { color: var(--faint); }

.budget-card {
  border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 22px 24px; margin-bottom: 20px; background: #fff;
}
.wizard-hotel { margin-bottom: 20px; }
.wizard-quality { margin-bottom: 20px; }
.wizard-servicing { margin-bottom: 20px; }
.budget-title {
  margin: 0 0 16px; font-size: 15px; font-weight: 700; color: var(--ink);
  display: flex; align-items: center; gap: 8px;
}
.budget-title :deep(.el-icon) { color: var(--brand); }
.budget-bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.budget-bar-label { width: 40px; font-size: 13px; color: var(--muted); }
.budget-bar-track { flex: 1; height: 10px; border-radius: var(--radius-full); background: var(--fill); overflow: hidden; }
.budget-bar-fill { height: 100%; border-radius: var(--radius-full); transition: width .6s ease; }
.budget-bar-value { width: 64px; text-align: right; font-size: 13px; font-weight: 600; color: var(--ink); }
.budget-total-row {
  display: flex; justify-content: space-between; align-items: center;
  border-top: 1px solid var(--line); padding-top: 14px; margin-top: 8px;
  font-size: 14px; color: var(--muted);
}
.budget-total { font-size: 18px; font-weight: 700; color: var(--brand); }

.trace-collapse { border: none; }
.trace-collapse :deep(.el-collapse-item__header) {
  border: none; font-size: 13px; font-weight: 500; color: var(--muted);
  padding: 4px 12px; border-radius: var(--radius-full);
  transition: background .2s, color .2s;
}
.trace-collapse :deep(.el-collapse-item__header:hover) { background: var(--fill); color: var(--ink); }
.trace-collapse :deep(.el-collapse-item__wrap) { border: none; }

/* 响应式 */
@media (max-width: 720px) {
  .panel { padding: 24px 20px; }
  .two-col { grid-template-columns: 1fr; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
  .day-card { flex-direction: column; }
  .success-actions { margin-left: 0; width: 100%; }
}
</style>