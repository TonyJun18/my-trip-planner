<script setup>
import { ref } from 'vue'
import TripDashboard from '@/components/TripDashboard.vue'

// 侧栏：旅程仪表盘（预算环 / 追踪 / 预订 / 徽章）—— sticky 常驻
defineProps({
  tripId: { type: String, required: true },
  budget: { type: Object, default: null },
  budgetPercent: { type: [Number, null], default: null },
  basisText: { type: String, default: '' },
  tripBudget: { type: [Number, null], default: null },
  travelers: { type: Number, default: 1 },
})

// 暴露仪表盘刷新（orchestrator 打卡后调用）
const dashInner = ref(null)
defineExpose({
  load: () => dashInner.value?.load(),
})
</script>

<template>
  <div class="side-col">
    <TripDashboard
      ref="dashInner"
      :trip-id="tripId"
      :budget="budget"
      :budget-percent="budgetPercent"
      :basis-text="basisText"
      :trip-budget="tripBudget"
      :travelers="travelers"
    />
  </div>
</template>

<style scoped>
.side-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: sticky;
  top: 76px; /* 顶部导航高度留白 */
}
@media (max-width: 960px) {
  .side-col {
    position: static;
  }
}
</style>