<script setup>
/**
 * 行程服务层组件（方案 B 第二段 servicing 产物展示）
 *
 * 消费 TripPlan.plan_data 中由后端 servicing 阶段生成的字段：
 *  - transport:       大交通方案（TransportAgent 采集阶段，from/to/options[]）
 *  - transit:         市内通勤视图（相邻站点怎么走，legs[]）
 *  - checkin:         酒店入住办理指引（模板 + LLM 润色）
 *  - discount_rules:  确定性折扣规则（采集阶段，rules[]）
 *  - discounts:       选定站点折扣比价（servicing 阶段，items[]）
 *
 * 所有区块都是「有数据才显示」；缺失时整卡隐藏（不打扰）。
 * 交互只有展开/折叠，不做任何写操作 —— 纯展示层。
 */
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  // TripPlan.plan_data 的 servicing 相关字段
  transport: { type: Object, default: null },
  transit: { type: Object, default: null },
  checkin: { type: Object, default: null },
  discountRules: { type: Array, default: () => [] },
  discounts: { type: Object, default: null },
})

const { t } = useI18n()

// 是否有任何内容可展示（整体空 → 隐藏组件）
const hasAny = computed(() => {
  return !!(
    props.transport?.options?.length ||
    props.transit?.legs?.length ||
    props.checkin ||
    props.discountRules?.length ||
    props.discounts?.items?.length
  )
})

// ── 折叠状态（默认展开交通 + 入住，通勤/折扣折叠） ──
const openSections = ref({
  transport: true,
  transit: false,
  checkin: true,
  discount: false,
})
function toggle(key) {
  openSections.value[key] = !openSections.value[key]
}

// ── 交通方案 ──
const transportOptions = computed(() => props.transport?.options || [])
function transportModeLabel(mode) {
  const map = {
    driving: t('servicing.modeDriving'),
    train: t('servicing.modeTrain'),
    flight: t('servicing.modeFlight'),
    bus: t('servicing.modeBus'),
    advice: t('servicing.modeAdvice'),
  }
  return map[mode] || mode || ''
}
function priceText(o) {
  if (Array.isArray(o.price_range) && o.price_range.length === 2) {
    return `¥${o.price_range[0]} ~ ¥${o.price_range[1]}`
  }
  if (o.price_range && o.price_range.length === 1) return `¥${o.price_range[0]}`
  return t('servicing.priceUnavailable')
}
function durationText(o) {
  if (o.duration_minutes == null) return ''
  if (o.duration_minutes < 60) return `${o.duration_minutes} ${t('common.minutes')}`
  const h = Math.floor(o.duration_minutes / 60)
  const m = o.duration_minutes % 60
  return m ? `${h}h${m}m` : `${h}h`
}

// ── 市内通勤 ──
const transitLegs = computed(() => props.transit?.legs || [])

// ── 入住指引 ──
const checkin = computed(() => props.checkin || null)

// ── 折扣 ──
const discountRuleList = computed(() => props.discountRules || [])
const discountItems = computed(() => props.discounts?.items || [])
const discountNote = computed(() => props.discounts?.note || '')

// 折叠卡片头部 chevron
function chevronRotate(open) {
  return open ? 'rotate(0deg)' : 'rotate(-90deg)'
}
</script>

<template>
  <div v-if="hasAny" class="servicing-wrap">
    <!-- ── 大交通（TransportAgent） ── -->
    <div v-if="transportOptions.length" class="serv-card">
      <div class="serv-head" @click="toggle('transport')">
        <span class="serv-title"><el-icon style="margin-right: 6px"><Van /></el-icon>{{ t('servicing.transportTitle') }}</span>
        <span class="serv-route" v-if="props.transport?.from && props.transport?.to">
          {{ props.transport.from }} → {{ props.transport.to }}
        </span>
        <el-icon class="serv-chevron" :style="{ transform: chevronRotate(openSections.transport) }"><ArrowDown /></el-icon>
      </div>
      <div v-show="openSections.transport" class="serv-body">
        <div v-for="(o, i) in transportOptions" :key="i" class="transport-item">
          <div class="transport-main">
            <span class="transport-mode">{{ transportModeLabel(o.mode) }}</span>
            <span class="transport-duration" v-if="durationText(o)">{{ durationText(o) }}</span>
            <span class="transport-price">{{ priceText(o) }}</span>
          </div>
          <div class="transport-sub">
            <span v-if="o.frequency" class="transport-freq">{{ o.frequency }}</span>
            <span v-if="o.note" class="transport-note">{{ o.note }}</span>
            <a v-if="o.source_url" :href="o.source_url" target="_blank" rel="noopener" class="transport-link">
              {{ t('servicing.sourceLink') }} <el-icon style="margin-left: 2px"><TopRight /></el-icon>
            </a>
          </div>
        </div>
        <div class="serv-footnote">{{ t('servicing.transportNote') }}</div>
      </div>
    </div>

    <!-- ── 市内通勤（servicing 生成） ── -->
    <div v-if="transitLegs.length" class="serv-card">
      <div class="serv-head" @click="toggle('transit')">
        <span class="serv-title"><el-icon style="margin-right: 6px"><Position /></el-icon>{{ t('servicing.transitTitle') }}</span>
        <span class="serv-count">{{ transitLegs.length }} {{ t('servicing.legsUnit') }}</span>
        <el-icon class="serv-chevron" :style="{ transform: chevronRotate(openSections.transit) }"><ArrowDown /></el-icon>
      </div>
      <div v-show="openSections.transit" class="serv-body">
        <div v-for="(leg, i) in transitLegs" :key="i" class="transit-item">
          <span class="transit-from">{{ leg.from }}</span>
          <el-icon class="transit-arrow"><Right /></el-icon>
          <span class="transit-to">{{ leg.to }}</span>
          <span class="transit-mode">{{ leg.mode }}</span>
          <span class="transit-dist">{{ leg.distance_km }}km</span>
        </div>
        <div v-if="props.transit?.note" class="serv-footnote">{{ props.transit.note }}</div>
      </div>
    </div>

    <!-- ── 酒店入住办理指引（HotelCheckinAgent） ── -->
    <div v-if="checkin" class="serv-card">
      <div class="serv-head" @click="toggle('checkin')">
        <span class="serv-title"><el-icon style="margin-right: 6px"><Key /></el-icon>{{ t('servicing.checkinTitle') }}</span>
        <el-tag v-if="checkin.source === 'template'" size="small" type="info" round>{{ t('servicing.templateSource') }}</el-tag>
        <el-tag v-else size="small" type="success" round>{{ t('servicing.llmSource') }}</el-tag>
        <el-icon class="serv-chevron" :style="{ transform: chevronRotate(openSections.checkin) }"><ArrowDown /></el-icon>
      </div>
      <div v-show="openSections.checkin" class="serv-body">
        <div class="checkin-hotel">
          <span class="checkin-name">{{ checkin.hotel_name }}</span>
          <span v-if="checkin.hotel_address" class="checkin-addr">{{ checkin.hotel_address }}</span>
        </div>
        <div class="checkin-times" v-if="checkin.check_in_time || checkin.check_out_time">
          <span class="checkin-time" v-if="checkin.check_in_time">
            <el-icon style="margin-right: 4px"><Clock /></el-icon>{{ t('servicing.checkIn') }} {{ checkin.check_in_time }}
          </span>
          <span class="checkin-time" v-if="checkin.check_out_time">
            <el-icon style="margin-right: 4px"><Clock /></el-icon>{{ t('servicing.checkOut') }} {{ checkin.check_out_time }}
          </span>
        </div>
        <div class="checkin-block" v-if="checkin.docs_required?.length">
          <div class="checkin-block-title">{{ t('servicing.docsRequired') }}</div>
          <ul class="checkin-list">
            <li v-for="(d, i) in checkin.docs_required" :key="'d' + i">{{ d }}</li>
          </ul>
        </div>
        <div class="checkin-block" v-if="checkin.steps?.length">
          <div class="checkin-block-title">{{ t('servicing.stepsTitle') }}</div>
          <ol class="checkin-list">
            <li v-for="(s, i) in checkin.steps" :key="'s' + i">{{ s }}</li>
          </ol>
        </div>
        <div class="checkin-block" v-if="checkin.transit?.length">
          <div class="checkin-block-title">{{ t('servicing.transitToHotel') }}</div>
          <ul class="checkin-list">
            <li v-for="(tr, i) in checkin.transit" :key="'t' + i">{{ tr }}</li>
          </ul>
        </div>
        <div class="serv-footnote" v-if="checkin.disclaimer">{{ checkin.disclaimer }}</div>
      </div>
    </div>

    <!-- ── 折扣（DiscountAgent 规则 + servicing 比价） ── -->
    <div v-if="discountRuleList.length || discountItems.length" class="serv-card">
      <div class="serv-head" @click="toggle('discount')">
        <span class="serv-title"><el-icon style="margin-right: 6px"><Ticket /></el-icon>{{ t('servicing.discountTitle') }}</span>
        <span class="serv-count" v-if="discountRuleList.length + discountItems.length">
          {{ discountRuleList.length + discountItems.length }} {{ t('servicing.discountUnit') }}
        </span>
        <el-icon class="serv-chevron" :style="{ transform: chevronRotate(openSections.discount) }"><ArrowDown /></el-icon>
      </div>
      <div v-show="openSections.discount" class="serv-body">
        <!-- 实时比价（有来源才展示） -->
        <div v-if="discountItems.length" class="discount-compare">
          <div class="discount-block-title">{{ t('servicing.priceCompare') }}</div>
          <div v-for="(it, i) in discountItems" :key="'c' + i" class="discount-item">
            <span class="discount-target">{{ it.target }}</span>
            <span class="discount-note">{{ it.note }}</span>
            <a v-if="it.source_url" :href="it.source_url" target="_blank" rel="noopener" class="discount-link">
              {{ t('servicing.sourceLink') }} <el-icon style="margin-left: 2px"><TopRight /></el-icon>
            </a>
          </div>
          <div v-if="discountNote" class="serv-footnote">{{ discountNote }}</div>
        </div>
        <!-- 确定性规则 -->
        <div v-if="discountRuleList.length" class="discount-rules">
          <div class="discount-block-title">{{ t('servicing.rulesTitle') }}</div>
          <div v-for="(r, i) in discountRuleList" :key="'r' + i" class="discount-rule">
            <span class="discount-rule-target">{{ r.target }}</span>
            <span class="discount-rule-desc">{{ r.rule }}</span>
            <a v-if="r.source_url" :href="r.source_url" target="_blank" rel="noopener" class="discount-link">
              {{ t('servicing.sourceLink') }} <el-icon style="margin-left: 2px"><TopRight /></el-icon>
            </a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.servicing-wrap {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 28px;
}
.serv-card {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 14px 18px;
  box-shadow: var(--shadow-card);
  transition: box-shadow .2s;
}
.serv-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,.06); }
.serv-head {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
  flex-wrap: wrap;
}
.serv-title {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
  display: inline-flex;
  align-items: center;
}
.serv-route {
  font-size: 12.5px;
  color: var(--brand);
  background: rgba(64,110,255,.08);
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-weight: 500;
}
.serv-count {
  font-size: 12px;
  color: var(--faint);
  margin-left: auto;
}
.serv-chevron {
  margin-left: auto;
  color: var(--faint);
  transition: transform .2s;
  font-size: 13px;
}
.serv-head .serv-chevron:last-child { margin-left: auto; }
.serv-body { margin-top: 12px; }
.serv-footnote {
  margin-top: 10px;
  font-size: 12px;
  color: var(--faint);
  line-height: 1.5;
}

/* ── 交通 ── */
.transport-item {
  padding: 8px 0;
  border-bottom: 1px dashed var(--line);
}
.transport-item:last-child { border-bottom: none; }
.transport-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.transport-mode {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
  background: var(--fill);
  padding: 3px 10px;
  border-radius: var(--radius-full);
}
.transport-duration {
  font-size: 12.5px;
  color: var(--muted);
}
.transport-price {
  font-size: 13px;
  font-weight: 700;
  color: var(--brand);
  margin-left: auto;
}
.transport-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--faint);
}
.transport-freq { color: var(--ink-2); }
.transport-note { color: var(--muted); max-width: 420px; }
.transport-link {
  display: inline-flex;
  align-items: center;
  color: var(--brand);
  text-decoration: none;
  font-weight: 500;
  margin-left: auto;
}

/* ── 通勤 ── */
.transit-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
  color: var(--ink-2);
  flex-wrap: wrap;
}
.transit-from, .transit-to { font-weight: 600; color: var(--ink); }
.transit-arrow { color: var(--faint); font-size: 13px; }
.transit-mode {
  font-size: 12px;
  background: var(--fill);
  color: var(--ink-2);
  padding: 2px 8px;
  border-radius: var(--radius-full);
}
.transit-dist { font-size: 12px; color: var(--faint); margin-left: auto; }

/* ── 入住 ── */
.checkin-hotel {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.checkin-name { font-size: 14px; font-weight: 600; color: var(--ink); }
.checkin-addr { font-size: 12.5px; color: var(--muted); }
.checkin-times {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--ink-2);
}
.checkin-time { display: inline-flex; align-items: center; }
.checkin-block { margin-top: 10px; }
.checkin-block-title, .discount-block-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--muted);
  margin-bottom: 6px;
}
.checkin-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.7;
}

/* ── 折扣 ── */
.discount-item, .discount-rule {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
  color: var(--ink-2);
  flex-wrap: wrap;
}
.discount-target, .discount-rule-target {
  font-weight: 600;
  color: var(--ink);
  flex-shrink: 0;
  min-width: 72px;
}
.discount-note { flex: 1; min-width: 0; }
.discount-link {
  display: inline-flex;
  align-items: center;
  color: var(--brand);
  text-decoration: none;
  font-weight: 500;
  font-size: 12px;
  flex-shrink: 0;
}
.discount-rules { margin-top: 12px; }
</style>