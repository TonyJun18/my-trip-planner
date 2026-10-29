<script setup>
import { Location, Promotion, Calendar, User, Wallet, Briefcase } from '@element-plus/icons-vue'

// 头部紧凑摘要条：封面 / 标题 / 状态徽标+切换 / meta pills
// 纯展示 + 状态切换事件，无业务状态。
defineProps({
  trip: { type: Object, required: true },
  statusMap: { type: Object, required: true },
  statusOptions: { type: Array, required: true },
  statusUpdating: { type: Boolean, default: false },
  tripTypeDisplay: { type: Function, required: true },
})

const emit = defineEmits(['edit-open', 'status-change'])
</script>

<template>
  <div class="hero-bar">
    <div class="hero-main">
      <div class="hero-cover-mini">{{ (trip.destination || '?')[0] }}</div>
      <div class="hero-info">
        <div class="hero-row1">
          <h1 class="hero-title">{{ trip.title }}</h1>
          <span class="status-badge" :class="(statusMap[trip.status] || statusMap.draft).type">
            {{ (statusMap[trip.status] || statusMap.draft).label }}
          </span>
          <el-select
            v-model="trip.status"
            class="status-switch"
            size="small"
            :loading="statusUpdating"
            @change="(v) => emit('status-change', v)"
          >
            <el-option v-for="opt in statusOptions" :key="opt.value" :value="opt.value" :label="opt.label" />
          </el-select>
        </div>
        <div class="hero-meta">
          <span class="hero-pill"><el-icon><Location /></el-icon>{{ trip.destination }}</span>
          <span class="hero-pill" v-if="trip.departure"><el-icon><Promotion /></el-icon>{{ $t('tripDetail.fromDeparture', { dep: trip.departure }) }}</span>
          <span class="hero-pill"><el-icon><Calendar /></el-icon>{{ trip.start_date }} ~ {{ trip.end_date }}</span>
          <span class="hero-pill"><el-icon><User /></el-icon>{{ trip.travelers }} {{ $t('common.peopleUnit') }}</span>
          <span class="hero-pill" v-if="trip.budget != null"><el-icon><Wallet /></el-icon>¥{{ trip.budget }}</span>
          <span class="hero-pill" v-if="trip.trip_type"><el-icon><Briefcase /></el-icon>{{ tripTypeDisplay(trip.trip_type) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hero-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
  padding: 14px 18px;
  background: linear-gradient(135deg, var(--brand-soft), var(--card) 55%);
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-card);
}
.hero-main {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 1;
  min-width: 0;
}
.hero-cover-mini {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-lg);
  flex-shrink: 0;
  background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 55%, #a1c4fd 100%);
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-sm);
}
.hero-info {
  flex: 1;
  min-width: 0;
}
.hero-row1 {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.hero-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.02em;
}
.status-badge {
  font-size: 11.5px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: var(--radius-full);
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--line);
}
.status-badge.success {
  color: var(--success);
}
.status-badge.warning {
  color: var(--warning);
}
.status-badge.info {
  color: var(--muted);
}
.status-switch {
  width: 108px;
}
.hero-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.hero-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--card);
  color: var(--ink-2);
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: var(--radius-full);
  border: 1px solid var(--line);
}
</style>