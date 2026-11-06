<script setup>
import { MagicStick, RefreshRight, Wallet, List, Plus, Minus, Edit, WarningFilled, CircleCheck, Loading, DataAnalysis } from '@element-plus/icons-vue'

/**
 * 规划工具条（主路径）：AI 调整行程 + 行程备选方案。
 *
 * 为什么从工作台提到地图与行程大纲之间：
 * - 这是两个**主线操作**（改行程 / 对比备选）。上一版收进底部工作台的
 *   tab 里，用户要先滚过整段行程大纲才够得着，属于「主操作埋在次级容器」。
 * - 提到地图下方后，视线是「看地图 → 改计划 → 看行程大纲」，形成一条闭环。
 * - 工作台只保留低频工具（时间校验 / 质检 / 住宿 / 预订 / 行李 / 素材）。
 *
 * 可见性（2026-11-06 修正）：AI 调整行程**任何时机都常驻**（planning / prep /
 * live / finished），只在导出态隐藏。上一版按 planning 才显示，行前换酒店、
 * 行中顺延/删站这些高频场景全都找不到入口。行程备选段按 planB 数据条件渲染。
 *
 * 收敛原则：
 * - 同一张卡内两段，中间虚线分隔；不做折叠（折叠会让主操作又藏起来）
 * - 历史状态（loading / error / 成功摘要 / diff / 质检）沿用原样式，避免老用户重新学习
 */
defineProps({
  planB: { type: Object, default: null },
  activePlan: { type: String, default: 'main' },
  planOptions: { type: Array, default: () => [] },
  planBBudget: { type: Object, default: null },
  planBTotal: { type: Number, default: 0 },
  // useRevise 状态原样透传（所有权仍在 orchestrator）
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
})

const emit = defineEmits(['revise', 'revise-input', 'plan-change', 'tool-open'])

// 埋点：点开 AI 调整 / 切换备选（G1 判定线口径不变）
function onReviseClick() {
  emit('tool-open', 'ai_revise')
}
function onPlanChange(v) {
  if (v === 'plan_b') emit('tool-open', 'plan_b')
  emit('plan-change', v)
}
</script>

<template>
  <section class="plan-tools">
    <!-- ── AI 调整行程（规划期唯一的高频输入） ── -->
    <div class="pt-block" @click.capture="onReviseClick">
      <div class="pt-head">
        <span class="pt-title">
          <el-icon class="pt-title-icon"><MagicStick /></el-icon>{{ $t('tripDetail.reviseTitle') }}
        </span>
        <span class="pt-hint">{{ $t('tripDetail.reviseHint') }}</span>
      </div>

      <div class="pt-row">
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

      <div v-if="revising" class="pt-loading">
        <el-icon class="is-loading"><Loading /></el-icon>{{ $t('tripDetail.reviseLoading') }}
      </div>

      <div v-if="reviseError" class="pt-error" role="alert">
        <el-icon style="margin-right: 6px; flex-shrink: 0; margin-top: 2px"><WarningFilled /></el-icon>
        <div class="pt-error-body">
          <div>{{ reviseError }}</div>
          <div class="pt-error-sub">{{ $t('tripDetail.reviseFailRetry') }}</div>
        </div>
      </div>

      <div v-if="lastReviseSummary" class="pt-summary">
        <el-icon style="margin-right: 4px; color: var(--success)"><CircleCheck /></el-icon>
        {{ lastReviseSummary }}
      </div>

      <div v-if="reviseDone" class="pt-diff">
        <div class="pt-diff-head">
          <span class="pt-diff-title"><el-icon style="margin-right: 5px"><List /></el-icon>{{ $t('tripDetail.diffTitle') }}</span>
          <span v-if="lastReviseDiff.length" class="pt-diff-count">{{ $t('tripDetail.diffCount', { n: lastReviseDiff.length }) }}</span>
        </div>
        <template v-if="lastReviseDiff.length">
          <div v-for="(a, i) in visibleReviseDiff" :key="i" class="pt-diff-item" :class="'op-' + (a.op || '')">
            <el-icon class="pt-diff-icon"><template v-if="a.op === 'add'"><Plus /></template><template v-else-if="a.op === 'remove'"><Minus /></template><template v-else><Edit /></template></el-icon>
            <span class="pt-diff-text">{{ diffText(a) }}</span>
          </div>
          <div v-if="reviseDiffMore" class="pt-diff-more">{{ $t('tripDetail.reviseDiffMore', { n: reviseDiffMore }) }}</div>
        </template>
        <div v-else class="pt-diff-empty">{{ $t('tripDetail.diffEmpty') }}</div>
      </div>

      <div v-if="lastReviseQuality" class="pt-quality">
        <div class="pt-quality-head">
          <el-icon style="margin-right: 5px"><DataAnalysis /></el-icon>
          <span class="pt-quality-title">{{ $t('tripDetail.reviseQualityTitle') }}</span>
          <span class="pt-quality-score" :class="{ pass: lastReviseQuality.passed, warn: !lastReviseQuality.passed }">
            {{ lastReviseQuality.score }}/100
          </span>
          <span v-if="lastReviseQuality.fix_applied" class="pt-quality-badge">{{ $t('tripDetail.reviseQualityFixApplied') }}</span>
          <span v-if="lastReviseQuality.degraded" class="pt-quality-badge degraded">{{ $t('tripDetail.reviseQualityDegraded') }}</span>
        </div>
        <div v-if="lastReviseQuality.summary" class="pt-quality-summary">{{ lastReviseQuality.summary }}</div>
        <ul v-if="lastReviseQuality.issues && lastReviseQuality.issues.length" class="pt-quality-issues">
          <li v-for="(issue, i) in lastReviseQuality.issues.slice(0, 3)" :key="i" class="pt-quality-issue">
            <span class="pt-quality-sev" :class="issue.severity">{{ issue.severity }}</span>
            {{ issue.message }}
          </li>
        </ul>
      </div>
    </div>

    <!-- ── 行程备选方案（主/备切换 + 差异对比） ── -->
    <div v-if="planB" class="pt-block pt-planb">
      <div class="pt-head">
        <span class="pt-title">
          <el-icon class="pt-title-icon"><RefreshRight /></el-icon>{{ $t('tripDetail.planBTitle') }}
        </span>
        <el-segmented
          :model-value="activePlan"
          :options="planOptions"
          size="small"
          @change="onPlanChange"
        />
      </div>

      <template v-if="activePlan === 'plan_b'">
        <div class="pt-planb-meta">
          <span class="pt-planb-label">{{ planB.label }}</span>
          <span class="pt-planb-desc">{{ planB.description }}</span>
        </div>
        <div class="pt-planb-deltas">
          <div v-for="(d, i) in planB.deltas" :key="i" class="pt-planb-delta">
            <el-icon style="margin-right: 6px; color: var(--brand)"><RefreshRight /></el-icon>{{ d }}
          </div>
        </div>
        <div class="pt-planb-foot">
          <span v-if="planBBudget" class="pt-planb-budget">
            <el-icon style="margin-right: 6px"><Wallet /></el-icon>
            {{ $t('tripDetail.planBBudgetLabel') }} ¥{{ planBTotal }}
            <span v-if="planBBudget.by_type?.hotel" class="pt-planb-budget-sub">
              {{ $t('common.typeHotel') }} ¥{{ planBBudget.by_type.hotel }}
            </span>
          </span>
          <span class="pt-planb-hint">{{ $t('tripDetail.planBHint') }}</span>
        </div>
      </template>
      <p v-else class="pt-planb-idle">{{ $t('tripDetail.planBHint') }}</p>
    </div>
  </section>
</template>

<style scoped>
.plan-tools {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 4px 16px;
  margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.pt-block { padding: 12px 0; }
.pt-block + .pt-block { border-top: 1px dashed var(--line); }

.pt-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.pt-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}
.pt-title-icon { color: var(--brand); font-size: 15px; }
.pt-hint { font-size: 12px; color: var(--muted); margin-left: auto; }

.pt-row { display: flex; gap: 10px; }
.pt-row :deep(.el-input) { flex: 1; min-width: 0; }
.pt-row :deep(.el-button) { flex-shrink: 0; }

.pt-loading { margin-top: 10px; font-size: 13px; color: var(--muted); display: inline-flex; align-items: center; gap: 6px; }

.pt-error {
  margin-top: 10px; font-size: 13px; color: var(--warning);
  background: var(--el-color-warning-light-9);
  border: 1px solid var(--el-color-warning-light-7);
  border-radius: var(--radius-sm);
  padding: 8px 10px; display: flex; align-items: flex-start;
}
.pt-error .el-icon { flex-shrink: 0; color: var(--warning); margin-top: 2px; }
.pt-error-body { display: flex; flex-direction: column; gap: 2px; }
.pt-error-sub { font-size: 12px; color: var(--muted); }

.pt-summary {
  margin-top: 10px; font-size: 13px; color: var(--success);
  background: var(--el-color-success-light-9);
  padding: 8px 12px;
  border: 1px solid var(--el-color-success-light-7);
  border-radius: var(--radius-sm);
  display: inline-flex; align-items: center;
}

.pt-diff { margin-top: 10px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius-md); padding: 10px 12px; }
.pt-diff-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.pt-diff-title { font-size: 13px; font-weight: 600; color: var(--ink); display: inline-flex; align-items: center; }
.pt-diff-count { font-size: 12px; color: var(--faint); }
.pt-diff-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: var(--radius-sm); font-size: 13px; color: var(--ink-2); }
.pt-diff-item + .pt-diff-item { margin-top: 2px; }
.pt-diff-item.op-add { background: rgba(16, 185, 129, 0.07); }
.pt-diff-item.op-remove { background: rgba(239, 68, 68, 0.07); }
.pt-diff-item.op-replace { background: rgba(217, 119, 6, 0.08); }
.pt-diff-icon { font-size: 14px; flex-shrink: 0; }
.pt-diff-item.op-add .pt-diff-icon { color: var(--success); }
.pt-diff-item.op-remove .pt-diff-icon { color: var(--danger); }
.pt-diff-item.op-replace .pt-diff-icon { color: var(--warning); }
.pt-diff-text { line-height: 1.45; }
.pt-diff-empty { font-size: 12.5px; color: var(--faint); padding: 6px 8px; background: rgba(0, 0, 0, 0.02); border-radius: var(--radius-sm); }
.pt-diff-more { margin-top: 6px; font-size: 12px; color: var(--faint); padding: 4px 8px; border-top: 1px dashed var(--line); }

.pt-quality { margin-top: 10px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius-md); padding: 10px 12px; }
.pt-quality-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.pt-quality-title { font-size: 13px; font-weight: 600; color: var(--ink); display: inline-flex; align-items: center; }
.pt-quality-score { font-size: 13px; font-weight: 700; }
.pt-quality-score.pass { color: var(--success); }
.pt-quality-score.warn { color: var(--warning); }
.pt-quality-badge { font-size: 11px; color: var(--success); background: var(--el-color-success-light-9); border-radius: 999px; padding: 1px 8px; }
.pt-quality-badge.degraded { color: var(--warning); background: var(--el-color-warning-light-9); }
.pt-quality-summary { font-size: 13px; color: var(--ink-2); line-height: 1.5; }
.pt-quality-issues { margin: 6px 0 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
.pt-quality-issue { display: flex; align-items: baseline; gap: 6px; font-size: 12.5px; color: var(--muted); }
.pt-quality-sev { flex-shrink: 0; font-size: 10.5px; color: var(--warning); background: var(--el-color-warning-light-8); border-radius: 4px; padding: 0 6px; }

/* 备选方案 */
.pt-planb .pt-head { margin-bottom: 0; }
.pt-planb .pt-head :deep(.el-segmented) { margin-left: auto; }
.pt-planb-meta { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
.pt-planb-label { font-size: 12.5px; font-weight: 700; color: var(--brand); background: var(--brand-soft); padding: 3px 10px; border-radius: var(--radius-full); }
.pt-planb-desc { font-size: 13px; color: var(--ink-2); }
.pt-planb-deltas { margin-top: 10px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius-md); padding: 8px 12px; }
.pt-planb-delta { display: flex; align-items: flex-start; gap: 4px; font-size: 13px; color: var(--ink-2); line-height: 1.5; padding: 4px 0; }
.pt-planb-delta .el-icon { flex-shrink: 0; margin-top: 3px; }
.pt-planb-foot { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-top: 10px; }
.pt-planb-budget { font-size: 13px; color: var(--ink); font-weight: 600; display: inline-flex; align-items: center; }
.pt-planb-budget-sub { margin-left: 10px; font-weight: 500; color: var(--muted); }
.pt-planb-hint { font-size: 12px; color: var(--faint); line-height: 1.5; }
/* 「当前行程」态：留一句说明，避免这一段看起来是个空块 */
.pt-planb-idle { margin: 8px 0 0; font-size: 12px; color: var(--faint); line-height: 1.55; }

@media (max-width: 640px) {
  .plan-tools { padding: 2px 12px; }
  .pt-row { flex-direction: column; }
  .pt-row :deep(.el-button) { width: 100%; }
  .pt-hint { margin-left: 0; width: 100%; }
  .pt-planb .pt-head :deep(.el-segmented) { margin-left: 0; }
}

@media print {
  .plan-tools { display: none !important; }
}
</style>
