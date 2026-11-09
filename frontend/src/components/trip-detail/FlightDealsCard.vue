<script setup>
// 机票特价推荐卡（FlightDeals：全网收集 → 2–3 个方案 → 用户确认）
//
// 数据来源：GET /trips/{id}/flight-deals（后端确定性排序：最省 / 日期最贴合 / 直飞优先）。
// 口径红线（与后端一致）：
// - price_kind 恒为 from：航线页展示的最低「起价」，不是所选日期实时报价；
// - 每条方案必须带 source_url（可点开核对），卡片上标注采集时间与来源；
// - 确认选择 ≠ 已订：后端落 TripBooking(status=pending)，卡片文案用「已选（未出票）」。
// 组件自己拉数据（与 TripDetailRatingCard 同构），不抬高 orchestrator 状态复杂度。
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Refresh, TopRight, Check } from '@element-plus/icons-vue'
import * as api from '@/api'

const props = defineProps({
  tripId: { type: String, required: true },
  travelers: { type: Number, default: 1 },
})

const { t } = useI18n()

const data = ref(null)
const loading = ref(false)
const refreshing = ref(false)
const choosingId = ref('')

const options = computed(() => data.value?.options || [])
const promos = computed(() => data.value?.promos || [])
const selected = computed(() => data.value?.selected || null)
const status = computed(() => data.value?.status || 'degraded')

// 有方案 / 有促销 / 降级需要重试 → 展示；skipped（无出发地）不占版面
const visible = computed(() => {
  if (!data.value) return false
  if (status.value === 'skipped') return false
  return options.value.length > 0 || promos.value.length > 0 || status.value === 'degraded'
})

const currencySymbol = computed(() => {
  const code = options.value[0]?.currency || selected.value?.currency || 'CNY'
  return { CNY: '¥', USD: '$', GBP: '£', EUR: '€', HKD: 'HK$', SGD: 'S$', JPY: 'JP¥' }[code] || ''
})

function priceText(value, currency) {
  if (value === null || value === undefined) return '—'
  const symbol =
    { CNY: '¥', USD: '$', GBP: '£', EUR: '€', HKD: 'HK$', SGD: 'S$', JPY: 'JP¥' }[currency || 'CNY'] || ''
  return `${symbol}${Number(value).toLocaleString()}`
}

function dateRange(option) {
  const out = (option.outbound_date || '').slice(5)
  const back = (option.inbound_date || '').slice(5)
  if (out && back) return `${out} → ${back}`
  return out || back || ''
}

function stopsText(option) {
  if (option.stops === 0) return t('flight.stops.direct')
  if (typeof option.stops === 'number') return t('flight.stops.n', { n: option.stops })
  return t('flight.stops.unknown')
}

function strategyLabel(strategy) {
  const map = {
    cheapest: t('flight.strategy.cheapest'),
    best_dates: t('flight.strategy.bestDates'),
    safest: t('flight.strategy.safest'),
    alternative: t('flight.strategy.alternative'),
    manual: t('flight.strategy.manual'),
  }
  return map[strategy] || ''
}

function fetchedText() {
  const raw = data.value?.fetched_at
  if (!raw) return ''
  const then = new Date(raw).getTime()
  if (Number.isNaN(then)) return ''
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60000))
  if (minutes < 1) return t('flight.fetched.justNow')
  if (minutes < 60) return t('flight.fetched.minutes', { n: minutes })
  return t('flight.fetched.hours', { n: Math.round(minutes / 60) })
}

async function load({ refresh = false } = {}) {
  if (!props.tripId) return
  if (refresh) refreshing.value = true
  else loading.value = true
  try {
    data.value = await api.getFlightDeals(props.tripId, { refresh })
  } catch {
    // 读取失败静默：机票是增强项，不能影响详情页主路径（后端已保证不编造）
    data.value = null
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

async function choose(option) {
  if (!option?.option_id || choosingId.value) return
  choosingId.value = option.option_id
  try {
    await api.chooseFlight(props.tripId, {
      option_id: option.option_id,
      travelers: props.travelers || 1,
    })
    ElMessage.success(t('flight.chooseDone'))
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.error?.message || t('flight.chooseFail'))
  } finally {
    choosingId.value = ''
  }
}

async function clearChoice() {
  if (!selected.value?.booking_id) return
  try {
    await api.clearFlightChoice(props.tripId, selected.value.booking_id)
    ElMessage.success(t('flight.clearDone'))
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.error?.message || t('flight.clearFail'))
  }
}

watch(() => props.tripId, () => load(), { immediate: true })
</script>

<template>
  <div v-if="visible" class="flight-deals">
    <div class="fd-head">
      <span class="fd-title">{{ t('flight.title') }}</span>
      <span v-if="fetchedText()" class="fd-fetched">{{ fetchedText() }}</span>
      <el-button
        size="small"
        text
        :loading="refreshing"
        class="fd-refresh"
        @click="load({ refresh: true })"
      >
        <el-icon style="margin-right: 3px"><Refresh /></el-icon>{{ t('flight.refresh') }}
      </el-button>
    </div>

    <!-- 已选：已选 ≠ 已订，明确写出「未出票」 -->
    <div v-if="selected" class="fd-selected">
      <el-icon class="fd-check"><Check /></el-icon>
      <div class="fd-selected-main">
        <div class="fd-selected-title">{{ selected.title }}</div>
        <div class="fd-selected-sub">
          {{ t('flight.selectedHint') }}
          <a
            v-if="selected.provider_url"
            :href="selected.provider_url"
            target="_blank"
            rel="noopener"
            class="fd-link"
          >
            {{ t('flight.sourceLink') }}<el-icon><TopRight /></el-icon>
          </a>
        </div>
      </div>
      <el-button size="small" text class="fd-clear" @click="clearChoice">{{ t('flight.clear') }}</el-button>
    </div>

    <div v-if="options.length" class="fd-grid">
      <div
        v-for="option in options"
        :key="option.option_id"
        class="fd-card"
        :class="`fd-card--${option.strategy}`"
      >
        <div class="fd-card-top">
          <span class="fd-chip">{{ strategyLabel(option.strategy) }}</span>
          <span class="fd-price">
            {{ priceText(option.price, option.currency) }}
            <span class="fd-price-unit">{{ t('flight.from') }}</span>
          </span>
        </div>
        <div class="fd-card-title">{{ option.title }}</div>
        <div class="fd-meta">
          <span v-if="dateRange(option)" class="fd-meta-item">{{ dateRange(option) }}</span>
          <span class="fd-meta-item">{{ stopsText(option) }}</span>
          <span v-if="option.airlines?.length" class="fd-meta-item">{{ option.airlines.join(' / ') }}</span>
        </div>
        <div class="fd-card-foot">
          <a
            v-if="option.source_url"
            :href="option.source_url"
            target="_blank"
            rel="noopener"
            class="fd-link"
          >
            {{ t('flight.source', { source: option.source || 'web' }) }}<el-icon><TopRight /></el-icon>
          </a>
          <span class="fd-conf" :title="t('flight.confidenceTip')">
            {{ t('flight.confidence', { n: Math.round((option.confidence || 0) * 100) }) }}
          </span>
        </div>
        <el-button
          size="small"
          type="primary"
          plain
          class="fd-choose"
          :loading="choosingId === option.option_id"
          @click="choose(option)"
        >
          {{ t('flight.choose') }}
        </el-button>
      </div>
    </div>

    <div v-else class="fd-empty">
      {{ data?.note || t('flight.empty') }}
      <el-button size="small" text :loading="refreshing" @click="load({ refresh: true })">
        {{ t('flight.retry') }}
      </el-button>
    </div>

    <div v-if="promos.length" class="fd-promos">
      <div class="fd-promos-title">{{ t('flight.promosTitle') }}</div>
      <a
        v-for="(promo, i) in promos"
        :key="i"
        :href="promo.source_url"
        target="_blank"
        rel="noopener"
        class="fd-promo"
      >
        <span class="fd-promo-title">{{ promo.title }}</span>
        <span v-if="promo.snippet" class="fd-promo-snippet">{{ promo.snippet }}</span>
      </a>
    </div>

    <div class="fd-footnote">
      {{ data?.note || t('flight.disclaimer') }}
      <span v-if="currencySymbol && data?.price_kind === 'from'"> · {{ t('flight.priceKindFrom') }}</span>
    </div>
  </div>
  <div v-else-if="loading" class="flight-deals fd-loading">{{ t('flight.loading') }}</div>
</template>

<style scoped>
.flight-deals {
  border: 1px solid var(--line, var(--border));
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--card, #fff);
}
.fd-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.fd-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text, var(--foreground));
}
.fd-fetched {
  font-size: 12px;
  color: var(--muted, var(--muted-foreground));
}
.fd-refresh {
  margin-left: auto;
}
.fd-selected {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 10px;
  border-radius: 8px;
  background: rgba(13, 138, 95, 0.08);
  border: 1px solid rgba(13, 138, 95, 0.25);
}
.fd-check {
  color: #0d8a5f;
}
.fd-selected-main {
  flex: 1;
  min-width: 0;
}
.fd-selected-title {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fd-selected-sub {
  font-size: 12px;
  color: var(--muted, var(--muted-foreground));
}
.fd-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px;
}
.fd-card {
  border: 1px solid var(--line, var(--border));
  border-radius: 10px;
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.fd-card--cheapest {
  border-color: rgba(194, 65, 12, 0.35);
}
.fd-card--safest {
  border-color: rgba(91, 110, 225, 0.3);
}
.fd-card-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
}
.fd-chip {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--brand-soft, rgba(0, 0, 0, 0.05));
  color: var(--brand, #b45309);
  white-space: nowrap;
}
.fd-price {
  font-size: 18px;
  font-weight: 700;
  color: var(--text, var(--foreground));
}
.fd-price-unit {
  font-size: 11px;
  font-weight: 400;
  color: var(--muted, var(--muted-foreground));
  margin-left: 2px;
}
.fd-card-title {
  font-size: 12px;
  color: var(--muted, var(--muted-foreground));
  line-height: 1.4;
}
.fd-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
}
.fd-meta-item {
  padding: 1px 6px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.04);
}
.fd-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 12px;
  color: var(--muted, var(--muted-foreground));
}
.fd-link {
  color: var(--brand, #b45309);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
}
.fd-conf {
  font-size: 11px;
  opacity: 0.8;
}
.fd-choose {
  margin-top: 2px;
  width: 100%;
}
.fd-empty {
  font-size: 12px;
  color: var(--muted, var(--muted-foreground));
  padding: 4px 0;
}
.fd-promos {
  margin-top: 12px;
  border-top: 1px dashed var(--line, var(--border));
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.fd-promos-title {
  font-size: 12px;
  font-weight: 600;
}
.fd-promo {
  display: flex;
  flex-direction: column;
  text-decoration: none;
  color: inherit;
  font-size: 12px;
  line-height: 1.4;
}
.fd-promo-title {
  color: var(--brand, #b45309);
}
.fd-promo-snippet {
  color: var(--muted, var(--muted-foreground));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fd-footnote {
  margin-top: 10px;
  font-size: 11px;
  color: var(--muted, var(--muted-foreground));
  line-height: 1.5;
}
.fd-loading {
  font-size: 12px;
  color: var(--muted, var(--muted-foreground));
}
@media print {
  .flight-deals {
    display: none;
  }
}
</style>
