<script setup>
import { computed } from 'vue'
import { MapLocation, MoreFilled, Top, Bottom, EditPen, Delete, Wallet, Clock } from '@element-plus/icons-vue'
import { useTripTypes } from '@/composables/useTripTypes'

// 逐日行程卡：Day 头（聚焦地图联动）+ 站点时间轴 + 站点操作（上移/下移/编辑/更多）
const props = defineProps({
  day: { type: Object, required: true },
  activeDay: { type: [Number, null], default: null },
  dayIndex: { type: Number, default: 0 },
})

const emit = defineEmits(['focus-day', 'add-stop', 'day-cmd', 'stop-cmd', 'stop-edit'])

const { typeLabel, typeColor, typeEmoji } = useTripTypes()

const isActive = computed(() => props.activeDay === props.day.day_number)
</script>

<template>
  <div class="day-section day-card" :class="{ 'day-active': isActive }">
    <div class="day-head">
      <div class="day-headline" :class="{ clickable: day.stops.length }" @click="day.stops.length && emit('focus-day', day.day_number)">
        <span class="day-badge" :class="{ 'day-badge-active': isActive }">Day {{ day.day_number }}</span>
        <div>
          <div class="day-title">
            {{ day.date || $t('common.dayN', { n: day.day_number }) }}
            <el-icon v-if="day.stops.length" class="day-focus-icon" :size="13" :title="$t('tripDetail.mapFocusHint')"><MapLocation /></el-icon>
          </div>
          <div class="day-note">{{ day.note || $t('common.freeExplore') }}</div>
        </div>
      </div>
      <div class="day-actions">
        <el-button size="small" type="primary" plain @click="emit('add-stop', day.id)">+ {{ $t('tripDetail.addStop') }}</el-button>
        <el-dropdown trigger="click" @command="(cmd) => emit('day-cmd', day, cmd)">
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
        <div class="stop-body" @click.self="emit('stop-edit', day, stop)">
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
                  aria-label="Move stop up"
                  @click.stop="emit('stop-cmd', day, stop, idx, 'up')"
                ><el-icon><Top /></el-icon></el-button>
                <el-button
                  v-if="idx < day.stops.length - 1"
                  link
                  circle
                  size="small"
                  :title="$t('tripDetail.moveDown')"
                  aria-label="Move stop down"
                  @click.stop="emit('stop-cmd', day, stop, idx, 'down')"
                ><el-icon><Bottom /></el-icon></el-button>
                <el-button
                  link
                  circle
                  size="small"
                  :title="$t('tripDetail.editStop')"
                  aria-label="Edit stop"
                  @click.stop="emit('stop-edit', day, stop)"
                ><el-icon><EditPen /></el-icon></el-button>
                <el-dropdown trigger="click" @click.stop @command="(cmd) => emit('stop-cmd', day, stop, idx, cmd)">
                  <el-button link circle size="small" aria-label="Stop actions">
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
</template>

<style scoped>
.day-section {
  margin-bottom: 24px;
}
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
.day-card:hover {
  border-color: var(--el-color-primary-light-8);
  box-shadow: var(--shadow-hover);
}
.day-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 14px;
  gap: 12px;
}
.day-headline {
  display: flex;
  align-items: center;
  gap: 12px;
}
.day-headline.clickable {
  cursor: pointer;
  border-radius: var(--radius-md);
}
.day-headline.clickable:hover {
  background: var(--fill);
}
.day-badge {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  flex-shrink: 0;
  background: var(--ink);
  color: #fff;
  font-weight: 700;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 0.02em;
  transition: background 0.2s;
}
.day-badge.day-badge-active {
  background: var(--brand);
}
.day-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}
.day-note {
  font-size: 12.5px;
  color: var(--muted);
}
.day-focus-icon {
  color: var(--faint);
  margin-left: 6px;
  vertical-align: -2px;
}
.day-card.day-active .day-focus-icon {
  color: var(--brand);
}
.day-actions {
  display: flex;
  gap: 8px;
}

.stops-list {
  display: flex;
  flex-direction: column;
}
.stop-item {
  display: flex;
  gap: 14px;
}
.stop-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 28px;
  flex-shrink: 0;
}
.stop-index {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  flex-shrink: 0;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 0 4px #fff;
}
.rail-line {
  flex: 1;
  width: 2px;
  background: var(--line);
  margin: 4px 0;
}
.stop-body {
  flex: 1;
  min-width: 0;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 14px 18px;
  margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
  transition: box-shadow 0.2s;
}
.stop-body:hover {
  box-shadow: var(--shadow-card);
}
.stop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.stop-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}
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
.stop-body:hover .stop-quick {
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
.stop-meta {
  display: flex;
  gap: 14px;
  font-size: 12.5px;
  color: var(--muted);
  margin-top: 6px;
  align-items: center;
}
.stop-meta .el-icon {
  font-size: 13px;
  color: var(--faint);
}
.stop-desc {
  margin-top: 6px;
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.55;
}

@media (max-width: 640px) {
  .day-head {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  .day-actions {
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
  }
  .day-actions :deep(.el-button) {
    margin-left: 0;
    min-height: 40px;
  }
  .day-badge {
    width: 44px;
    height: 44px;
    font-size: 12px;
  }
  .day-headline {
    gap: 10px;
  }
  .stop-body {
    padding: 12px 14px;
  }
  .stop-quick {
    opacity: 1;
    transform: none;
  }
  .stop-quick :deep(.el-button) {
    min-height: 36px;
    min-width: 36px;
  }
}

@media print {
  .day-card,
  .stop-item {
    break-inside: avoid;
  }
  .day-actions {
    display: none !important;
  }
  .stop-quick {
    display: none !important;
  }
}
</style>