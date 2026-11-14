<script setup>
// 常驻预算条 + 预算口径卡（竞品依据：Mindtrip「持久预算条」/ DVGO「含·不含清单」）
//
// 数据全部来自既有接口，无新增后端：
// - 预算：trip.budget（用户规划时填的额度）
// - 预计：GET /trips/{id}/budget → total_estimated / by_type / estimate_basis
// - 实花：GET /trips/{id}/journey → expense_total（多币种已折算 CNY）
// 口径诚实：按「含 / 不含」明确列出，来源与置信度原样透出，不做加工。
import { computed, ref } from 'vue'
import { Warning } from '@element-plus/icons-vue'

const props = defineProps({
  budgetPlanned: { type: Number, default: 0 },
  estimated: { type: Number, default: 0 },
  spent: { type: Number, default: 0 },
  byType: { type: Object, default: () => ({}) },
  basis: { type: Object, default: () => ({}) },
  reconciliation: { type: Object, default: null },
  travelers: { type: Number, default: 1 },
})

const expanded = ref(false)

const hasPlanned = computed(() => props.budgetPlanned > 0)
const hasEstimated = computed(() => props.estimated > 0)
const hasSpent = computed(() => props.spent > 0)

// 进度以「预计」为主口径（预算是否够用）；已花超过预计时改用已花，避免低估
const driver = computed(() => Math.max(props.estimated || 0, props.spent || 0))
const percent = computed(() =>
  hasPlanned.value ? Math.round((driver.value / props.budgetPlanned) * 100) : 0,
)
const level = computed(() => {
  if (!hasPlanned.value) return 'none'
  if (percent.value > 100) return 'over'
  if (percent.value >= 80) return 'warn'
  return 'ok'
})
const barPercent = computed(() => Math.min(100, percent.value))
const overAmount = computed(() => Math.max(0, driver.value - props.budgetPlanned))

const perPerson = computed(() => {
  if (!props.estimated || props.travelers <= 1) return 0
  return Math.round(props.estimated / props.travelers)
})

// 含：四类（transport 仅在 estimate_basis 有参考价时出现）
const includedRows = computed(() => {
  const rows = []
  const bt = props.byType || {}
  const labels = { attraction: 'tickets', food: 'food', hotel: 'hotel', transport: 'transport' }
  for (const [key, label] of Object.entries(labels)) {
    const v = Number(bt[key] || 0)
    if (v > 0) rows.push({ key, label, amount: v })
  }
  return rows
})
const basisNote = computed(() => {
  const b = props.basis || {}
  const hotel = b.hotel
  const transport = b.transport
  const parts = []
  if (hotel?.source) parts.push(`hotel: ${hotel.source}${hotel.updated_at ? ` (${hotel.updated_at})` : ''}`)
  if (transport?.source) parts.push(`transport: ${transport.source}`)
  return parts.join(' · ')
})

// 预算对账（方案 C）：estimated 显著低于 planned 时提示缺口，不硬凑
const recon = computed(() => props.reconciliation || null)
const reconGap = computed(() => {
  if (!recon.value?.gap || recon.value.status !== 'under') return 0
  return Math.round(recon.value.gap)
})
const reconDaily = computed(() => {
  if (!recon.value?.daily_needed || recon.value.status !== 'under') return 0
  return Math.round(recon.value.daily_needed)
})
const showRecon = computed(() => {
  // 仅当缺口显著（≥ 计划 15%）时提示，避免「只差几十块」的噪音
  const planned = Number(props.budgetPlanned) || 0
  return reconGap.value > 0 && planned > 0 && reconGap.value >= planned * 0.15
})
</script>

<template>
  <div v-if="hasPlanned || hasEstimated" class="budget-bar" :class="level">
    <div class="bb-main">
      <div class="bb-figures">
        <span v-if="hasPlanned" class="bb-item">
          <span class="bb-label">{{ $t('budgetBar.planned') }}</span>
          <span class="bb-value">¥{{ Math.round(budgetPlanned).toLocaleString() }}</span>
        </span>
        <span v-if="hasEstimated" class="bb-item">
          <span class="bb-label">{{ $t('budgetBar.estimated') }}</span>
          <span class="bb-value">¥{{ Math.round(estimated).toLocaleString() }}</span>
        </span>
        <span v-if="hasSpent" class="bb-item">
          <span class="bb-label">{{ $t('budgetBar.spent') }}</span>
          <span class="bb-value spent">¥{{ Math.round(spent).toLocaleString() }}</span>
        </span>
        <span v-if="perPerson" class="bb-item muted">
          {{ $t('budgetBar.perPerson', { amount: perPerson.toLocaleString() }) }}
        </span>
      </div>

      <div class="bb-actions">
        <span v-if="level === 'over'" class="bb-flag over">
          {{ $t('budgetBar.over', { amount: Math.round(overAmount).toLocaleString() }) }}
        </span>
        <span v-else-if="level !== 'none'" class="bb-flag" :class="level">{{ percent }}%</span>
        <el-button text size="small" class="bb-toggle" @click="expanded = !expanded">
          {{ expanded ? $t('budgetBar.hideBasis') : $t('budgetBar.showBasis') }}
        </el-button>
      </div>
    </div>

    <div v-if="hasPlanned" class="bb-track">
      <div class="bb-fill" :class="level" :style="{ width: barPercent + '%' }" />
      <div v-if="hasSpent && hasEstimated" class="bb-marker" :style="{ left: barPercent + '%' }" />
    </div>

    <div v-if="showRecon" class="bb-recon">
      <el-icon class="bb-recon-ico"><Warning /></el-icon>
      <span>{{ $t('budgetBar.reconGap', { amount: reconGap.toLocaleString(), daily: reconDaily.toLocaleString() }) }}</span>
    </div>

    <div v-if="expanded" class="bb-detail">
      <div class="bb-col">
        <div class="bb-col-title">{{ $t('budgetBar.included') }}</div>
        <div v-for="row in includedRows" :key="row.key" class="bb-row">
          <span>{{ $t(`budgetBar.${row.label}`) }}</span>
          <span>¥{{ Math.round(row.amount).toLocaleString() }}</span>
        </div>
        <div v-if="!includedRows.length" class="bb-row muted">{{ $t('budgetBar.noBreakdown') }}</div>
      </div>
      <div class="bb-col">
        <div class="bb-col-title">{{ $t('budgetBar.excluded') }}</div>
        <div class="bb-row muted">{{ $t('budgetBar.excludedList') }}</div>
        <div v-if="basisNote" class="bb-row basis">{{ $t('budgetBar.basisLabel') }}: {{ basisNote }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.budget-bar {
  margin-bottom: 14px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--card);
  box-shadow: var(--shadow-sm);
}
.bb-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.bb-figures {
  display: flex;
  align-items: baseline;
  gap: 14px;
  flex-wrap: wrap;
}
.bb-item {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
}
.bb-label {
  font-size: 12px;
  color: var(--muted);
}
.bb-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
}
.bb-value.spent {
  color: var(--brand);
}
.bb-item.muted {
  font-size: 12px;
  color: var(--muted);
}
.bb-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bb-flag {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.05);
  color: var(--muted);
}
.bb-flag.ok { background: rgba(22, 163, 74, 0.12); color: #16a34a; }
.bb-flag.warn { background: rgba(224, 164, 88, 0.16); color: #b45309; }
.bb-flag.over { background: rgba(220, 38, 38, 0.12); color: #dc2626; }
.bb-toggle { padding: 0 4px; }
.bb-track {
  position: relative;
  height: 6px;
  margin-top: 8px;
  border-radius: 999px;
  background: var(--line);
  overflow: hidden;
}
.bb-fill {
  height: 100%;
  border-radius: 999px;
  background: #16a34a;
  transition: width 0.3s ease;
}
.bb-fill.warn { background: #e0a458; }
.bb-fill.over { background: #dc2626; }
.bb-marker {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--ink);
  opacity: 0.35;
}
.bb-detail {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
}
.bb-col {
  flex: 1 1 200px;
  min-width: 160px;
}
.bb-col-title {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 6px;
}
.bb-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12.5px;
  color: var(--ink);
  padding: 2px 0;
}
.bb-row.muted {
  color: var(--muted);
}
.bb-row.basis {
  display: block;
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--muted);
  word-break: break-all;
}
.bb-recon {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(224, 164, 88, 0.1);
  color: #b45309;
  font-size: 12.5px;
}
.bb-recon-ico {
  flex-shrink: 0;
}
@media print {
  .bb-toggle { display: none; }
  .bb-recon { display: none; }
}
</style>
