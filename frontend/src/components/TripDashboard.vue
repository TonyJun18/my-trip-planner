<template>
  <div class="trip-dashboard">
    <!-- 预算环 -->
    <div class="dash-section" v-if="budget">
      <div class="dash-head">
        <span class="dash-title">{{ t('common.budgetTitle') }}</span>
        <span v-if="budgetPercent != null" class="dash-sub" :class="{ over: budgetPercent > 100 }">
          {{ budgetPercent > 100 ? '+' : '' }}{{ budgetPercent }}%
        </span>
      </div>
      <div class="dash-budget">
        <div class="budget-ring-mini" :style="{ '--pct': Math.min(100, +(budgetPercent || 0)) }">
          <div class="budget-ring-mini-inner">
            <div class="mini-total">¥{{ budget.total_estimated }}</div>
            <div class="mini-label">{{ t('common.estimated') }}</div>
          </div>
        </div>
        <div class="budget-meta">
          <div class="budget-meta-line" v-if="tripBudget != null">
            <span class="meta-k">{{ t('common.budget') }}</span>
            <span class="meta-v">¥{{ tripBudget }}</span>
          </div>
          <div class="budget-meta-line" v-if="budget.daily_average">
            <span class="meta-k">{{ t('common.dailyAvgShort') }}</span>
            <span class="meta-v">¥{{ budget.daily_average }}</span>
          </div>
          <div class="budget-meta-line" v-if="budget.per_person_total != null && travelers > 1">
            <span class="meta-k">{{ t('common.perPersonShort') }}</span>
            <span class="meta-v">¥{{ budget.per_person_total }}</span>
          </div>
        </div>
      </div>
      <div class="budget-lines-mini">
        <div v-for="(label, k) in typeLabels" :key="k" class="budget-line-mini">
          <span class="budget-dot" :style="{ background: typeColor[k] }" />
          <span>{{ label }}</span>
          <span class="budget-line-val">¥{{ budget.by_type?.[k] || 0 }}</span>
        </div>
      </div>
      <div v-if="basisText" class="budget-basis-mini" :title="basisText">
        <el-icon :size="12"><InfoFilled /></el-icon>
        <span class="basis-link">{{ t('share.basisLabel') }}</span>
      </div>
    </div>

    <!-- 追踪摘要 -->
    <div class="dash-section">
      <div class="dash-head">
        <span class="dash-title">{{ t('journey.panelTitle') }}</span>
        <el-tag v-if="phase" size="small" :type="phaseTagType" effect="light">{{ phaseLabel }}</el-tag>
      </div>
      <div v-if="totalStops > 0" class="dash-progress">
        <el-progress
          :percentage="Math.round(progress)"
          :stroke-width="8"
          :format="() => `${completedStops}/${totalStops}`"
        />
      </div>
      <div v-else class="dash-empty">{{ t('journey.noStops') }}</div>

      <!-- 统计：费用 / 预订 / 徽章 -->
      <div class="dash-stats">
        <div class="dash-stat" v-if="expenseTotal > 0">
          <div class="dash-stat-val">¥{{ expenseTotal.toFixed(0) }}</div>
          <div class="dash-stat-label">{{ t('journey.expenseTotal') }}</div>
        </div>
        <div class="dash-stat">
          <div class="dash-stat-val">{{ bookingCount }}</div>
          <div class="dash-stat-label">{{ t('journey.bookingCount') }}</div>
        </div>
        <div class="dash-stat">
          <div class="dash-stat-val">{{ badgeCount }}</div>
          <div class="dash-stat-label">{{ t('passport.panelTitle') }}</div>
        </div>
      </div>

      <!-- 按天状态速览 -->
      <div v-if="days.length" class="dash-days">
        <div
          v-for="day in days"
          :key="day.day_number"
          class="dash-day"
          :class="`day-${day.status}`"
          :title="dayStatusLabel(day.status)"
        >
          <span class="dash-day-num">D{{ day.day_number }}</span>
          <span v-if="day.total" class="dash-day-count">{{ day.completed }}/{{ day.total }}</span>
        </div>
      </div>

      <div v-if="!dataComplete" class="dash-incomplete">{{ t('journey.incomplete') }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { InfoFilled } from '@element-plus/icons-vue'
import { getJourney, getPassport } from '../api'

const props = defineProps({
  tripId: { type: String, required: true },
  // 预算（父组件已拉取，避免重复请求）
  budget: { type: Object, default: null },
  budgetPercent: { type: Number, default: null },
  basisText: { type: String, default: '' },
  tripBudget: { type: Number, default: null },
  travelers: { type: Number, default: 1 },
})

const { t } = useI18n()
const journey = ref(null)
const passport = ref(null)

const typeLabels = computed(() => ({
  attraction: t('common.typeAttraction'),
  food: t('common.typeFood'),
  hotel: t('common.typeHotel'),
  transport: t('common.typeTransport'),
}))
const typeColor = { attraction: 'var(--brand)', food: '#c2410c', hotel: '#0d8a5f', transport: '#5b6ee1' }

// ── 追踪投影 ──
const phase = computed(() => journey.value?.phase || '')
const phaseLabel = computed(() => {
  const map = {
    upcoming: t('journey.phase.upcoming'),
    live: t('journey.phase.live'),
    finished: t('journey.phase.finished'),
  }
  return map[phase.value] || phase.value
})
const phaseTagType = computed(() => ({ live: 'success', finished: 'info', upcoming: 'warning' }[phase.value] || 'info'))
const progress = computed(() => journey.value?.journey_progress || 0)
const completedStops = computed(() => journey.value?.completed_stops || 0)
const totalStops = computed(() => journey.value?.total_stops || 0)
const days = computed(() => journey.value?.days || [])
const expenseTotal = computed(() => journey.value?.expense_total || 0)
const bookingCount = computed(() => {
  const bs = journey.value?.booking_status || {}
  return (bs.confirmed || 0) + (bs.pending || 0)
})
const dataComplete = computed(() => journey.value?.data_complete ?? true)

// ── 护照徽章 ──
const badgeCount = computed(() => passport.value?.badge_count || 0)

function dayStatusLabel(s) {
  return t(`journey.dayStatus.${s}`) || s
}

async function load() {
  try {
    const [j, p] = await Promise.all([
      getJourney(props.tripId),
      getPassport(props.tripId),
    ])
    journey.value = j
    passport.value = p
  } catch {
    // 仪表盘是可选的，失败不影响详情页
  }
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.trip-dashboard { display: flex; flex-direction: column; gap: 14px; }

.dash-section {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}
.dash-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.dash-title { font-size: 14px; font-weight: 600; color: var(--ink); }
.dash-sub { font-size: 12px; font-weight: 600; color: var(--success); }
.dash-sub.over { color: var(--danger); }

/* 预算 */
.dash-budget { display: flex; align-items: center; gap: 14px; margin-bottom: 10px; }
.budget-ring-mini {
  --pct: 0;
  width: 76px; height: 76px; flex-shrink: 0;
  border-radius: 50%;
  background: conic-gradient(var(--brand) calc(var(--pct) * 1%), var(--fill) 0);
  display: flex; align-items: center; justify-content: center;
}
.budget-ring-mini-inner {
  width: 56px; height: 56px; border-radius: 50%; background: #fff;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
}
.mini-total { font-size: 13px; font-weight: 700; color: var(--ink); }
.mini-label { font-size: 10px; color: var(--faint); }
.budget-meta { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.budget-meta-line { display: flex; justify-content: space-between; font-size: 12px; color: var(--ink-2); }
.meta-k { color: var(--faint); }
.meta-v { font-weight: 600; color: var(--ink); }

.budget-lines-mini { display: flex; flex-direction: column; gap: 3px; }
.budget-line-mini { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-2); }
.budget-dot { width: 7px; height: 7px; border-radius: 50%; }
.budget-line-val { margin-left: auto; font-weight: 600; color: var(--ink); }
.budget-basis-mini {
  margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--line);
  display: flex; align-items: center; gap: 4px;
  font-size: 11px; color: var(--muted);
}

/* 追踪 */
.dash-empty { font-size: 12px; color: var(--faint); padding: 4px 0; }
.dash-progress { margin-bottom: 10px; }
.dash-stats { display: flex; gap: 8px; margin: 10px 0 6px; }
.dash-stat {
  flex: 1; text-align: center;
  background: var(--fill); border-radius: var(--radius-md);
  padding: 8px 4px;
}
.dash-stat-val { font-size: 16px; font-weight: 700; color: var(--ink); }
.dash-stat-label { font-size: 10.5px; color: var(--muted); margin-top: 2px; }

.dash-days { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.dash-day {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; padding: 3px 8px;
  border-radius: 999px;
  background: var(--fill); color: var(--muted);
}
.dash-day.day-completed { background: rgba(16,185,129,.12); color: var(--success); }
.dash-day.day-partial { background: rgba(250,204,21,.14); color: #b45309; }
.dash-day.day-skipped { opacity: .5; text-decoration: line-through; }
.dash-day-num { font-weight: 600; }
.dash-incomplete { margin-top: 8px; font-size: 11px; color: var(--warning); }
</style>