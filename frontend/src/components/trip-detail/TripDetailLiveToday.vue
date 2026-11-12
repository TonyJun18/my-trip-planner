<script setup>
// 行中「今日视图」（live 期间；打卡/跳过/迟到顺延）—— 全宽置顶，随时可操作
// 天气卡（task-weather-card-frontend）：后端 LiveSnapshotOut.weather 早已透出
// （{date, text_day, temp_min, temp_max, source, advice}），本组件负责渲染；
// 无数据 → 整行不渲染（预报非事实，绝不伪造；对齐 Kiara/Journelyx「诚实沉默」）。
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  live: { type: Object, required: true },
  liveOp: { type: String, default: '' },
  typeEmoji: { type: Object, required: true },
  typeLabel: { type: Object, required: true },
})

const emit = defineEmits(['check', 'skip', 'delay', 'add-expense', 'frame-card'])
const { t } = useI18n()

const weather = computed(() => props.live?.weather || null)
const weatherEmoji = computed(() => {
  const advice = weather.value?.advice || []
  if (advice.includes('rain')) return '🌧'
  if (advice.includes('hot')) return '🔥'
  const text = weather.value?.text_day || ''
  if (text.includes('雪')) return '❄️'
  if (text.includes('云') || text.includes('阴')) return '⛅'
  return '☀️'
})
const weatherTemp = computed(() => {
  const w = weather.value
  if (!w) return ''
  const { temp_min: lo, temp_max: hi } = w
  if (lo != null && hi != null) return `${lo}~${hi}°C`
  if (hi != null) return `${hi}°C`
  return ''
})
const weatherAdviceText = computed(() =>
  (weather.value?.advice || [])
    .map((code) => t(`tripDetail.weatherAdvice.${code}`))
    .filter(Boolean)
    .join(' · '),
)
// 降水概率（task-weather-probability-card）：wttr 源透出当天最大 chanceofrain
// （{rain_probability}）；高德源无概率字段 → null → 前端不渲染（诚实沉默）。
const weatherRainText = computed(() => {
  const p = weather.value?.rain_probability
  if (p == null) return ''
  return t('tripDetail.weatherRainProb', { p })
})
</script>

<template>
  <div v-if="live && live.phase === 'live'" class="live-card">
    <div class="live-head">
      <div>
        <div class="live-title">📅 {{ $t('tripDetail.liveTodayTitle') }}</div>
        <div class="live-sub">{{ $t('tripDetail.liveTodaySub', { day: live.day_number, date: live.date }) }}</div>
      </div>
      <div class="live-progress">
        <span class="live-progress-num">{{ live.completed }}/{{ live.total }}</span>
        <el-progress
          :percentage="live.total ? Math.round((live.completed / live.total) * 100) : 0"
          :stroke-width="6"
          :show-text="false"
          style="width: 90px"
        />
      </div>
    </div>

    <div v-if="weather" class="live-weather" :class="{ wet: (weather.advice || []).includes('rain'), hot: (weather.advice || []).includes('hot') }">
      <span class="live-weather-emoji">{{ weatherEmoji }}</span>
      <span class="live-weather-text">
        {{ weather.text_day || $t('tripDetail.weatherNoData') }}
        <template v-if="weatherTemp"> · {{ weatherTemp }}</template>
        <template v-if="weatherRainText"> · {{ weatherRainText }}</template>
      </span>
      <span class="live-weather-badge">{{ $t('tripDetail.weatherForecastBadge') }}</span>
      <span v-if="weatherAdviceText" class="live-weather-advice">{{ weatherAdviceText }}</span>
    </div>

    <div class="live-stops">
      <div v-for="stop in live.stops" :key="stop.id" class="live-stop" :class="{ done: stop.checked }">
        <el-checkbox
          :model-value="stop.checked"
          :disabled="!!liveOp"
          @change="(v) => emit('check', stop, v)"
        />
        <div class="live-stop-info">
          <div class="live-stop-name" :class="{ muted: stop.checked }">{{ stop.name }}</div>
          <div class="live-stop-type">
            <!-- 时刻徽标（schedule_service 注入派生时刻；缺失时兜底只显示类型） -->
            <span
              v-if="stop.visit_start"
              class="live-stop-time"
              :class="{ 'live-stop-time-transfer': stop.is_transfer }"
            >{{ stop.is_transfer ? '🚄' : '🕐' }} {{ stop.stop_type === 'hotel' ? $t('tripDetail.checkinAt', { t: stop.visit_start }) : stop.visit_start + (stop.visit_end && stop.visit_end !== stop.visit_start ? '–' + stop.visit_end : '') }}</span>
            {{ typeEmoji[stop.stop_type] }} {{ typeLabel[stop.stop_type] || stop.stop_type }}
          </div>
        </div>
        <div class="live-stop-actions">
          <el-button size="small" text type="danger" :disabled="!!liveOp" @click="emit('skip', stop)">
            {{ $t('tripDetail.liveSkip') }}
          </el-button>
        </div>
      </div>
    </div>

    <div class="live-footer">
      <el-button size="small" type="primary" plain @click="emit('add-expense')">
        💸 {{ $t('expense.add') }}
      </el-button>
      <el-button
        size="small"
        type="success"
        plain
        :disabled="!live.completed"
        @click="emit('frame-card')"
      >
        🖼️ {{ $t('frames.dialog.title') }}
      </el-button>
      <el-button size="small" type="warning" plain :loading="liveOp === 'delay'" @click="emit('delay')">
        {{ $t('tripDetail.liveDelay') }}
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.live-card {
  margin-bottom: 18px;
  border: 1.5px solid var(--brand);
  border-radius: var(--radius-lg);
  padding: 16px 18px;
  background: linear-gradient(180deg, var(--card), transparent);
  box-shadow: var(--shadow-sm);
}
.live-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.live-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
}
.live-sub {
  font-size: 12.5px;
  color: var(--muted);
  margin-top: 2px;
}
.live-progress {
  display: flex;
  align-items: center;
  gap: 10px;
}
.live-progress-num {
  font-size: 14px;
  font-weight: 700;
  color: var(--brand);
}
/* 天气卡（task-weather-card-frontend）：预报徽标 + 行动建议；无数据整行不渲染 */
.live-weather {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
  padding: 8px 12px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-md);
  background: var(--card);
  font-size: 13px;
  color: var(--ink);
}
.live-weather.wet {
  border-color: #7bb0d6;
  background: rgba(123, 176, 214, 0.08);
}
.live-weather.hot {
  border-color: #e0a458;
  background: rgba(224, 164, 88, 0.1);
}
.live-weather-emoji {
  font-size: 15px;
  line-height: 1;
}
.live-weather-text {
  font-weight: 600;
}
.live-weather-badge {
  font-size: 11px;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 1px 6px;
}
.live-weather-advice {
  font-size: 12.5px;
  color: var(--muted);
}
.live-stops {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.live-stop {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--card);
}
.live-stop.done {
  opacity: 0.6;
}
.live-stop-info {
  flex: 1;
  min-width: 0;
}
.live-stop-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}
.live-stop-name.muted {
  text-decoration: line-through;
  color: var(--muted);
}
.live-stop-type {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}
/* 时刻徽标：今日站点行内的派生时刻 */
.live-stop-time {
  font-weight: 600;
  color: var(--ink-2, #333);
  font-variant-numeric: tabular-nums;
  margin-right: 6px;
}
.live-stop-time-transfer {
  color: #6d28d9;
}
.live-stop-actions {
  flex-shrink: 0;
}
.live-footer {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 640px) {
  .live-head {
    flex-direction: column;
    align-items: flex-start;
  }
  .live-progress {
    width: 100%;
    justify-content: space-between;
  }
}

@media print {
  .live-card {
    display: none !important;
  }
}
</style>