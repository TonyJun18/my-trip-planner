<script setup>
// 费用记账面板（行中「实付」记录）：列表 + 汇总 + 记一笔 + 撤销误记
//
// 消费 backend/app/api/v1/expenses.py：
//   GET    /trips/{id}/expenses           → { items, balance }
//   POST   /trips/{id}/expenses           → ExpenseOut（原币 + 折算 amount_base）
//   DELETE /trips/{id}/expenses/{eid}     → 204
// 多币种：每条记录显示「原币金额」与「折算 CNY」，汇总只用 amount_base（口径一致）。
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import * as api from '@/api'
import AddExpenseDialog from '@/components/AddExpenseDialog.vue'

const props = defineProps({
  tripId: { type: String, required: true },
})
const emit = defineEmits(['changed'])

const { t } = useI18n()

const CATEGORY_EMOJI = {
  food: '🍜', transport: '🚕', hotel: '🏨', attraction: '🎫', shopping: '🛍️', other: '💸',
}

const items = ref([])
const balance = ref(null)
const loading = ref(false)
const dialogVisible = ref(false)
const deleting = ref('')

const total = computed(() => Number(balance.value?.total || 0))
const perPerson = computed(() => Number(balance.value?.per_person || 0))
const currencies = computed(() => balance.value?.currencies || [])
const hasRecords = computed(() => items.value.length > 0)

async function load() {
  if (!props.tripId) return
  loading.value = true
  try {
    const data = await api.listExpenses(props.tripId)
    items.value = data?.items || []
    balance.value = data?.balance || null
  } catch {
    items.value = []
    balance.value = null // 读失败静默（费用面板不阻断行程浏览）
  } finally {
    loading.value = false
  }
}

async function remove(item) {
  const label = `${item.currency} ${item.amount}`
  try {
    await ElMessageBox.confirm(t('expense.deleteConfirm', { amount: label }), t('expense.deleteTitle'), {
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
      type: 'warning',
    })
  } catch {
    return // 用户取消
  }
  deleting.value = item.id
  try {
    await api.deleteExpense(props.tripId, item.id)
    ElMessage.success(t('expense.deleted'))
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || t('expense.deleteFailed'))
  } finally {
    deleting.value = ''
  }
}

async function onAdded() {
  await load()
  emit('changed')
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="expense-panel" v-loading="loading">
    <div class="expense-summary">
      <div class="summary-main">
        <span class="summary-total">¥{{ total.toFixed(2) }}</span>
        <span class="summary-label">{{ $t('expense.total') }}</span>
      </div>
      <div class="summary-meta">
        <span>{{ $t('expense.perPerson') }} ¥{{ perPerson.toFixed(2) }}</span>
        <span>·</span>
        <span>{{ $t('expense.count', { n: items.length }) }}</span>
        <span v-if="currencies.length > 1" class="summary-currencies">
          {{ $t('expense.currencies') }}: {{ currencies.join(' / ') }}
        </span>
      </div>
      <el-button size="small" type="primary" plain @click="dialogVisible = true">
        {{ $t('expense.add') }}
      </el-button>
    </div>

    <div v-if="hasRecords" class="expense-list">
      <div v-for="item in items" :key="item.id" class="expense-item">
        <span class="expense-emoji">{{ CATEGORY_EMOJI[item.category] || '💸' }}</span>
        <div class="expense-main">
          <div class="expense-line">
            <span class="expense-category">{{ $t(`expense.category_${item.category}`) }}</span>
            <span class="expense-amount">{{ item.currency }} {{ item.amount }}</span>
          </div>
          <div class="expense-sub">
            <span v-if="item.currency !== 'CNY'" class="expense-converted">
              ≈ ¥{{ Number(item.amount_base).toFixed(2) }}（{{ $t('expense.rateShort', { rate: item.rate_to_base }) }}）
            </span>
            <span v-if="item.payer" class="expense-payer">{{ item.payer }}</span>
            <span v-if="item.note" class="expense-note">{{ item.note }}</span>
          </div>
        </div>
        <el-button
          size="small"
          text
          type="danger"
          :loading="deleting === item.id"
          @click="remove(item)"
        >
          {{ $t('common.delete') }}
        </el-button>
      </div>
    </div>
    <el-empty v-else :description="$t('expense.empty')" :image-size="56" />

    <AddExpenseDialog
      v-model="dialogVisible"
      :trip-id="tripId"
      :spent-total="total"
      @added="onAdded"
    />
  </div>
</template>

<style scoped>
.expense-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 60px;
}
.expense-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--card);
}
.summary-main {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.summary-total {
  font-size: 20px;
  font-weight: 700;
  color: var(--brand);
}
.summary-label {
  font-size: 12.5px;
  color: var(--muted);
}
.summary-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--muted);
  flex-wrap: wrap;
}
.summary-currencies {
  margin-left: 4px;
}
.expense-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.expense-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--card);
}
.expense-emoji {
  font-size: 16px;
  line-height: 1;
}
.expense-main {
  flex: 1;
  min-width: 0;
}
.expense-line {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.expense-category {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}
.expense-amount {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--ink);
}
.expense-sub {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}
.expense-note {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
