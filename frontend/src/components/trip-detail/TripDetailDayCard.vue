<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { MapLocation, MoreFilled, ArrowDown, EditPen, Delete, Wallet, Clock, Sort } from '@element-plus/icons-vue'
import { useTripTypes } from '@/composables/useTripTypes'
import DayNavButton from '@/components/trip-detail/DayNavButton.vue'

// 逐日行程卡：Day 头（折叠开关 + 摘要 + 地图聚焦）+ 站点时间轴 + 站点操作
//
// 折叠设计（解决「10 天行程 = 10 屏」）：
// - 收起时 Day 头一行给出「N 站 · ¥总计 · 总时长」，信息不丢、页面密度大增
// - 展开/收起是主操作（点 Day 头即切换），地图聚焦降级为独立图标按钮
const props = defineProps({
  day: { type: Object, required: true },
  activeDay: { type: [Number, null], default: null },
  dayIndex: { type: Number, default: 0 },
  // 受控展开态（orchestrator 持有：默认只开当天/第一天，导出时全开）
  open: { type: Boolean, default: true },
  // 「按最优顺序重排」进行中（task-auto-optimize-cta：按钮 loading + 防重复点击）
  optimizing: { type: Boolean, default: false },
  // 重排失败的内联提示（约束未通过时展示在卡片内，而不是全局 toast）
  optimizeError: { type: String, default: '' },
  // 已确认预订（task-booking-ledger-rhythm：按 service_date 投影到所在日，父组件过滤传入）
  confirmedBookings: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'focus-day', 'toggle-open', 'add-stop', 'day-cmd', 'stop-cmd', 'stop-edit', 'optimize-order',
])

const { typeLabel, typeColor, typeEmoji } = useTripTypes()
const { t } = useI18n()

const isActive = computed(() => props.activeDay === props.day.day_number)
const hasStops = computed(() => (props.day.stops || []).length > 0)

const totalCost = computed(() =>
  (props.day.stops || []).reduce((sum, s) => sum + (Number(s.estimated_cost) || 0), 0),
)
const totalMinutes = computed(() =>
  (props.day.stops || []).reduce((sum, s) => sum + (Number(s.estimated_duration_minutes) || 0), 0),
)

const durationText = computed(() => {
  const m = totalMinutes.value
  if (!m) return ''
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const rest = m % 60
  return rest ? `${h}h${rest}m` : `${h}h`
})

// ── 时间轴派生时刻（schedule_service 读取路径注入；缺失时回退无时刻渲染）──
// 日窗口 = 首站 visit_start → 末站 visit_end；跨夜（end=24:00）或跨度 >12h → 过载高亮。
const stops = computed(() => props.day.stops || [])
const hasSchedule = computed(() => stops.value.some((s) => s.visit_start))

function toMinutes(hhmm) {
  if (!hhmm) return null
  const [h, m] = hhmm.split(':').map(Number)
  if (Number.isNaN(h) || Number.isNaN(m)) return null
  return h * 60 + m
}

const dayWindow = computed(() => {
  if (!hasSchedule.value) return null
  const first = stops.value.find((s) => s.visit_start)
  const last = [...stops.value].reverse().find((s) => s.visit_end)
  if (!first || !last) return null
  const start = toMinutes(first.visit_start)
  const end = toMinutes(last.visit_end)
  if (start == null || end == null) return null
  return {
    text: `${first.visit_start} → ${last.visit_end}`,
    span: Math.max(0, end - start),
    overflow: end >= 24 * 60 || end - start > 720,
  }
})

// 段间交通样式：纯时长口径（前端无距离数据，阈值对应 servicing 距离档的常见耗时）
function travelMeta(prevStop) {
  const m = prevStop?.travel_to_next_minutes
  if (!m || m <= 0) return null
  const emoji = m <= 15 ? '🚶' : m <= 45 ? '🚌' : '🚕'
  return { emoji, text: `${t('tripDetail.travelGap', { n: m })}` }
}

// 收起态摘要：站数 · 花费 · 时长（缺项自动省略，不占位）
const summary = computed(() => {
  if (!hasStops.value) return ''
  return [
    t('tripDetail.dayStops', { n: props.day.stops.length }),
    totalCost.value ? `¥${totalCost.value}` : '',
    // 时间窗口优先于裸时长（17h30m 这种数字无法一眼判断是否过载）
    dayWindow.value && !dayWindow.value.overflow ? dayWindow.value.text : durationText.value,
    dayWindow.value?.overflow ? t('tripDetail.dayOverflowBadge') : '',
  ].filter(Boolean).join(' · ')
})

function toggle() {
  if (!hasStops.value) return
  emit('toggle-open', props.day)
}

// 订单徽标（task-booking-ledger-rhythm）：已确认预订按 service_date 投影到日卡片
const BOOKING_EMOJI = { train: '🚄', flight: '✈️', hotel: '🏨', ticket: '🎫' }
const PROVIDER_LABEL = {
  ctrip: '携程', qunar: '去哪儿', '12306': '12306',
  feizhu: '飞猪', tongcheng: '同程', trip: 'Trip',
}
function bookingBadgeText(b) {
  const kind = t(`booking.kind.${b.kind}`)
  const provider = b.provider === 'manual' ? t('booking.provider.manual') : PROVIDER_LABEL[b.provider] || b.provider
  return `${BOOKING_EMOJI[b.kind] || '🎫'} ${kind} · ${provider}`
}
</script>

<template>
  <div class="day-section day-card" :class="{ 'day-active': isActive, 'is-collapsed': !open }">
    <div class="day-head">
      <button
        class="day-headline"
        :class="{ clickable: hasStops }"
        type="button"
        :aria-expanded="open"
        @click="toggle"
      >
        <span class="day-badge" :class="{ 'day-badge-active': isActive }">D{{ day.day_number }}</span>
        <span class="day-head-text">
          <span class="day-title-row">
            <span class="day-title">{{ day.date || $t('common.dayN', { n: day.day_number }) }}</span>
            <span v-if="summary && !open" class="day-summary">{{ summary }}</span>
          </span>
          <!-- 展开态日头时间窗口（派生时刻存在时） -->
          <span v-if="open && dayWindow && day.stops.length >= 2" class="day-window" :class="{ 'day-window-overflow': dayWindow.overflow }">
            <el-icon><Clock /></el-icon>{{ dayWindow.text }}
            <el-tooltip v-if="dayWindow.overflow" :content="$t('tripDetail.dayOverflowHint')" placement="top" :show-after="200">
              <span class="day-window-overflow-badge">⚠ {{ $t('tripDetail.dayOverflowBadge') }}</span>
            </el-tooltip>
          </span>
          <span class="day-note">{{ day.note || $t('common.freeExplore') }}</span>
          <span v-if="confirmedBookings.length" class="day-booking-badges">
            <el-tag
              v-for="b in confirmedBookings"
              :key="b.id"
              size="small"
              type="success"
              effect="plain"
              class="day-booking-badge"
            >
              {{ bookingBadgeText(b) }}
            </el-tag>
          </span>
        </span>
        <el-icon v-if="hasStops" class="day-chevron" :class="{ open }"><ArrowDown /></el-icon>
      </button>

      <div class="day-actions">
        <DayNavButton :stops="day.stops || []" />
        <el-tooltip :content="$t('tripDetail.mapFocusHint')" placement="top" :show-after="400">
          <el-button
            size="small"
            plain
            circle
            :class="{ 'focus-on': isActive }"
            :disabled="!hasStops"
            :aria-label="$t('tripDetail.mapFocusHint')"
            @click="emit('focus-day', day.day_number)"
          ><el-icon><MapLocation /></el-icon></el-button>
        </el-tooltip>
        <el-tooltip :content="$t('tripDetail.optimizeOrderHint')" placement="top" :show-after="400">
          <el-button
            v-if="hasStops && (day.stops || []).length >= 3"
            size="small"
            plain
            :loading="optimizing"
            @click="emit('optimize-order', day)"
          >
            <el-icon style="margin-right: 4px"><Sort /></el-icon>{{ $t('tripDetail.optimizeOrder') }}
          </el-button>
        </el-tooltip>
        <el-button size="small" type="primary" plain @click="emit('add-stop', day.id)">+ {{ $t('tripDetail.addStop') }}</el-button>
        <el-dropdown trigger="click" @command="(cmd) => emit('day-cmd', day, cmd)">
          <el-button size="small" plain circle :aria-label="$t('tripDetail.dayActions')">
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

    <!-- 重排失败内联提示（约束未通过时留在卡片内，不打断页面） -->
    <p v-if="optimizeError" class="optimize-error">{{ optimizeError }}</p>

    <!-- 站点时间轴（折叠动画） -->
    <el-collapse-transition>
      <div v-show="open" class="stops-wrap">
        <div class="stops-list" v-if="hasStops">
          <div v-for="(stop, idx) in day.stops" :key="stop.id" class="stop-item">
            <div class="stop-rail">
              <span class="stop-index" :style="{ background: typeColor[stop.stop_type] || 'var(--brand)' }">{{ idx + 1 }}</span>
              <span class="rail-line" v-if="idx < day.stops.length - 1" />
            </div>
            <div class="stop-body">
              <!-- 段间交通 chip（来自上一站的 travel_to_next_minutes） -->
              <div v-if="idx > 0 && travelMeta(day.stops[idx - 1])" class="stop-travel-chip">
                {{ travelMeta(day.stops[idx - 1]).emoji }} {{ travelMeta(day.stops[idx - 1]).text }}
              </div>
              <div class="stop-head">
                <span class="stop-name" @click.stop="emit('stop-edit', day, stop)">{{ stop.name }}</span>
                <div class="stop-head-right">
                  <div class="stop-quick">
                    <el-button
                      v-if="idx > 0"
                      link
                      circle
                      size="small"
                      :title="$t('tripDetail.moveUp')"
                      :aria-label="$t('tripDetail.moveUp')"
                      @click.stop="emit('stop-cmd', day, stop, idx, 'up')"
                    ><el-icon><ArrowDown class="icon-up" /></el-icon></el-button>
                    <el-button
                      v-if="idx < day.stops.length - 1"
                      link
                      circle
                      size="small"
                      :title="$t('tripDetail.moveDown')"
                      :aria-label="$t('tripDetail.moveDown')"
                      @click.stop="emit('stop-cmd', day, stop, idx, 'down')"
                    ><el-icon><ArrowDown /></el-icon></el-button>
                    <el-button
                      link
                      circle
                      size="small"
                      :title="$t('tripDetail.editStop')"
                      :aria-label="$t('tripDetail.editStop')"
                      @click.stop="emit('stop-edit', day, stop)"
                    ><el-icon><EditPen /></el-icon></el-button>
                    <el-dropdown trigger="click" @click.stop @command="(cmd) => emit('stop-cmd', day, stop, idx, cmd)">
                      <el-button link circle size="small" :aria-label="$t('tripDetail.stopActions')">
                        <el-icon><MoreFilled /></el-icon>
                      </el-button>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item command="up" :disabled="idx === 0">{{ $t('tripDetail.moveUp') }}</el-dropdown-item>
                          <el-dropdown-item command="down" :disabled="idx === day.stops.length - 1">{{ $t('tripDetail.moveDown') }}</el-dropdown-item>
                          <el-dropdown-item command="delete" divided class="detail-dropdown-danger">{{ $t('tripDetail.deleteStop') }}</el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                  </div>
                  <el-tag size="small" round :style="{ color: typeColor[stop.stop_type] || 'var(--brand)', background: (typeColor[stop.stop_type] || 'var(--brand)') + '1a', border: 'none' }">
                    {{ typeEmoji[stop.stop_type] }} {{ typeLabel[stop.stop_type] || stop.stop_type }}
                  </el-tag>
                </div>
              </div>
              <div class="stop-meta">
                <!-- 时刻徽标：住宿站=「入住 HH:MM」；交通占位站=🚄；普通站=起止时刻 -->
                <span v-if="stop.visit_start && stop.stop_type === 'hotel'" class="stop-time stop-time-hotel">
                  <el-icon><Clock /></el-icon>{{ $t('tripDetail.checkinAt', { t: stop.visit_start }) }}
                </span>
                <span v-else-if="stop.visit_start && stop.is_transfer" class="stop-time stop-time-transfer">🚄 {{ stop.visit_start }}</span>
                <span v-else-if="stop.visit_start && stop.visit_start !== stop.visit_end" class="stop-time">
                  <el-icon><Clock /></el-icon>{{ stop.visit_start }}–{{ stop.visit_end }}
                </span>
                <span v-if="stop.estimated_cost != null"><el-icon><Wallet /></el-icon>¥{{ stop.estimated_cost }}</span>
                <span v-if="stop.estimated_duration_minutes && stop.stop_type !== 'hotel'"><el-icon><Clock /></el-icon>{{ stop.estimated_duration_minutes }} {{ $t('common.minutes') }}</span>
              </div>
              <div v-if="stop.description" class="stop-desc">{{ stop.description }}</div>
            </div>
          </div>
        </div>
        <el-empty v-else :description="$t('common.dayEmpty')" :image-size="60" />
      </div>
    </el-collapse-transition>
  </div>
</template>

<style scoped>
.day-section {
  margin-bottom: 24px;
}
.day-section.day-card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 12px 16px;
  margin-bottom: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
  transition: border-color 0.2s, box-shadow 0.2s, padding 0.2s;
}
.day-card.day-active {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft), var(--shadow-card);
}
.day-card:hover {
  border-color: var(--el-color-primary-light-8);
  box-shadow: var(--shadow-hover);
}
/* 收起态：更紧凑的头部，视觉上像大纲条目而不是卡片 */
.day-card.is-collapsed { padding: 8px 14px; }

/* 重排失败内联提示（约束未通过）：留在卡片内，弱化但仍醒目 */
.optimize-error {
  margin: 2px 0 6px;
  padding: 6px 10px;
  font-size: 12px;
  line-height: 1.5;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: var(--radius-md, 8px);
}

.day-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.day-headline {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  padding: 2px 6px 2px 2px;
  margin: -2px -6px -2px -2px;
  background: none;
  border: none;
  border-radius: var(--radius-md);
  font: inherit;
  text-align: left;
  color: inherit;
  transition: background 0.16s;
}
.day-headline.clickable { cursor: pointer; }
.day-headline.clickable:hover { background: var(--fill); }
.day-headline:focus-visible { outline: 2px solid var(--brand); outline-offset: 1px; }

.day-head-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.day-title-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.day-badge {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  flex-shrink: 0;
  background: var(--ink);
  color: #fff;
  font-weight: 700;
  font-size: 12.5px;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 0.02em;
  transition: background 0.2s;
}
.day-card.is-collapsed .day-badge { width: 32px; height: 32px; font-size: 11.5px; }
.day-badge.day-badge-active { background: var(--brand); }
.day-title {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}
.day-summary {
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
  background: var(--fill);
  border-radius: var(--radius-full);
  padding: 1px 8px;
  white-space: nowrap;
}
.day-note {
  font-size: 12.5px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.day-booking-badges {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 2px;
}
.day-booking-badge {
  font-size: 11px;
}
.day-chevron {
  font-size: 12px;
  color: var(--faint);
  flex-shrink: 0;
  transition: transform 0.2s;
  transform: rotate(-90deg);
}
.day-chevron.open { transform: rotate(0deg); }

.day-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.day-actions :deep(.el-button) { margin-left: 0; }
.day-actions :deep(.el-button.focus-on) {
  color: var(--brand);
  border-color: var(--brand);
  background: var(--brand-soft);
}

.stops-wrap { padding-top: 12px; }
.stops-list {
  display: flex;
  flex-direction: column;
}
.stop-item {
  display: flex;
  gap: 12px;
}
.stop-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 26px;
  flex-shrink: 0;
}
.stop-index {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  flex-shrink: 0;
  color: #fff;
  font-size: 12.5px;
  font-weight: 600;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 0 4px var(--card);
}
.rail-line {
  flex: 1;
  width: 2px;
  background: var(--line);
  margin: 2px 0;
}
.stop-body {
  flex: 1;
  min-width: 0;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  margin-bottom: 8px;
  transition: border-color 0.18s, box-shadow 0.18s;
}
.stop-body:hover {
  border-color: var(--el-color-primary-light-8);
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.05);
}
.stop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.stop-name {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
  cursor: pointer;
}
.stop-name:hover { color: var(--brand); }
.stop-head-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.stop-quick {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transform: translateX(6px);
  transition: opacity 0.16s ease, transform 0.16s ease;
}
.stop-body:hover .stop-quick,
.stop-body:focus-within .stop-quick {
  opacity: 1;
  transform: translateX(0);
}
.stop-quick :deep(.el-button) {
  color: var(--muted);
  transition: background 0.16s, color 0.16s;
}
.stop-quick :deep(.el-button:hover) {
  color: var(--brand);
  background: var(--brand-soft);
}
.icon-up { transform: rotate(180deg); }
.stop-meta {
  display: flex;
  gap: 14px;
  font-size: 12.5px;
  color: var(--muted);
  margin-top: 4px;
  align-items: center;
}
.stop-meta .el-icon {
  font-size: 13px;
  color: var(--faint);
}
/* 时刻徽标：比价格/时长略醒目（时间轴核心信息） */
.stop-time {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--ink-2);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.stop-time-transfer {
  color: #6d28d9;
}
/* 段间交通 chip：站点之间的小间距提示 */
.stop-travel-chip {
  margin: 2px 0 4px 2px;
  font-size: 11.5px;
  color: var(--muted);
  padding: 1px 8px;
  background: var(--fill, #f6f6f7);
  border-radius: 999px;
  width: fit-content;
}
/* 日头时间窗口（展开态） */
.day-window {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.day-window .el-icon { font-size: 12px; color: var(--faint); }
.day-window-overflow {
  color: #b45309;
  font-weight: 600;
}
.day-window-overflow-badge {
  margin-left: 4px;
  padding: 0 6px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
  cursor: help;
}
.stop-desc {
  margin-top: 5px;
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.55;
}

@media (max-width: 640px) {
  .day-section.day-card { padding: 10px 12px; }
  .day-head { flex-wrap: wrap; }
  .day-actions { width: 100%; justify-content: flex-end; }
  .day-actions :deep(.el-button) { min-height: 36px; }
  .day-badge { width: 34px; height: 34px; font-size: 11.5px; }
  .day-note { white-space: normal; }
  .stop-body { padding: 10px 12px; }
  /* 移动端无 hover：快捷操作常驻 */
  .stop-quick { opacity: 1; transform: none; }
  .stop-quick :deep(.el-button) { min-height: 34px; min-width: 34px; }
}

@media print {
  .day-card,
  .stop-item {
    break-inside: avoid;
  }
  .day-actions,
  .stop-quick,
  .day-chevron {
    display: none !important;
  }
}
</style>
