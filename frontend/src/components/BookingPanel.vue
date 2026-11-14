<template>
  <div class="booking-panel">
    <div class="booking-header">
      <span class="booking-title">{{ t('booking.panelTitle') }}</span>
      <el-tooltip :content="t('booking.hint')" placement="top">
        <el-icon class="booking-hint-icon"><QuestionFilled /></el-icon>
      </el-tooltip>
    </div>

    <!-- 预订节奏（task-booking-ledger-rhythm：确定性规则库，派生读路径） -->
    <div v-if="rhythm.length" class="rhythm-card">
      <div class="rhythm-title">{{ t('booking.rhythmTitle') }}</div>
      <div v-for="(r, i) in rhythm" :key="i" class="rhythm-item">
        <el-tag size="small" :type="phaseTag(r.phase)">{{ phaseLabel(r.phase) }}</el-tag>
        <span class="rhythm-target">{{ r.target }}</span>
        <span class="rhythm-window">{{ r.window_open }} → {{ r.window_deadline }}</span>
        <el-tooltip :content="r.note" placement="top">
          <el-icon class="rhythm-info"><InfoFilled /></el-icon>
        </el-tooltip>
      </div>
      <p class="rhythm-basis">{{ t('booking.rhythmBasisNote', { basis: 'rule_based' }) }}</p>
    </div>

    <!-- 加载/空态 -->
    <el-empty
      v-if="!loading && items.length === 0"
      :description="t('booking.empty')"
      :image-size="60"
    />

    <div v-else class="booking-items">
      <template v-for="group in groups" :key="group.key">
        <div class="booking-group-title">{{ group.label }}（{{ group.items.length }}）</div>
        <div
          v-for="b in group.items"
          :key="b.id"
          class="booking-item"
          :class="`status-${b.status}`"
        >
          <div class="booking-item-main">
            <div class="booking-item-top">
              <el-tag size="small" :type="kindTag(b.kind)">{{ kindLabel(b.kind) }}</el-tag>
              <el-tag size="small" effect="plain" class="provider-tag">{{ providerLabel(b.provider) }}</el-tag>
              <span v-if="daysText(b)" class="booking-countdown" :class="{ overdue: b.days_until < 0 }">
                {{ daysText(b) }}
              </span>
              <span class="booking-status">{{ statusLabel(b.status) }}</span>
            </div>
            <div class="booking-item-title">{{ b.title || '—' }}</div>
            <div v-if="b.service_date" class="booking-item-service">
              {{ t('booking.serviceDate') }}: {{ b.service_date }}
              <span v-if="b.service_note" class="booking-service-note">· {{ b.service_note }}</span>
            </div>
            <div v-if="b.amount" class="booking-item-price">
              {{ t('booking.amountText', { amount: b.amount, currency: b.currency }) }}
            </div>
            <div v-if="b.order_no" class="booking-item-order">
              {{ t('booking.orderNo') }}: {{ b.order_no }}
            </div>
            <div v-if="b.status === 'pending' && !b.credential" class="booking-pending-hint">
              {{ t('booking.pendingHint') }}
            </div>
          </div>

          <div class="booking-item-actions">
            <!-- suggested/pending: 可跳转预订 -->
            <el-button
              v-if="(b.status === 'suggested' || b.status === 'pending') && b.provider_url"
              size="small"
              type="primary"
              @click="openBooking(b)"
            >
              {{ t('booking.bookNow') }}
            </el-button>
            <!-- 回填凭证（suggested 手动补录 / pending 邮件归并后确认） -->
            <el-button
              v-if="b.status === 'suggested' || (b.status === 'pending' && !b.credential)"
              size="small"
              plain
              @click="openConfirm(b)"
            >
              {{ t('booking.fillBack') }}
            </el-button>
            <!-- confirmed: 可取消 -->
            <el-button
              v-if="b.status === 'confirmed'"
              size="small"
              type="danger"
              plain
              @click="cancelBooking(b)"
            >
              {{ t('booking.cancel') }}
            </el-button>
          </div>
        </div>
      </template>
    </div>

    <!-- 回填凭证对话框（task-booking-ledger-minors：可顺带登记金额与服务日期） -->
    <el-dialog v-model="confirmVisible" :title="t('booking.confirmTitle')" width="440px">
      <el-form label-position="top">
        <el-form-item :label="t('booking.orderNo')">
          <el-input v-model="confirmForm.order_no" :placeholder="t('booking.orderNoPh')" />
        </el-form-item>
        <el-form-item :label="t('booking.credential')">
          <el-input v-model="confirmForm.credential" :placeholder="t('booking.credentialPh')" />
        </el-form-item>
        <el-form-item :label="t('booking.amount')">
          <el-input-number v-model="confirmForm.amount" :min="0" :precision="2" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('booking.serviceDate')">
          <el-date-picker
            v-model="confirmForm.service_date"
            type="date"
            value-format="YYYY-MM-DD"
            clearable
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item :label="t('booking.serviceNote')">
          <el-input v-model="confirmForm.service_note" maxlength="500" :placeholder="t('booking.serviceNotePh')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="confirmVisible = false">{{ t('booking.cancelText') }}</el-button>
        <el-button type="primary" :loading="confirming" @click="submitConfirm">
          {{ t('booking.confirmSubmit') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled, QuestionFilled } from '@element-plus/icons-vue'
import { getBookingRhythm, listBookings, updateBookingStatus } from '../api'

const props = defineProps({
  tripId: { type: String, required: true },
})
const emit = defineEmits(['changed'])

const { t } = useI18n()
const items = ref([])
const rhythm = ref([])
const loading = ref(false)
const confirming = ref(false)
const confirmVisible = ref(false)
const current = ref(null)
const confirmForm = reactive({ order_no: '', credential: '', amount: null, service_date: '', service_note: '' })

// 台账分组：待办（suggested+pending）→ 已确认 → 已取消（组内保持后端 service_date 排序）
const groups = computed(() => {
  const todo = items.value.filter((b) => b.status === 'suggested' || b.status === 'pending')
  const confirmed = items.value.filter((b) => b.status === 'confirmed')
  const cancelled = items.value.filter((b) => b.status === 'cancelled')
  return [
    { key: 'todo', label: t('booking.groupTodo'), items: todo },
    { key: 'confirmed', label: t('booking.groupConfirmed'), items: confirmed },
    { key: 'cancelled', label: t('booking.groupCancelled'), items: cancelled },
  ].filter((g) => g.items.length > 0)
})

function kindLabel(kind) {
  return t(`booking.kind.${kind}`)
}
function kindTag(kind) {
  return { train: 'primary', flight: 'primary', hotel: 'warning', ticket: 'success' }[kind] || 'info'
}
function providerLabel(p) {
  const map = {
    ctrip: '携程', qunar: '去哪儿', '12306': '12306',
    feizhu: '飞猪', tongcheng: '同程', manual: t('booking.provider.manual'),
  }
  return map[p] || p
}
function statusLabel(s) {
  const map = {
    suggested: t('booking.status.suggested'),
    pending: t('booking.status.pending'),
    confirmed: t('booking.status.confirmed'),
    cancelled: t('booking.status.cancelled'),
  }
  return map[s] || s
}
// 倒计时：未来 N 天后 / 今天 / 已过 N 天前（无服务日期不显示）
function daysText(b) {
  const d = b.days_until
  if (d === null || d === undefined) return ''
  if (d > 0) return t('booking.daysUntil', { n: d })
  if (d === 0) return t('booking.daysToday')
  return t('booking.daysAgo', { n: -d })
}
function phaseLabel(p) {
  return { open: t('booking.phaseOpen'), upcoming: t('booking.phaseUpcoming'), closing: t('booking.phaseClosing') }[p] || p
}
function phaseTag(p) {
  return { open: 'success', upcoming: 'info', closing: 'warning' }[p] || 'info'
}

async function load() {
  loading.value = true
  try {
    // 节奏失败不阻断台账展示（派生读路径，可缺失）
    const [data, rhythmData] = await Promise.all([
      listBookings(props.tripId),
      getBookingRhythm(props.tripId).catch(() => ({ items: [] })),
    ])
    items.value = data.items || []
    rhythm.value = rhythmData.items || []
  } catch (e) {
    ElMessage.warning(t('booking.loadFailed'))
  } finally {
    loading.value = false
  }
}

function openBooking(b) {
  if (!b.provider_url) return
  // 跳转 OTA 搜索页，用户自助完成交易；回来点"回填凭证"
  window.open(b.provider_url, '_blank', 'noopener')
  // 跳转后把可见项提示回填（不自动改状态——绝不伪造成已订）
  ElMessage.info(t('booking.afterJump'))
}

function openConfirm(b) {
  current.value = b
  confirmForm.order_no = b.order_no || ''
  confirmForm.credential = ''
  confirmForm.amount = b.amount ?? null
  confirmForm.service_date = b.service_date || ''
  confirmForm.service_note = b.service_note || ''
  confirmVisible.value = true
}

async function submitConfirm() {
  if (!current.value) return
  if (!confirmForm.order_no && !confirmForm.credential) {
    ElMessage.warning(t('booking.confirmRequireOrder'))
    return
  }
  confirming.value = true
  try {
    const payload = {
      status: 'confirmed',
      order_no: confirmForm.order_no,
      credential: confirmForm.credential,
    }
    // 金额/服务日期/备注：仅显式提供才提交（null / 空串清空——后端用 model_fields_set 区分）
    if (confirmForm.amount !== null && confirmForm.amount !== undefined) payload.amount = confirmForm.amount
    if (confirmForm.service_date !== '') payload.service_date = confirmForm.service_date || null
    if (confirmForm.service_note !== undefined) payload.service_note = confirmForm.service_note || null
    await updateBookingStatus(props.tripId, current.value.id, payload)
    ElMessage.success(t('booking.confirmed'))
    confirmVisible.value = false
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(t('booking.confirmFailed'))
  } finally {
    confirming.value = false
  }
}

async function cancelBooking(b) {
  try {
    await ElMessageBox.confirm(t('booking.cancelConfirm'), t('booking.cancel'), {
      confirmButtonText: t('booking.cancelOk'),
      cancelButtonText: t('booking.cancelText'),
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await updateBookingStatus(props.tripId, b.id, { status: 'cancelled' })
    ElMessage.success(t('booking.cancelled'))
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(t('booking.cancelFailed'))
  }
}

onMounted(load)
</script>

<style scoped>
.booking-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px;
}
.booking-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}
.booking-title {
  font-weight: 600;
  font-size: 15px;
}
.booking-hint-icon {
  color: var(--el-text-color-secondary);
  cursor: help;
}
/* 节奏卡（行前准备：什么时候该订什么） */
.rhythm-card {
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: var(--el-fill-color-lighter);
}
.rhythm-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.rhythm-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  padding: 3px 0;
}
.rhythm-target {
  font-weight: 500;
}
.rhythm-window {
  color: var(--el-text-color-secondary);
  font-family: monospace;
}
.rhythm-info {
  color: var(--el-text-color-secondary);
  cursor: help;
}
.rhythm-basis {
  margin: 6px 0 0;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.booking-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin: 8px 0 6px;
}
.booking-items {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.booking-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  transition: border-color 0.2s;
}
.booking-item.status-confirmed {
  border-color: var(--el-color-success);
  background: var(--el-color-success-light-9);
}
.booking-item.status-cancelled {
  opacity: 0.6;
}
.booking-item-top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.booking-status {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: auto;
}
.booking-countdown {
  font-size: 12px;
  color: var(--el-color-warning);
  font-weight: 600;
}
.booking-countdown.overdue {
  color: var(--el-text-color-secondary);
}
.booking-item-title {
  font-weight: 500;
  margin: 4px 0;
  line-height: 1.4;
}
.booking-item-service {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.booking-service-note {
  margin-left: 2px;
}
.booking-item-price {
  font-size: 13px;
  color: var(--el-color-warning);
}
.booking-item-order {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.booking-pending-hint {
  font-size: 12px;
  color: var(--el-color-warning);
  margin-top: 2px;
}
.booking-item-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}
</style>
