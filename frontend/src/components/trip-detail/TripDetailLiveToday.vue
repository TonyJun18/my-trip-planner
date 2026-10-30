<script setup>
// 行中「今日视图」（live 期间；打卡/跳过/迟到顺延）—— 全宽置顶，随时可操作
defineProps({
  live: { type: Object, required: true },
  liveOp: { type: String, default: '' },
  typeEmoji: { type: Object, required: true },
  typeLabel: { type: Object, required: true },
})

const emit = defineEmits(['check', 'skip', 'delay'])
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

    <div class="live-stops">
      <div v-for="stop in live.stops" :key="stop.id" class="live-stop" :class="{ done: stop.checked }">
        <el-checkbox
          :model-value="stop.checked"
          :disabled="!!liveOp"
          @change="(v) => emit('check', stop, v)"
        />
        <div class="live-stop-info">
          <div class="live-stop-name" :class="{ muted: stop.checked }">{{ stop.name }}</div>
          <div class="live-stop-type">{{ typeEmoji[stop.stop_type] }} {{ typeLabel[stop.stop_type] || stop.stop_type }}</div>
        </div>
        <div class="live-stop-actions">
          <el-button size="small" text type="danger" :disabled="!!liveOp" @click="emit('skip', stop)">
            {{ $t('tripDetail.liveSkip') }}
          </el-button>
        </div>
      </div>
    </div>

    <div class="live-footer">
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
.live-stop-actions {
  flex-shrink: 0;
}
.live-footer {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
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