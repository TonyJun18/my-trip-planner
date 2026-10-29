<script setup>
import { computed, ref } from 'vue'
import { MagicStick, DataLine, Suitcase, RefreshRight, Clock, DataAnalysis, List, Plus, Minus, Edit, Wallet, WarningFilled, CircleCheck, Loading } from '@element-plus/icons-vue'
import CollapsibleSection from '@/components/CollapsibleSection.vue'
import QualityCard from '@/components/QualityCard.vue'
import BookingPanel from '@/components/BookingPanel.vue'
import JourneyTimeline from '@/components/JourneyTimeline.vue'
import PassportPanel from '@/components/PassportPanel.vue'
import StoryCardGenerator from '@/components/StoryCardGenerator.vue'
import PackingList from '@/components/PackingList.vue'
import TripServicing from '@/components/TripServicing.vue'
import HotelRecommend from '@/components/HotelRecommend.vue'
import TripEventFeed from '@/components/TripEventFeed.vue'

// 内部子面板 ref（JourneyTimeline / PassportPanel），暴露给 orchestrator 刷新投影
const journeyInner = ref(null)
const passportInner = ref(null)
defineExpose({
  loadJourney: () => journeyInner.value?.load(),
  loadPassport: () => passportInner.value?.load(),
})

// 工具箱：3 组 CollapsibleSection 编排容器（规划修订 / 旅程执行 / 装备素材）。
// 阶段一保持结构与 default-open 不变，纯编排；exportAll 由 orchestrator 透传 forceOpen。
// revise 相关字段 = useRevise 解构原样透传（状态所有权仍在 orchestrator）。
const props = defineProps({
  trip: { type: Object, required: true },
  plan: { type: Object, default: null },
  planB: { type: Object, default: null },
  activePlan: { type: String, default: 'main' },
  planOptions: { type: Array, default: () => [] },
  planBBudget: { type: Object, default: null },
  planBTotal: { type: Number, default: 0 },
  hotelCandidates: { type: Array, default: () => [] },
  servicingProps: { type: Object, default: () => ({}) },
  bookingBadge: { type: String, default: '' },
  journeyBadge: { type: String, default: '' },
  passportBadge: { type: String, default: '' },
  exportAll: { type: Boolean, default: false },
  // useRevise 透传（修订表单 + 状态 + diff 渲染）
  reviseMsg: { type: String, default: '' },
  revising: { type: Boolean, default: false },
  reviseError: { type: String, default: '' },
  lastReviseSummary: { type: String, default: '' },
  reviseDone: { type: Boolean, default: false },
  lastReviseDiff: { type: Array, default: () => [] },
  visibleReviseDiff: { type: Array, default: () => [] },
  reviseDiffMore: { type: Number, default: 0 },
  lastReviseQuality: { type: Object, default: null },
  diffText: { type: Function, default: () => (a) => a?.op || '' },
  // 面板白名单：null = 全部（v1 分组平铺）；数组 = 只渲染列出的面板（阶段二时机收纳）
  keys: { type: Array, default: null },
  // flat：嵌在 Tab / 工作台卡内 → 不渲染分组标题与虚线分隔
  flat: { type: Boolean, default: false },
  // 已被提到主路径（地图与行程大纲之间）的工具：此处跳过渲染，避免同屏两份。
  // flag 关闭（v1 平铺）时传空数组 → 修订/备选仍留在工具箱内，G1 对照组成立。
  hoistedKeys: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'plan-change', 'revise', 'revise-input', 'changed', 'arranged', 'tool-open',
])

const planBDisplay = computed(() => props.planB)
const timeGateIssues = computed(() => props.plan?.time_gate?.issues || [])
const quality = computed(() => props.plan?.quality || null)

// 面板存在性判定（keys 为 null 时全部渲染）
function has(key) {
  return !props.keys || props.keys.includes(key)
}

// 是否已被提到主路径（由 TripDetailPlanTools 承载）
function isHoisted(key) {
  return props.hoistedKeys.includes(key)
}

</script>

<template>
  <div class="toolbox" :class="{ flat }">
  <!-- ═══ 工具箱：规划修订 ═══ -->
  <div v-if="['revise', 'planb', 'timegate', 'quality'].some((k) => has(k) && !isHoisted(k))" class="toolbox-group" :class="{ first: flat }">
    <div v-if="!flat" class="toolbox-label"><el-icon style="margin-right: 5px"><MagicStick /></el-icon>{{ $t('tripDetail.toolboxPlan') }}</div>
    <div class="aux-area">
      <!-- AI 调整行程（若已被提到主路径则跳过，见 TripDetailPlanTools） -->
      <CollapsibleSection
        v-if="has('revise') && !isHoisted('revise')"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.revise.${trip.id}`"
        @click="emit('tool-open', 'ai_revise')"
      >
        <template #title>{{ $t('tripDetail.reviseTitle') }}</template>
        <div class="revise-card aux-child">
          <div class="revise-head">
            <span class="revise-hint">{{ $t('tripDetail.reviseHint') }}</span>
          </div>
          <div class="revise-row">
            <el-input
              :model-value="reviseMsg"
              :placeholder="$t('tripDetail.revisePlaceholder')"
              size="large"
              clearable
              :disabled="revising"
              @update:model-value="(v) => emit('revise-input', v)"
              @keyup.enter="emit('revise')"
            />
            <el-button type="primary" size="large" :loading="revising" @click="emit('revise')">
              <el-icon style="margin-right: 4px"><MagicStick /></el-icon>{{ $t('tripDetail.reviseBtn') }}
            </el-button>
          </div>
          <!-- 加载态提示 -->
          <div v-if="revising" class="revise-loading">
            <el-icon class="is-loading"><Loading /></el-icon>{{ $t('tripDetail.reviseLoading') }}
          </div>
          <!-- 错误态 -->
          <transition name="el-fade-in">
            <div v-if="reviseError" class="revise-error" role="alert">
              <el-icon style="margin-right: 6px; flex-shrink: 0; margin-top: 2px"><WarningFilled /></el-icon>
              <div class="revise-error-body">
                <div>{{ reviseError }}</div>
                <div class="revise-error-sub">{{ $t('tripDetail.reviseFailRetry') }}</div>
              </div>
            </div>
          </transition>
          <!-- 成功摘要 -->
          <transition name="el-fade-in">
            <div v-if="lastReviseSummary" class="revise-summary">
              <el-icon style="margin-right: 4px; color: var(--success)"><CircleCheck /></el-icon>
              {{ lastReviseSummary }}
            </div>
          </transition>
          <!-- 变更 diff -->
          <transition name="el-fade-in">
            <div v-if="reviseDone" class="revise-diff">
              <div class="revise-diff-head">
                <span class="revise-diff-title"><el-icon style="margin-right: 5px"><List /></el-icon>{{ $t('tripDetail.diffTitle') }}</span>
                <span class="revise-diff-count" v-if="lastReviseDiff.length">{{ $t('tripDetail.diffCount', { n: lastReviseDiff.length }) }}</span>
              </div>
              <template v-if="lastReviseDiff.length">
                <div v-for="(a, i) in visibleReviseDiff" :key="i" class="revise-diff-item" :class="'op-' + (a.op || '')">
                  <el-icon class="revise-diff-icon"><template v-if="a.op === 'add'"><Plus /></template><template v-else-if="a.op === 'remove'"><Minus /></template><template v-else><Edit /></template></el-icon>
                  <span class="revise-diff-text">{{ diffText(a) }}</span>
                </div>
                <div v-if="reviseDiffMore" class="revise-diff-more">
                  {{ $t('tripDetail.reviseDiffMore', { n: reviseDiffMore }) }}
                </div>
              </template>
              <div v-else class="revise-diff-empty">{{ $t('tripDetail.diffEmpty') }}</div>
            </div>
          </transition>
          <!-- 修订质控 -->
          <transition name="el-fade-in">
            <div v-if="lastReviseQuality" class="revise-quality">
              <div class="revise-quality-head">
                <el-icon style="margin-right: 5px"><DataAnalysis /></el-icon>
                <span class="revise-quality-title">{{ $t('tripDetail.reviseQualityTitle') }}</span>
                <span class="revise-quality-score" :class="{ pass: lastReviseQuality.passed, warn: !lastReviseQuality.passed }">
                  {{ lastReviseQuality.score }}/100
                </span>
                <span v-if="lastReviseQuality.fix_applied" class="revise-quality-badge">{{ $t('tripDetail.reviseQualityFixApplied') }}</span>
                <span v-if="lastReviseQuality.degraded" class="revise-quality-badge degraded">{{ $t('tripDetail.reviseQualityDegraded') }}</span>
              </div>
              <div v-if="lastReviseQuality.summary" class="revise-quality-summary">{{ lastReviseQuality.summary }}</div>
              <ul v-if="lastReviseQuality.issues && lastReviseQuality.issues.length" class="revise-quality-issues">
                <li v-for="(issue, i) in lastReviseQuality.issues.slice(0, 3)" :key="i" class="revise-quality-issue">
                  <span class="revise-quality-sev" :class="issue.severity">{{ issue.severity }}</span>
                  {{ issue.message }}
                </li>
              </ul>
            </div>
          </transition>
        </div>
      </CollapsibleSection>

      <!-- 行程：Plan B 备选（若已被提到主路径则跳过） -->
      <CollapsibleSection
        v-if="has('planb') && !isHoisted('planb') && planBDisplay"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.planb.${trip.id}`"
        @click="emit('tool-open', 'plan_b')"
      >
        <template #title>{{ $t('tripDetail.planBTitle') }}</template>
        <div class="planb-card aux-child">
          <div class="planb-head">
            <el-segmented :model-value="activePlan" :options="planOptions" size="small" @change="(v) => emit('plan-change', v)" />
          </div>
          <div v-if="activePlan === 'plan_b'" class="planb-body">
            <div class="planb-meta">
              <span class="planb-label">{{ planBDisplay.label }}</span>
              <span class="planb-desc">{{ planBDisplay.description }}</span>
            </div>
            <div class="planb-deltas">
              <div v-for="(d, i) in planBDisplay.deltas" :key="i" class="planb-delta">
                <el-icon style="margin-right: 6px; color: var(--brand)"><RefreshRight /></el-icon>{{ d }}
              </div>
            </div>
            <div class="planb-budget" v-if="planBBudget">
              <el-icon style="margin-right: 6px"><Wallet /></el-icon>
              {{ $t('tripDetail.planBBudgetLabel') }} ¥{{ planBTotal }}
              <span v-if="planBBudget.by_type?.hotel" class="planb-budget-sub">
                {{ $t('common.typeHotel') }} ¥{{ planBBudget.by_type.hotel }}
              </span>
            </div>
            <div class="planb-hint">{{ $t('tripDetail.planBHint') }}</div>
          </div>
        </div>
      </CollapsibleSection>

      <!-- TimeGate 时间校验 -->
      <CollapsibleSection
        v-if="has('timegate') && timeGateIssues.length"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.timegate.${trip.id}`"
      >
        <template #title>{{ $t('tripDetail.timeGateTitle') }}</template>
        <div class="timegate-card aux-child">
          <div class="timegate-head">
            <span class="timegate-title"><el-icon style="margin-right: 6px"><Clock /></el-icon>{{ $t('tripDetail.timeGateTitle') }}</span>
            <span class="timegate-badge">{{ $t('tripDetail.timeGateBasis') }}</span>
          </div>
          <ul class="timegate-list">
            <li v-for="(iss, i) in timeGateIssues.slice(0, 6)" :key="i" class="timegate-item">
              <span class="timegate-sev">{{ $t('tripDetail.timeGateWarn') }}</span>
              <span v-if="iss.day_number" class="timegate-day">Day {{ iss.day_number }}</span>
              <span class="timegate-msg">{{ iss.message }}</span>
              <span v-if="iss.suggestion" class="timegate-suggestion">→ {{ iss.suggestion }}</span>
            </li>
          </ul>
        </div>
      </CollapsibleSection>

      <!-- AI 质检 -->
      <CollapsibleSection
        v-if="has('quality')"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.quality.${trip.id}`"
        @click="emit('tool-open', 'qa')"
      >
        <template #title>{{ $t('quality.reportTitle') }}</template>
        <div class="aux-child detail-quality">
          <QualityCard :quality="quality" />
        </div>
      </CollapsibleSection>
    </div>
  </div>

  <!-- ═══ 工具箱：旅程执行 ═══ -->
  <div v-if="['booking', 'journey', 'passport', 'story'].some((k) => has(k))" class="toolbox-group">
    <div v-if="!flat" class="toolbox-label"><el-icon style="margin-right: 5px"><DataLine /></el-icon>{{ $t('tripDetail.toolboxOps') }}</div>
    <div class="aux-area">
      <CollapsibleSection
        v-if="has('booking')"
        plain
        :default-open="true"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.booking.${trip.id}`"
      >
        <template #title>{{ $t('booking.panelTitle') }}</template>
        <template #extra>
          <span v-if="bookingBadge" class="cs-badge">{{ bookingBadge }}</span>
        </template>
        <BookingPanel :trip-id="trip.id" @changed="emit('changed')" />
      </CollapsibleSection>

      <CollapsibleSection
        v-if="has('journey')"
        plain
        :default-open="true"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.journey.${trip.id}`"
      >
        <template #title>{{ $t('journey.panelTitle') }}</template>
        <template #extra>
          <span v-if="journeyBadge" class="cs-badge">{{ journeyBadge }}</span>
        </template>
        <JourneyTimeline ref="journeyInner" :trip-id="trip.id" @changed="emit('changed')" />
      </CollapsibleSection>

      <CollapsibleSection
        v-if="has('passport')"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.passport.${trip.id}`"
      >
        <template #title>{{ $t('passport.panelTitle') }}</template>
        <template #extra>
          <span v-if="passportBadge" class="cs-badge">{{ passportBadge }} ✦</span>
        </template>
        <PassportPanel ref="passportInner" :trip-id="trip.id" @changed="emit('changed')" />
      </CollapsibleSection>

      <CollapsibleSection
        v-if="has('story')"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.story.${trip.id}`"
      >
        <template #title>{{ $t('story.panelTitle') }}</template>
        <StoryCardGenerator :trip-id="trip.id" />
      </CollapsibleSection>
    </div>
  </div>

  <!-- ═══ 工具箱：装备素材 ═══ -->
  <div v-if="['packing', 'servicing', 'hotel', 'events'].some((k) => has(k))" class="toolbox-group">
    <div v-if="!flat" class="toolbox-label"><el-icon style="margin-right: 5px"><Suitcase /></el-icon>{{ $t('tripDetail.toolboxGear') }}</div>
    <div class="aux-area">
      <CollapsibleSection
        v-if="has('packing')"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.packing.${trip.id}`"
      >
        <template #title>{{ $t('packing.title') }}</template>
        <PackingList :trip-id="trip.id" />
      </CollapsibleSection>

      <CollapsibleSection
        v-if="has('servicing')"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.servicing.${trip.id}`"
      >
        <template #title>{{ $t('servicing.panelTitle') }}</template>
        <TripServicing
          :transport="servicingProps.transport"
          :transit="servicingProps.transit"
          :checkin="servicingProps.checkin"
          :discount-rules="servicingProps.discountRules"
          :discounts="servicingProps.discounts"
        />
      </CollapsibleSection>

      <CollapsibleSection
        v-if="has('hotel')"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.hotel.${trip.id}`"
      >
        <template #title>{{ $t('hotel.recommendTitle') }}</template>
        <HotelRecommend :hotels="hotelCandidates" :days="trip.days" actionable @arranged="emit('arranged')" />
      </CollapsibleSection>

      <CollapsibleSection
        v-if="has('events')"
        plain
        :default-open="false"
        :force-open="exportAll"
        :storage-key="`tripDetail.aux.v2.events.${trip.id}`"
      >
        <template #title>{{ $t('events.title') }}</template>
        <TripEventFeed :trip-id="trip.id" />
      </CollapsibleSection>
    </div>
  </div>
  </div>
</template>

<style scoped>
.toolbox-group {
  margin-top: 22px;
  border-top: 1px dashed var(--line);
  padding-top: 14px;
}
/* flat：嵌在工作台卡内（tab 收纳）——去掉首组的虚线分隔与外部间距 */
.toolbox.flat .toolbox-group {
  margin-top: 0;
  border-top: none;
  padding-top: 0;
}
/* flat 模式（嵌在工作台 tab 内）收起子面板自带的重复标题：
   折叠头已给出标题，面板内再写一遍「预订 / 旅程追踪 / 护照 / 故事卡」是纯噪音。
   - 预订 / 故事卡：内部头只有「标题 + ？提示」，整行隐藏
   - 追踪 / 护照：内部头还带状态标签与徽章计数，只隐藏标题并把剩余内容靠右 */
.toolbox.flat :deep(.booking-header),
.toolbox.flat :deep(.story-header) {
  display: none;
}
.toolbox.flat :deep(.journey-title),
.toolbox.flat :deep(.passport-title) {
  display: none;
}
.toolbox.flat :deep(.passport-header) {
  justify-content: flex-end;
  gap: 8px;
}
/* 追踪面板的状态标签折叠头已经有了（「2/11 · 进行中」），内部再放一遍是同屏重复 */
.toolbox.flat :deep(.journey-header) {
  display: none;
}
.toolbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.aux-area {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.aux-child {
  margin-bottom: 0;
}
.cs-badge {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--muted);
  background: var(--fill);
  border: 1px solid var(--line);
  border-radius: var(--radius-full);
  padding: 2px 10px;
  line-height: 1.6;
  white-space: nowrap;
}

/* AI 调整 */
.revise-card {
  background: linear-gradient(135deg, var(--brand-soft), var(--card) 60%);
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  padding: 16px 20px;
  margin-bottom: 20px;
}
.revise-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.revise-hint { font-size: 12px; color: var(--muted); }
.revise-row { display: flex; gap: 10px; }
.revise-loading { margin-top: 10px; font-size: 13px; color: var(--muted); display: inline-flex; align-items: center; gap: 6px; }
.revise-error { margin-top: 10px; font-size: 13px; color: var(--warning); background: var(--el-color-warning-light-9); border: 1px solid var(--el-color-warning-light-7); border-radius: var(--radius-sm); padding: 8px 10px; display: flex; align-items: flex-start; }
.revise-error .el-icon { flex-shrink: 0; color: var(--warning); margin-top: 2px; }
.revise-error-body { display: flex; flex-direction: column; gap: 2px; }
.revise-error-sub { font-size: 12px; color: var(--muted); }
.revise-summary { margin-top: 10px; font-size: 13px; color: var(--success); background: var(--el-color-success-light-9); padding: 8px 12px; border: 1px solid var(--el-color-success-light-7); border-radius: var(--radius-sm); display: inline-flex; align-items: center; }
.revise-diff { margin-top: 10px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius-md); padding: 10px 12px; }
.revise-diff-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.revise-diff-title { font-size: 13px; font-weight: 600; color: var(--ink); display: inline-flex; align-items: center; }
.revise-diff-count { font-size: 12px; color: var(--faint); }
.revise-diff-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: var(--radius-sm); font-size: 13px; color: var(--ink-2); }
.revise-diff-item + .revise-diff-item { margin-top: 2px; }
.revise-diff-item.op-add { background: rgba(16,185,129,.07); }
.revise-diff-item.op-remove { background: rgba(239,68,68,.07); }
.revise-diff-item.op-replace { background: rgba(217,119,6,.08); }
.revise-diff-icon { font-size: 14px; flex-shrink: 0; }
.revise-diff-item.op-add .revise-diff-icon { color: var(--success); }
.revise-diff-item.op-remove .revise-diff-icon { color: var(--danger); }
.revise-diff-item.op-replace .revise-diff-icon { color: var(--warning); }
.revise-diff-text { line-height: 1.45; }
.revise-diff-empty { font-size: 12.5px; color: var(--faint); padding: 6px 8px; background: rgba(0,0,0,.02); border-radius: var(--radius-sm); }
.revise-diff-more { margin-top: 6px; font-size: 12px; color: var(--faint); padding: 4px 8px; border-top: 1px dashed var(--line); }
.revise-quality { margin-top: 10px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius-md); padding: 10px 12px; }
.revise-quality-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.revise-quality-title { font-size: 13px; font-weight: 600; color: var(--ink); display: inline-flex; align-items: center; }
.revise-quality-score { font-size: 13px; font-weight: 700; }
.revise-quality-score.pass { color: var(--success); }
.revise-quality-score.warn { color: var(--warning); }
.revise-quality-badge { font-size: 11px; color: var(--success); background: var(--el-color-success-light-9); border-radius: 999px; padding: 1px 8px; }
.revise-quality-badge.degraded { color: var(--warning); background: var(--el-color-warning-light-9); }
.revise-quality-summary { font-size: 13px; color: var(--ink-2); line-height: 1.5; }
.revise-quality-issues { margin: 6px 0 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
.revise-quality-issue { display: flex; align-items: baseline; gap: 6px; font-size: 12.5px; color: var(--muted); }
.revise-quality-sev { flex-shrink: 0; font-size: 10.5px; color: var(--warning); background: var(--el-color-warning-light-8); border-radius: 4px; padding: 0 6px; }

/* Plan B */
.planb-card { background: linear-gradient(135deg, var(--brand-soft), var(--card) 60%); border: 1px solid var(--line); border-radius: var(--radius-xl); padding: 14px 20px; margin-bottom: 20px; }
.planb-head { display: flex; align-items: center; justify-content: flex-end; gap: 12px; flex-wrap: wrap; }
.planb-body { margin-top: 12px; }
.planb-meta { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.planb-label { font-size: 13px; font-weight: 700; color: var(--brand); background: var(--brand-soft); padding: 3px 10px; border-radius: var(--radius-full); }
.planb-desc { font-size: 13px; color: var(--ink-2); }
.planb-deltas { margin-top: 10px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius-md); padding: 8px 12px; }
.planb-delta { display: flex; align-items: flex-start; gap: 4px; font-size: 13px; color: var(--ink-2); line-height: 1.5; padding: 4px 0; }
.planb-delta .el-icon { flex-shrink: 0; margin-top: 3px; }
.planb-budget { margin-top: 10px; font-size: 13px; color: var(--ink); font-weight: 600; display: inline-flex; align-items: center; }
.planb-budget-sub { margin-left: 10px; font-weight: 500; color: var(--muted); }
.planb-hint { margin-top: 8px; font-size: 12px; color: var(--faint); }

/* TimeGate */
.timegate-card { margin-top: 4px; border: 1px solid var(--el-color-warning-light-7); background: var(--el-color-warning-light-9); border-radius: var(--radius-lg); padding: 12px 14px; }
.timegate-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.timegate-title { font-size: 14px; font-weight: 600; color: var(--warning); display: inline-flex; align-items: center; }
.timegate-badge { font-size: 11px; color: var(--warning); background: var(--el-color-warning-light-7); border-radius: 999px; padding: 1px 8px; }
.timegate-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.timegate-item { display: flex; align-items: baseline; gap: 6px; font-size: 13px; color: var(--ink-2); }
.timegate-sev { flex-shrink: 0; font-size: 11px; color: var(--warning); background: var(--el-color-warning-light-8); border-radius: 4px; padding: 0 6px; }
.timegate-day { flex-shrink: 0; font-weight: 600; }
.timegate-msg { flex: 1; min-width: 0; }
.timegate-suggestion { color: var(--warning); font-size: 12px; }

.detail-quality { margin-top: 4px; }

@media (max-width: 640px) {
  .revise-card { padding: 14px; }
  .revise-row { flex-direction: column; gap: 8px; }
  .revise-row :deep(.el-button) { width: 100%; margin-left: 0; min-height: 44px; }
}
</style>