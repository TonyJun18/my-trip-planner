<script setup>
// 记一笔费用（task-multi-currency-expense-eval 前端接线：后端多币种已就绪）
//
// 零凭证哲学（与后端 expense_service 一致）：
// - 币种来自后端规则库（_RULE_RATES），汇率可留空由规则库兜底；
// - 规则库没有的币种 → 必须手填折算汇率（绝不编造汇率）；
// - 不接实时汇率 API，文案明确标注「参考汇率（非实时）」。
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import * as api from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  tripId: { type: String, required: true },
  // 预算口径（可选）：仅用于记账后的超预算提示，不参与任何计算
  budgetTotal: { type: Number, default: 0 },
  spentTotal: { type: Number, default: 0 },
})
const emit = defineEmits(['update:modelValue', 'added'])

const { t } = useI18n()

// 与 backend/app/services/expense_service.py 的 _RULE_RATES 保持同步
const RULE_RATES = {
  CNY: 1, USD: 7.1, EUR: 7.7, JPY: 0.047, KRW: 0.0052,
  GBP: 9, THB: 0.2, SGD: 5.3, MYR: 1.6, AUD: 4.7,
}
const CURRENCY_CODES = Object.keys(RULE_RATES)
const CATEGORIES = ['food', 'transport', 'hotel', 'attraction', 'shopping', 'other']

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

function emptyForm() {
  return { category: 'food', amount: null, currency: 'CNY', rate_to_base: null, payer: '', note: '' }
}
const form = ref(emptyForm())
const saving = ref(false)
const error = ref('')

const isBase = computed(() => form.value.currency === 'CNY')
const ruleRate = computed(() => RULE_RATES[form.value.currency] ?? null)
const needsManualRate = computed(() => !isBase.value && ruleRate.value == null)
const ratePlaceholder = computed(() =>
  ruleRate.value != null
    ? t('expense.ratePlaceholder', { rate: ruleRate.value })
    : t('expense.rateRequired'),
)

watch(visible, (v) => {
  if (v) {
    form.value = emptyForm()
    error.value = ''
  }
})

function readError(e) {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail) return JSON.stringify(detail)
  return t('expense.saveFailed')
}

async function submit() {
  error.value = ''
  if (!form.value.amount || Number(form.value.amount) <= 0) {
    error.value = t('expense.amountInvalid')
    return
  }
  if (needsManualRate.value && !form.value.rate_to_base) {
    error.value = t('expense.rateRequired')
    return
  }
  saving.value = true
  try {
    const payload = {
      category: form.value.category,
      amount: Number(form.value.amount),
      currency: form.value.currency,
      payer: form.value.payer || '',
    }
    if (form.value.note) payload.note = form.value.note
    if (!isBase.value && form.value.rate_to_base) {
      payload.rate_to_base = Number(form.value.rate_to_base)
    }
    const saved = await api.addExpense(props.tripId, payload)
    const spentAfter = (props.spentTotal || 0) + (saved?.amount_base || 0)
    if (props.budgetTotal && spentAfter > props.budgetTotal) {
      ElMessage.warning(
        t('expense.overBudget', {
          over: (spentAfter - props.budgetTotal).toFixed(2),
          budget: props.budgetTotal,
        }),
      )
    } else {
      ElMessage.success(t('expense.added'))
    }
    emit('added', saved)
    visible.value = false
  } catch (e) {
    error.value = readError(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="$t('expense.addTitle')" width="460px" append-to-body>
    <el-form label-position="top" @submit.prevent>
      <el-form-item :label="$t('expense.category')">
        <el-select v-model="form.category" style="width: 100%">
          <el-option
            v-for="c in CATEGORIES"
            :key="c"
            :label="$t(`expense.category_${c}`)"
            :value="c"
          />
        </el-select>
      </el-form-item>

      <div class="amount-row">
        <el-form-item :label="$t('expense.amount')" class="amount-item">
          <el-input-number v-model="form.amount" :min="0.01" :precision="2" :step="10" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="$t('expense.currency')" class="currency-item">
          <el-select v-model="form.currency" filterable style="width: 100%">
            <el-option v-for="c in CURRENCY_CODES" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </div>

      <el-form-item v-if="!isBase" :label="$t('expense.rateLabel', { currency: form.currency })">
        <el-input-number
          v-model="form.rate_to_base"
          :min="0.0001"
          :precision="4"
          :step="0.1"
          :placeholder="ratePlaceholder"
          style="width: 100%"
        />
        <div class="field-hint">{{ ratePlaceholder }} · {{ $t('expense.rateBasis') }}</div>
      </el-form-item>

      <el-form-item :label="$t('expense.payer')">
        <el-input v-model="form.payer" :placeholder="$t('expense.payerPlaceholder')" maxlength="50" />
      </el-form-item>

      <el-form-item :label="$t('expense.note')">
        <el-input v-model="form.note" :placeholder="$t('expense.notePlaceholder')" maxlength="200" />
      </el-form-item>

      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    </el-form>

    <template #footer>
      <el-button @click="visible = false">{{ $t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" @click="submit">{{ $t('expense.submit') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.amount-row {
  display: flex;
  gap: 12px;
}
.amount-item {
  flex: 1 1 60%;
}
.currency-item {
  flex: 0 0 120px;
}
.field-hint {
  font-size: 12px;
  color: var(--muted);
  margin-top: 4px;
  line-height: 1.4;
}
@media (max-width: 640px) {
  .amount-row {
    flex-direction: column;
    gap: 0;
  }
  .currency-item {
    flex: 1 1 auto;
  }
}
</style>
