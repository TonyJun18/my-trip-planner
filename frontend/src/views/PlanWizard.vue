<script setup>
import { ref, reactive, computed, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import * as api from '@/api'
import HotelRecommend from '@/components/HotelRecommend.vue'
import QualityCard from '@/components/QualityCard.vue'

const router = useRouter()
const { t } = useI18n()

const formRef = ref(null)
const submitting = ref(false)
const result = ref(null)
const activeStep = ref(0)
const taskStatus = ref('pending')
const errorMsg = ref('')
let pollTimer = null

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
const preferenceOptions = computed(() => preferenceKeys.map((k) => ({ key: k, label: prefLabel(k) })))

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
    pollTask(task.task_id)
  } catch (e) {
    submitting.value = false
    activeStep.value = 0
  }
}

async function pollTask(taskId) {
  try {
    const task = await api.getPlanTask(taskId)
    if (task.trace?.length) {
      result.value = { ...result.value, trace: task.trace }
    }
    if (task.status === 'completed') {
      result.value = { ...task, trace: task.trace || [] }
      submitting.value = false
      activeStep.value = 2
      ElMessage.success(t('planWizard.planSucceed'))
      return
    }
    if (task.status === 'failed') {
      errorMsg.value = task.error || t('planWizard.planFailed')
      submitting.value = false
      activeStep.value = 0
      ElMessage.error(errorMsg.value)
      return
    }
    pollTimer = setTimeout(() => pollTask(taskId), 1500)
  } catch (e) {
    pollTimer = setTimeout(() => pollTask(taskId), 2000)
  }
}

onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
})

const traceSteps = computed(() => result.value?.trace || [])
const planDays = computed(() => result.value?.plan?.days || [])
const planBudget = computed(() => result.value?.plan?.budget || {})
// 向导页酒店推荐展示（未落库，暂不安排；详情页可安排）
const planHotels = computed(() => result.value?.plan?.hotels || [])

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

        <!-- 偏好 -->
        <div class="field">
          <label class="field-label">{{ $t('planWizard.prefLabel') }}</label>
          <div class="pref-list">
            <button v-for="p in preferenceOptions" :key="p.key"
                    type="button" class="chip pref" :class="{ picked: form.preferences.includes(p.key) }"
                    @click="togglePref(p)">
              <span class="pref-check" v-if="form.preferences.includes(p.key)">✓</span>
              {{ p.label }}
            </button>
          </div>
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

        <button class="btn-primary big" :disabled="submitting" @click.prevent="submit">
          <el-icon style="margin-right: 8px"><MagicStick /></el-icon>{{ $t('planWizard.startBtn') }}
        </button>
      </el-form>
    </div>

    <!-- Step 2: 规划中 -->
    <div v-if="submitting" class="panel planning">
      <div class="planning-hero">
        <div class="pulse-ring">
          <el-icon class="is-loading" :size="34" color="var(--brand)"><Loading /></el-icon>
        </div>
        <h3>{{ $t('planWizard.planningTitle', { dest: form.destination || $t('planWizard.planningDestFallback') }) }}</h3>
        <p class="planning-sub">{{ $t('planWizard.planningSub') }}</p>
      </div>

      <!-- 实时轨迹 -->
      <div v-if="traceSteps.length" class="agent-steps">
        <div v-for="(s, i) in traceSteps" :key="i" class="agent-step" :class="{ done: !isTraceFailed(s) }">
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
          <div class="summary-label">{{ $t('planWizard.summaryDest') }}</div>
          <div class="summary-value">{{ result.plan?.destination }}</div>
        </div>
        <div class="summary-card">
          <div class="summary-label">{{ $t('planWizard.summaryDays') }}</div>
          <div class="summary-value">{{ planDays.length }} {{ $t('common.days') }}</div>
        </div>
        <div class="summary-card">
          <div class="summary-label">{{ $t('planWizard.summaryBudget') }}</div>
          <div class="summary-value accent">¥{{ planBudget.total_estimated || 0 }}</div>
        </div>
        <div class="summary-card">
          <div class="summary-label">{{ $t('planWizard.summaryModel') }}</div>
          <div class="summary-value small">{{ result.provider }} · {{ result.model || '-' }}</div>
        </div>
      </div>

      <!-- 每日计划 -->
      <div class="day-flow">
        <div v-for="day in planDays" :key="day.day_number" class="day-card">
          <div class="day-badge">Day {{ day.day_number }}</div>
          <div class="day-content">
            <div class="day-headline">
              <h4 class="day-theme">{{ day.theme || $t('common.freeExplore') }}</h4>
              <span class="day-date">{{ day.date || '' }}</span>
            </div>
            <div class="stops">
              <div v-for="(stop, idx) in day.stops" :key="idx" class="stop">
                <span class="stop-index" :style="{ background: typeColor[stop.type] || 'var(--brand)' }">{{ idx + 1 }}</span>
                <div class="stop-main">
                  <div class="stop-name-line">
                    <span class="stop-name">{{ stop.name }}</span>
                    <el-tag size="small" round :style="{ color: typeColor[stop.type] || 'var(--brand)', background: (typeColor[stop.type] || 'var(--brand)') + '1a', border: 'none' }">
                      {{ typeEmoji[stop.type] }} {{ typeLabel[stop.type] || stop.type }}
                    </el-tag>
                  </div>
                  <div class="stop-meta">
                    <span v-if="stop.estimated_cost">¥{{ stop.estimated_cost }}</span>
                    <span v-if="stop.duration_minutes">{{ stop.duration_minutes }} {{ $t('common.minutes') }}</span>
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

      <!-- 预算明细 -->
      <div class="budget-card">
        <h4 class="budget-title">{{ $t('common.budgetTitle') }}</h4>
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
.wizard { max-width: 780px; margin: 0 auto; }
.wizard-head { margin-bottom: 24px; }
.page-title { margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); }
.page-sub { margin: 6px 0 0; font-size: 14px; color: var(--muted); }

/* ── Step 指示器 ── */
.steps { display: flex; align-items: center; margin: 8px 0 32px; }
.step { display: flex; align-items: center; gap: 8px; }
.step-num {
  width: 30px; height: 30px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--fill); color: var(--muted); font-weight: 600; font-size: 14px;
  transition: all .3s;
}
.step.active .step-num { background: var(--brand); color: #fff; box-shadow: 0 0 0 5px var(--brand-soft); }
.step.done .step-num { background: var(--success); color: #fff; }
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
  font-size: 13px; color: var(--ink-2); padding: 6px 14px;
  border-radius: var(--radius-full);
  transition: all .2s;
}
.chip:hover { border-color: var(--brand); color: var(--brand); }
.chip.picked { background: var(--brand); border-color: var(--brand); color: #fff; }
.chip.pref { display: inline-flex; align-items: center; gap: 4px; }
.pref-check { font-size: 11px; }
.date-row { display: flex; align-items: center; gap: 10px; }
.date-sep { color: var(--faint); font-size: 16px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.budget-presets { display: flex; flex-wrap: wrap; gap: 8px; margin: -8px 0 22px; }
.pref-list { display: flex; flex-wrap: wrap; gap: 8px; }

/* ── 主动提问（需求澄清） ── */
.qa-field { background: var(--fill); border-radius: var(--radius-lg); padding: 16px 18px; }
.qa-tip { font-size: 12px; color: var(--faint); font-weight: 400; margin-left: 4px; }
.qa-list { display: flex; flex-direction: column; gap: 14px; }
.qa-item { display: flex; flex-direction: column; gap: 8px; }
.qa-q { font-size: 14px; font-weight: 600; color: var(--ink); }
.qa-opts { display: flex; flex-wrap: wrap; gap: 8px; }
.qa-input { max-width: 480px; }

.btn-primary {
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--brand); color: #fff; border: none; cursor: pointer;
  font-size: 15px; font-weight: 600; padding: 13px 28px;
  border-radius: var(--radius-full);
  box-shadow: 0 4px 14px rgba(255,56,92,0.3);
  transition: all .2s;
}
.btn-primary:hover:not(:disabled) { background: var(--brand-dark); transform: translateY(-1px); box-shadow: 0 6px 20px rgba(255,56,92,0.4); }
.btn-primary:disabled { opacity: .6; cursor: not-allowed; }
.btn-primary.big { width: 100%; margin-top: 6px; font-size: 16px; padding: 14px; }

.btn-ghost {
  background: transparent; border: 1px solid var(--line); cursor: pointer;
  font-size: 14px; font-weight: 500; color: var(--ink-2);
  padding: 10px 18px; border-radius: var(--radius-full);
  transition: all .2s;
}
.btn-ghost:hover { border-color: var(--brand); color: var(--brand); }

/* ── 规划中 ── */
.planning { text-align: center; }
.planning-hero { padding: 24px 0 8px; }
.pulse-ring {
  width: 76px; height: 76px; margin: 0 auto 16px;
  border-radius: 50%; background: var(--brand-soft);
  display: flex; align-items: center; justify-content: center;
  animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255,56,92,0.25); }
  50% { box-shadow: 0 0 0 16px rgba(255,56,92,0); }
}
.planning-hero h3 { margin: 0 0 6px; font-size: 18px; color: var(--ink); }
.planning-sub { margin: 0; font-size: 13px; color: var(--muted); }
.planning-wait { margin-top: 20px; color: var(--faint); font-size: 13px; }
.dots span { animation: blink 1.4s infinite; }
.dots span:nth-child(2) { animation-delay: .2s; }
.dots span:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%,100% { opacity: .2; } 50% { opacity: 1; } }

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
  background: linear-gradient(135deg, var(--brand-soft), #fff);
  border: 1px solid #ffdbe0; border-radius: var(--radius-lg);
  padding: 20px 24px; margin-bottom: 20px;
}
.success-icon {
  width: 60px; height: 60px; border-radius: 50%; flex-shrink: 0;
  background: var(--brand); display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 18px rgba(255,56,92,0.35);
}
.success-title { margin: 0 0 4px; font-size: 18px; color: var(--ink); }
.success-sub { margin: 0; font-size: 13px; color: var(--muted); }
.success-actions { margin-left: auto; display: flex; gap: 10px; }

.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
.summary-card {
  background: var(--fill); border-radius: var(--radius-md); padding: 14px 16px;
}
.summary-label { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.summary-value { font-size: 18px; font-weight: 700; color: var(--ink); }
.summary-value.accent { color: var(--brand); }
.summary-value.small { font-size: 13px; font-weight: 500; }

.day-flow { display: flex; flex-direction: column; gap: 16px; margin-bottom: 24px; }
.day-card {
  display: flex; gap: 16px; border: 1px solid var(--line);
  border-radius: var(--radius-lg); padding: 20px; background: #fff;
}
.day-badge {
  flex-shrink: 0; width: 64px; height: 64px; border-radius: var(--radius-md);
  background: var(--ink); color: #fff; display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 14px; letter-spacing: 0.02em;
}
.day-content { flex: 1; min-width: 0; }
.day-headline { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 14px; }
.day-theme { margin: 0; font-size: 16px; font-weight: 600; color: var(--ink); }
.day-date { font-size: 12.5px; color: var(--faint); }
.stops { display: flex; flex-direction: column; gap: 12px; }
.stop { display: flex; gap: 12px; }
.stop-index {
  width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0;
  color: #fff; font-size: 12px; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
}
.stop-main { flex: 1; min-width: 0; }
.stop-name-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.stop-name { font-size: 14.5px; font-weight: 600; color: var(--ink); }
.stop-meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: 12.5px; color: var(--muted); margin-top: 4px; }
.stop-desc { color: var(--faint); }

.budget-card {
  border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 20px 24px; margin-bottom: 20px; background: #fff;
}
.wizard-hotel { margin-bottom: 20px; }
.wizard-quality { margin-bottom: 20px; }
.budget-title { margin: 0 0 16px; font-size: 15px; font-weight: 600; color: var(--ink); }
.budget-bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.budget-bar-label { width: 40px; font-size: 13px; color: var(--muted); }
.budget-bar-track { flex: 1; height: 8px; border-radius: var(--radius-full); background: var(--fill); overflow: hidden; }
.budget-bar-fill { height: 100%; border-radius: var(--radius-full); transition: width .6s ease; }
.budget-bar-value { width: 64px; text-align: right; font-size: 13px; font-weight: 600; color: var(--ink); }
.budget-total-row {
  display: flex; justify-content: space-between; align-items: center;
  border-top: 1px solid var(--line); padding-top: 12px; margin-top: 6px;
  font-size: 14px; color: var(--muted);
}
.budget-total { font-size: 18px; font-weight: 700; color: var(--brand); }

.trace-collapse { border: none; }
.trace-collapse :deep(.el-collapse-item__header) { border: none; font-size: 13px; color: var(--muted); }

/* 响应式 */
@media (max-width: 720px) {
  .panel { padding: 24px 20px; }
  .two-col { grid-template-columns: 1fr; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
  .day-card { flex-direction: column; }
  .success-actions { margin-left: 0; width: 100%; }
}
</style>