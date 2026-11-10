<script setup>
// 行程内结构化事实问答（task-property-qa-eval 前端接线）
// 口径：只答结构化字段里真实存在的事实（营业时间/评分/预算/费用/时长/质检预警），
// 零 LLM；拿不到就明说「查不到」，绝不编造数字/时间/评分。
// basis 徽标透出答案来源：explicit（显式字段）/ rule_based（类目规则库推断）/ none（无数据）。
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChatDotRound, Search } from '@element-plus/icons-vue'
import * as api from '@/api'
import { currentLocale } from '@/i18n'

const props = defineProps({
  tripId: { type: String, required: true },
})

const { t } = useI18n()

const loading = ref(false)
const asking = ref(false)
const facts = ref(null)
const answer = ref(null)
const question = ref('')
const failed = ref(false)

const allFacts = computed(() => facts.value?.facts || [])
const availableFacts = computed(() => allFacts.value.filter((f) => f.available && f.value).slice(0, 12))
const unknownCount = computed(() => allFacts.value.filter((f) => !f.available || !f.value).length)
const suggestions = computed(() => (facts.value?.suggestions || []).slice(0, 4))
const warnings = computed(() => (facts.value?.warnings || []).filter((w) => w.message).slice(0, 4))
const budget = computed(() => facts.value?.budget || {})
const currency = computed(() => budget.value.currency || 'CNY')
const hasBudget = computed(
  () => budget.value.preset_budget != null || budget.value.estimated_total != null,
)

const kindLabels = computed(() => ({
  hours: t('propertyQa.kindHours'),
  rating: t('propertyQa.kindRating'),
  price: t('propertyQa.kindPrice'),
  duration: t('propertyQa.kindDuration'),
}))

const basisLabel = computed(() => {
  const basis = answer.value?.basis
  if (basis === 'explicit') return t('propertyQa.basisExplicit')
  if (basis === 'rule_based') return t('propertyQa.basisRule')
  return t('propertyQa.basisNone')
})

async function loadFacts() {
  if (!props.tripId) return
  loading.value = true
  failed.value = false
  try {
    facts.value = await api.getPropertyQaFacts(props.tripId, currentLocale())
  } catch {
    // api 拦截器已提示；面板降级为「暂无结构化数据」
    facts.value = null
    failed.value = true
  } finally {
    loading.value = false
  }
}

async function ask(text) {
  const q = String(text ?? question.value).trim()
  if (!q || asking.value) return
  asking.value = true
  try {
    answer.value = await api.askPropertyQa(props.tripId, q, currentLocale())
    question.value = q
  } catch {
    answer.value = null
  } finally {
    asking.value = false
  }
}

function askSuggestion(text) {
  answer.value = null
  ask(text)
}

watch(() => props.tripId, loadFacts, { immediate: true })
</script>

<template>
  <section class="qa-card">
    <header class="qa-head">
      <div class="qa-title">
        <el-icon style="margin-right: 6px"><ChatDotRound /></el-icon>
        {{ t('propertyQa.title') }}
      </div>
      <span class="qa-hint">{{ t('propertyQa.hint') }}</span>
    </header>

    <div v-if="loading" class="qa-empty">{{ t('common.loading') }}</div>

    <template v-else>
      <!-- 可答事实（无 q 时的清单，证明「能答什么」而不是空口） -->
      <div v-if="availableFacts.length" class="qa-facts">
        <div class="qa-section-title">{{ t('propertyQa.factsTitle') }}</div>
        <ul class="qa-fact-list">
          <li v-for="(f, idx) in availableFacts" :key="idx" class="qa-fact">
            <span class="qa-fact-target">{{ f.target }}</span>
            <em class="qa-fact-kind">{{ kindLabels[f.kind] || f.kind }}</em>
            <span class="qa-fact-value">{{ f.value }}</span>
            <em v-if="f.basis === 'rule_based'" class="qa-fact-basis">{{ t('propertyQa.basisRule') }}</em>
          </li>
        </ul>
        <p v-if="unknownCount" class="qa-unknown-note">
          {{ t('propertyQa.unknownFacts', { n: unknownCount }) }}
        </p>
      </div>

      <div v-else-if="failed || !availableFacts.length" class="qa-empty">
        {{ t('propertyQa.noFacts') }}
      </div>

      <!-- 预算 + 质检预警（结构化字段直接透出） -->
      <div v-if="hasBudget" class="qa-budget">
        <div class="qa-section-title">{{ t('propertyQa.budgetTitle') }}</div>
        <div class="qa-budget-row">
          <span v-if="budget.preset_budget != null">
            {{ t('propertyQa.budgetPreset', { amount: budget.preset_budget, currency }) }}
          </span>
          <span v-if="budget.estimated_total != null">
            {{ t('propertyQa.budgetEstimated', { amount: budget.estimated_total, currency }) }}
          </span>
        </div>
      </div>

      <div v-if="warnings.length" class="qa-warnings">
        <div class="qa-section-title">{{ t('propertyQa.warningsTitle') }}</div>
        <ul class="qa-warning-list">
          <li v-for="(w, idx) in warnings" :key="idx">
            {{ w.message }}
            <em v-if="w.suggestion" class="qa-warning-fix">{{ w.suggestion }}</em>
          </li>
        </ul>
      </div>

      <!-- 提问区 -->
      <div class="qa-ask">
        <el-input
          v-model="question"
          :placeholder="t('propertyQa.placeholder')"
          maxlength="200"
          clearable
          @keyup.enter="ask()"
        >
          <template #append>
            <el-button :loading="asking" :disabled="!question.trim()" @click="ask()">
              <el-icon><Search /></el-icon>
            </el-button>
          </template>
        </el-input>
      </div>

      <div v-if="suggestions.length" class="qa-suggest">
        <button
          v-for="(s, idx) in suggestions"
          :key="idx"
          class="qa-chip"
          type="button"
          @click="askSuggestion(s)"
        >
          {{ s }}
        </button>
      </div>

      <!-- 答案（available=false 时诚实说查不到，绝不编造） -->
      <div v-if="answer" class="qa-answer" :class="{ 'qa-answer-empty': !answer.available }">
        <div class="qa-answer-q">{{ answer.question }}</div>
        <div class="qa-answer-a">
          {{ answer.available ? answer.answer : t('propertyQa.noAnswer') }}
        </div>
        <div class="qa-answer-meta">
          <em v-if="answer.target" class="qa-answer-target">{{ answer.target }}</em>
          <em class="qa-answer-basis">{{ t('propertyQa.basisLabel') }}{{ basisLabel }}</em>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.qa-card {
  margin-top: 16px;
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 12px;
  background: var(--card-bg, #fff);
  padding: 14px 16px;
}
.qa-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.qa-title {
  font-weight: 600;
  font-size: 15px;
  display: inline-flex;
  align-items: center;
}
.qa-hint { color: var(--faint); font-size: 12px; }
.qa-empty { color: var(--faint); font-size: 13px; padding: 8px 0; }
.qa-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  margin: 10px 0 6px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.qa-fact-list, .qa-warning-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.qa-fact {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  flex-wrap: wrap;
}
.qa-fact-target { font-weight: 500; }
.qa-fact-kind {
  font-style: normal;
  font-size: 11px;
  color: var(--faint);
  background: var(--bg-soft, #f3f4f6);
  border-radius: 999px;
  padding: 1px 7px;
}
.qa-fact-value { color: var(--text-color, #333); }
.qa-fact-basis { font-style: normal; font-size: 11px; color: var(--faint); }
.qa-unknown-note { color: var(--faint); font-size: 12px; margin: 6px 0 0; }

.qa-budget-row { display: flex; gap: 14px; font-size: 13px; flex-wrap: wrap; }
.qa-warning-list li { font-size: 13px; }
.qa-warning-fix { font-style: normal; color: var(--faint); font-size: 12px; margin-left: 6px; }

.qa-ask { margin-top: 12px; }
.qa-suggest { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.qa-chip {
  border: 1px solid var(--border-color, #e5e7eb);
  background: transparent;
  color: var(--text-color, #333);
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}
.qa-chip:hover { border-color: var(--primary, #409eff); color: var(--primary, #409eff); }

.qa-answer {
  margin-top: 12px;
  border-left: 3px solid var(--primary, #409eff);
  background: var(--bg-soft, #f8fafc);
  border-radius: 0 8px 8px 0;
  padding: 8px 12px;
}
.qa-answer-empty { border-left-color: var(--faint); }
.qa-answer-q { font-size: 12px; color: var(--faint); margin-bottom: 4px; }
.qa-answer-a { font-size: 14px; }
.qa-answer-meta { display: flex; gap: 10px; margin-top: 6px; }
.qa-answer-target, .qa-answer-basis { font-style: normal; font-size: 11px; color: var(--faint); }
</style>
