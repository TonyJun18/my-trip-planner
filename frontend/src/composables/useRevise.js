import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import * as api from '@/api'

/**
 * AI 对话式修订行程（方案 B：revise）。
 *
 * 输入框 / 修订状态 / 结果（summary + diff 预览 + quality 质控报告）
 * 全部收敛在此，详情页模板只需绑定返回的 refs 与 revise()。
 */
export function useRevise({ afterRevise } = {}) {
  const route = useRoute()
  const { t, locale } = useI18n()

  const reviseMsg = ref('')
  const revising = ref(false)
  const lastReviseSummary = ref('')
  const lastReviseDiff = ref([])
  const reviseError = ref('')
  const reviseDone = ref(false)
  const lastReviseQuality = ref(null)

  // diff 预览折叠：超过 8 条默认收起，避免卡片过高
  const REVISE_DIFF_PREVIEW_MAX = 8
  const visibleReviseDiff = computed(() => lastReviseDiff.value.slice(0, REVISE_DIFF_PREVIEW_MAX))
  const reviseDiffMore = computed(() => Math.max(0, lastReviseDiff.value.length - REVISE_DIFF_PREVIEW_MAX))

  const diffOpKeys = {
    replace: 'diffReplace',
    add: 'diffAdd',
    remove: 'diffRemove',
    reorder: 'diffReorder',
  }
  const fieldLabelKeys = {
    name: 'fieldName',
    description: 'fieldDesc',
    stop_type: 'fieldType',
    estimated_cost: 'fieldCost',
    estimated_duration_minutes: 'fieldDuration',
    note: 'fieldNote',
    date: 'fieldDate',
    lat: 'fieldLat',
    lng: 'fieldLng',
  }
  function fieldLabel(k) {
    const key = fieldLabelKeys[k]
    return key ? t(`tripDetail.${key}`) : k
  }
  function diffText(a) {
    const day = a.day_number ? `Day${a.day_number} · ` : ''
    const target = a.target_name || ''
    if (a.op === 'reorder') {
      return t('tripDetail.diffReorderText', { day, n: a.index ?? '?' })
    }
    const fieldKeys = Object.keys(a.fields || {})
    const fieldText = fieldKeys.length ? `（${fieldKeys.map(fieldLabel).join('、')}）` : ''
    const opLabel = diffOpKeys[a.op] ? t(`tripDetail.${diffOpKeys[a.op]}`) : a.op
    return t('tripDetail.diffActionText', { day, op: opLabel, target, fields: fieldText })
  }

  async function revise() {
    const msg = reviseMsg.value.trim()
    if (!msg) {
      ElMessage.warning(t('tripDetail.reviseWarning'))
      return
    }
    if (revising.value) return
    revising.value = true
    reviseError.value = ''
    reviseDone.value = false
    lastReviseSummary.value = ''
    lastReviseDiff.value = []
    lastReviseQuality.value = null
    try {
      const r = await api.reviseTrip(route.params.id, { message: msg, provider: 'auto', language: String(locale.value || '').replace('_', '-') })
      lastReviseSummary.value = r.summary || ''
      lastReviseDiff.value = Array.isArray(r.diff) ? r.diff : []
      lastReviseQuality.value = r.quality || null
      reviseDone.value = true
      ElMessage.success(r.summary || t('tripDetail.revised'))
      reviseMsg.value = ''
      afterRevise?.()
    } catch (e) {
      lastReviseSummary.value = ''
      lastReviseDiff.value = []
      lastReviseQuality.value = null
      reviseError.value = e?.response?.data?.detail || e?.response?.data?.error?.message || t('tripDetail.reviseFailHint')
    } finally {
      revising.value = false
    }
  }

  return {
    reviseMsg, revising, lastReviseSummary, lastReviseDiff, reviseError, reviseDone, lastReviseQuality,
    visibleReviseDiff, reviseDiffMore, diffText, revise,
  }
}