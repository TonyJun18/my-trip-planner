<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { CircleCheck, DataAnalysis, Download, WarningFilled, Document } from '@element-plus/icons-vue'
import { getQualityReport, getSharedQualityReport } from '@/api'
import { exportPdf, exportImage } from '@/utils/export'

/**
 * 质检报告面板（task-trip-quality-report-a/b）。
 *
 * 五类质检只读聚合：quality（AI Critic 评审）/ time_gate（时间校验）/
 * repeat_gate（重复站点，独立露出）/ weather_gate（天气感知）/
 * dynamic_facts（日期特例）。gate 未检查（checked=false）→ 显示「未检查」，
 * 绝不假装通过。支持导出 PDF / 长图（shareToken 模式免登录）。
 *
 * 刻意放在 exportEl 之外由父组件决定；本组件自带的导出pdf/图片用
 * exportEl 之外的自身 DOM（reportBody），不影响行程整体导出。
 */
const props = defineProps({
  tripId: { type: String, required: true },
  // 分享令牌模式（免登录只读）；为空 = owner 模式
  shareToken: { type: String, default: '' },
})

const { t } = useI18n()
const loading = ref(false)
const report = ref(null)
const bodyEl = ref(null)
const exporting = ref('')

const gates = computed(() => report.value?.gates || [])
const totalIssues = computed(() => report.value?.total_issues || 0)
const checkedGates = computed(() => report.value?.checked_gates || 0)
const passedGates = computed(() => report.value?.passed_gates || 0)
const hasReport = computed(() => report.value != null)

// gate 的标题 / 状态徽标（i18n 键 + 颜色）
const gateMeta = (g) => {
  const title = t(`qualityReport.gate.${g.key}`)
  let badge = ''
  let type = 'info'
  if (!g.checked) {
    badge = t('qualityReport.unchecked')
    type = 'info'
  } else if (g.issues?.length) {
    badge = t('qualityReport.issuesBadge', { n: g.warning_count })
    type = 'warning'
  } else {
    badge = t('qualityReport.passedBadge')
    type = 'success'
  }
  return { title, badge, type }
}

const sevLabel = { critical: () => t('quality.sevCritical'), warning: () => t('quality.sevWarning'), info: () => t('quality.sevInfo') }
const sevColor = { critical: '#dc2626', warning: '#d97706', info: 'var(--faint)' }

async function load() {
  loading.value = true
  try {
    const fn = props.shareToken ? getSharedQualityReport : getQualityReport
    const arg = props.shareToken || props.tripId
    report.value = await fn(arg)
  } catch (e) {
    // 静默降级：面板不可用不阻断页面（与 property-qa 口径一致）
    report.value = null
  } finally {
    loading.value = false
  }
}

// 导出 PDF / 长图（b：报告导出）——只抓报告本体，不携带凭证
async function doExport(kind) {
  if (exporting.value) return
  exporting.value = kind
  try {
    const el = bodyEl.value
    if (!el) return
    const name = `${t('qualityReport.exportName')}-${new Date().toISOString().slice(0, 10)}`
    if (kind === 'pdf') await exportPdf(el, name)
    else await exportImage(el, name)
    ElMessage.success(kind === 'pdf' ? t('tripDetail.pdfExported') : t('tripDetail.imageExported'))
  } catch (e) {
    ElMessage.error(t('tripDetail.exportFail', { msg: e?.message || '' }))
  } finally {
    exporting.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="quality-report-panel">
    <!-- 头部：标题 + 统计 + 导出 -->
    <div class="qr-head">
      <span class="qr-title"><el-icon style="margin-right: 6px"><DataAnalysis /></el-icon>{{ t('qualityReport.title') }}</span>
      <span v-if="totalIssues" class="qr-issues-total">
        <el-icon style="margin-right: 3px"><WarningFilled /></el-icon>{{ t('qualityReport.issuesTotal', { n: totalIssues }) }}
      </span>
      <span v-else class="qr-clean"><el-icon style="margin-right: 3px"><CircleCheck /></el-icon>{{ t('qualityReport.clean') }}</span>
      <span class="qr-meta">{{ t('qualityReport.checkedMeta', { checked: checkedGates, passed: passedGates, total: gates.length }) }}</span>
      <div class="qr-actions">
        <el-button size="small" plain :loading="exporting === 'pdf'" @click="doExport('pdf')">
          <el-icon style="margin-right: 4px"><Document /></el-icon>{{ t('qualityReport.exportPdf') }}
        </el-button>
        <el-button size="small" plain :loading="exporting === 'image'" @click="doExport('image')">
          <el-icon style="margin-right: 4px"><Download /></el-icon>{{ t('qualityReport.exportImage') }}
        </el-button>
      </div>
    </div>

    <!-- 空态（加载完成但无报告 / 降级） -->
    <el-empty
      v-if="!loading && !hasReport"
      :description="t('qualityReport.unavailable')"
      :image-size="50"
    />

    <!-- 报告体（导出抓取范围） -->
    <div v-else ref="bodyEl" class="qr-body">
      <div class="qr-gates">
        <div v-for="g in gates" :key="g.key" class="qr-gate" :class="{ unchecked: !g.checked }">
          <div class="qr-gate-head">
            <span class="qr-gate-title">{{ gateMeta(g).title }}</span>
            <el-tag size="small" :type="gateMeta(g).type" effect="plain">{{ gateMeta(g).badge }}</el-tag>
            <span v-if="g.basis" class="qr-gate-basis">{{ g.basis }}</span>
            <span v-if="g.score != null" class="qr-gate-score" :class="{ pass: g.score >= 80 }">{{ g.score }}/100</span>
          </div>

          <!-- 未检查：诚实标注，不假装通过 -->
          <div v-if="!g.checked" class="qr-gate-empty">
            {{ t('qualityReport.notCheckedHint') }}
          </div>

          <!-- 通过：绿色提示 -->
          <div v-else-if="!g.issues?.length" class="qr-gate-clean">
            <el-icon style="margin-right: 4px; color: var(--success)"><CircleCheck /></el-icon>
            {{ t('qualityReport.gateClean') }}
          </div>

          <!-- 问题列表 -->
          <ul v-else class="qr-issues">
            <li v-for="(iss, i) in g.issues" :key="i" class="qr-issue">
              <span class="qr-sev" :style="{ background: sevColor[iss.severity] || 'var(--faint)' }">
                {{ (sevLabel[iss.severity] || (() => iss.severity))() }}
              </span>
              <span v-if="iss.day_number" class="qr-day">Day {{ iss.day_number }}</span>
              <span class="qr-msg">{{ iss.message }}</span>
              <span v-if="iss.suggestion" class="qr-suggestion">→ {{ iss.suggestion }}</span>
            </li>
          </ul>
        </div>
      </div>
      <p class="qr-foot">{{ t('qualityReport.footNote') }}</p>
    </div>
  </div>
</template>

<style scoped>
.quality-report-panel {
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, #f7fbff, #fff 60%);
  padding: 16px 20px;
}
.qr-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.qr-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  display: inline-flex;
  align-items: center;
}
.qr-title .el-icon { color: var(--brand); }
.qr-issues-total {
  font-size: 12.5px;
  color: var(--warning);
  background: rgba(217,119,6,.1);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  display: inline-flex;
  align-items: center;
}
.qr-clean {
  font-size: 12.5px;
  color: var(--success);
  display: inline-flex;
  align-items: center;
}
.qr-meta {
  font-size: 12px;
  color: var(--muted);
}
.qr-actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
}
.qr-body { margin-top: 4px; }
.qr-gates {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.qr-gate {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  background: #fff;
}
.qr-gate.unchecked {
  opacity: 0.65;
  background: var(--el-fill-color-lighter);
}
.qr-gate-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.qr-gate-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}
.qr-gate-basis {
  font-size: 11px;
  color: var(--faint);
  font-family: monospace;
}
.qr-gate-score {
  font-size: 12px;
  font-weight: 700;
  color: var(--warning);
}
.qr-gate-score.pass { color: var(--success); }
.qr-gate-empty {
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
}
.qr-gate-clean {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--success);
  display: inline-flex;
  align-items: center;
}
.qr-issues {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.qr-issue {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--ink-2);
  line-height: 1.5;
}
.qr-sev {
  color: #fff;
  font-size: 10.5px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}
.qr-day {
  font-size: 11px;
  color: var(--brand);
  background: var(--brand-soft);
  padding: 0 6px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}
.qr-msg { flex: 1; min-width: 120px; }
.qr-suggestion { width: 100%; font-size: 11.5px; color: var(--muted); padding-left: 3px; }
.qr-foot {
  margin: 12px 0 0;
  font-size: 11px;
  color: var(--faint);
}
</style>