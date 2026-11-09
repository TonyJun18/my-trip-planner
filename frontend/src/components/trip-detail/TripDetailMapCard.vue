<script setup>
import { MapLocation } from '@element-plus/icons-vue'
import TripMap from '@/components/TripMap.vue'

// 地图卡：markers 高亮 + activeDay 联动 + 可拖拽修订
defineProps({
  markers: { type: Array, required: true },
  activeDay: { type: [Number, null], default: null },
  canMapDrag: { type: Boolean, default: false },
  mapDragError: { type: String, default: '' },
  // 离线降级（task-offline-degrade）：透传给 TripMap，改渲染按日站点列表
  offline: { type: Boolean, default: false },
})

const emit = defineEmits(['clear-focus', 'map-move'])
</script>

<template>
  <div class="map-card" :class="{ 'day-focused': activeDay != null }">
    <div class="card-head">
      <span class="card-title"><el-icon style="margin-right: 6px"><MapLocation /></el-icon>{{ $t('common.mapTitle') }}</span>
      <span class="map-hint">
        <template v-if="activeDay != null">{{ $t('tripDetail.mapFocusDay', { day: activeDay }) }} · </template>
        {{ canMapDrag ? $t('tripDetail.mapDragHint') : $t('common.mapHint') }}
        <el-button v-if="activeDay != null" link type="primary" size="small" @click="emit('clear-focus')" style="margin-left: 6px">
          {{ $t('tripDetail.mapClearFocus') }}
        </el-button>
      </span>
    </div>
    <el-alert
      v-if="mapDragError"
      class="map-drag-error"
      type="warning"
      :closable="false"
      show-icon
      :title="mapDragError"
    />
    <TripMap
      :markers="markers"
      :active-day="activeDay"
      height="360px"
      :draggable="canMapDrag"
      :offline="offline"
      :on-move="(payload) => emit('map-move', payload)"
    />
  </div>
</template>

<style scoped>
.map-card {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 18px;
  box-shadow: var(--shadow-card);
}
.map-card.day-focused {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft), var(--shadow-card);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}
.map-hint {
  font-size: 12px;
  color: var(--faint);
}
.map-drag-error {
  margin-bottom: 10px;
}

@media (max-width: 640px) {
  .map-card {
    padding: 14px;
  }
  .map-hint {
    font-size: 11px;
  }
}

@media print {
  .map-card {
    max-height: 320px;
    overflow: hidden;
  }
  .map-hint {
    display: none !important;
  }
  .map-drag-error {
    display: none !important;
  }
}
</style>