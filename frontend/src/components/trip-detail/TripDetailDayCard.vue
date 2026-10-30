<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { MapLocation, MoreFilled, ArrowDown, EditPen, Delete, Wallet, Clock } from '@element-plus/icons-vue'
import { useTripTypes } from '@/composables/useTripTypes'

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
})

const emit = defineEmits(['focus-day', 'toggle-open', 'add-stop', 'day-cmd', 'stop-cmd', 'stop-edit'])

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

// 收起态摘要：站数 · 花费 · 时长（缺项自动省略，不占位）
const summary = computed(() => {
  if (!hasStops.value) return ''
  return [
    t('tripDetail.dayStops', { n: props.day.stops.length }),
    totalCost.value ? `¥${totalCost.value}` : '',
    durationText.value,
  ].filter(Boolean).join(' · ')
})

function toggle() {
  if (!hasStops.value) return
  emit('toggle-open', props.day)
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
          <span class="day-note">{{ day.note || $t('common.freeExplore') }}</span>
        </span>
        <el-icon v-if="hasStops" class="day-chevron" :class="{ open }"><ArrowDown /></el-icon>
      </button>

      <div class="day-actions">
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
                <span v-if="stop.estimated_cost != null"><el-icon><Wallet /></el-icon>¥{{ stop.estimated_cost }}</span>
                <span v-if="stop.estimated_duration_minutes"><el-icon><Clock /></el-icon>{{ stop.estimated_duration_minutes }} {{ $t('common.minutes') }}</span>
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
