<template>
  <div class="journey-timeline">
    <div class="journey-header">
      <span class="journey-title">{{ t('journey.panelTitle') }}</span>
      <el-tag v-if="phase === 'live'" size="small" type="success" effect="light">
        {{ t('journey.phase.live') }}
      </el-tag>
      <el-tag v-else-if="phase === 'finished'" size="small" type="info" effect="light">
        {{ t('journey.phase.finished') }}
      </el-tag>
      <el-tag v-else size="small" type="warning" effect="light">
        {{ t('journey.phase.upcoming') }}
      </el-tag>
    </div>

    <!-- 进度 -->
    <div class="journey-progress" v-if="totalStops > 0">
      <el-progress
        :percentage="Math.round(progress)"
        :stroke-width="10"
        :format="() => `${completedStops}/${totalStops}`"
      />
    </div>
    <div v-else class="journey-empty">{{ t('journey.noStops') }}</div>

    <!-- 费用汇总 -->
    <div class="journey-stats" v-if="expenseTotal > 0 || bookingCount > 0">
      <div class="stat-item">
        <div class="stat-value">{{ expenseTotal.toFixed(2) }}</div>
        <div class="stat-label">{{ t('journey.expenseTotal') }}</div>
      </div>
      <div class="stat-item" v-if="perPerson > 0">
        <div class="stat-value">{{ perPerson.toFixed(2) }}</div>
        <div class="stat-label">{{ t('journey.perPerson') }}</div>
      </div>
      <div class="stat-item">
        <div class="stat-value">{{ bookingCount }}</div>
        <div class="stat-label">{{ t('journey.bookingCount') }}</div>
      </div>
    </div>

    <!-- 按天列表 -->
    <div v-if="days.length" class="journey-days">
      <div v-for="day in days" :key="day.day_number" class="journey-day" :class="`day-${day.status}`">
        <div class="journey-day-head">
          <span class="journey-day-num">{{ t('journey.day', { n: day.day_number }) }}</span>
          <span v-if="day.date" class="journey-day-date">{{ day.date }}</span>
          <el-tag size="small" :type="dayTagType(day.status)" effect="plain" class="journey-day-status">
            {{ dayStatusLabel(day.status) }}
          </el-tag>
          <span v-if="day.total" class="journey-day-count">{{ day.completed }}/{{ day.total }}</span>
        </div>
        <div v-if="day.highlights && day.highlights.length" class="journey-day-highlights">
          <div v-for="(h, i) in day.highlights" :key="i" class="journey-highlight">· {{ h }}</div>
        </div>
      </div>
    </div>

    <!-- 数据完整提示 -->
    <div v-if="!dataComplete" class="journey-incomplete">
      {{ t('journey.incomplete') }}
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getJourney } from '../api'

const props = defineProps({
  tripId: { type: String, required: true },
})

const { t } = useI18n()
const journey = ref(null)

const phase = computed(() => journey.value?.phase || 'upcoming')
const progress = computed(() => journey.value?.journey_progress || 0)
const completedStops = computed(() => journey.value?.completed_stops || 0)
const totalStops = computed(() => journey.value?.total_stops || 0)
const days = computed(() => journey.value?.days || [])
const expenseTotal = computed(() => journey.value?.expense_total || 0)
const perPerson = computed(() => journey.value?.per_person || 0)
const bookingCount = computed(() => {
  const bs = journey.value?.booking_status || {}
  return (bs.suggested || 0) + (bs.pending || 0) + (bs.confirmed || 0)
})
const dataComplete = computed(() => journey.value?.data_complete !== false)

function dayStatusLabel(s) {
  const map = {
    completed: t('journey.dayStatus.completed'),
    partial: t('journey.dayStatus.partial'),
    todo: t('journey.dayStatus.todo'),
    skipped: t('journey.dayStatus.skipped'),
  }
  return map[s] || s
}
function dayTagType(s) {
  if (s === 'completed') return 'success'
  if (s === 'partial') return 'primary'
  if (s === 'skipped') return 'info'
  return 'info'
}

async function load() {
  try {
    journey.value = await getJourney(props.tripId)
  } catch (e) {
    // 静默：追踪是可选的，失败不影响详情页
  }
}

onMounted(load)

defineExpose({ load })
</script>

<style scoped>
.journey-timeline {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px;
}
.journey-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.journey-title {
  font-weight: 600;
  font-size: 15px;
}
.journey-progress {
  margin-bottom: 10px;
}
.journey-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  padding: 10px 0;
}
.journey-stats {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.stat-value {
  font-size: 18px;
  font-weight: 600;
  color: var(--el-color-primary);
}
.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.journey-days {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.journey-day {
  border-left: 3px solid var(--el-border-color);
  padding: 6px 10px;
  border-radius: 4px;
}
.journey-day.day-completed {
  border-left-color: var(--el-color-success);
}
.journey-day.day-partial {
  border-left-color: var(--el-color-primary);
}
.journey-day.day-skipped {
  border-left-color: var(--el-color-info);
  opacity: 0.6;
}
.journey-day-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.journey-day-num {
  font-weight: 600;
}
.journey-day-date {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.journey-day-status {
  margin-left: auto;
}
.journey-day-count {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.journey-day-highlights {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.journey-highlight {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.journey-incomplete {
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-color-warning);
}
</style>