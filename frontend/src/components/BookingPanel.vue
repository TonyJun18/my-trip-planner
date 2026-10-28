<template>
  <div class="booking-panel">
    <div class="booking-header">
      <span class="booking-title">{{ t('booking.panelTitle') }}</span>
      <el-tooltip :content="t('booking.hint')" placement="top">
        <el-icon class="booking-hint-icon"><QuestionFilled /></el-icon>
      </el-tooltip>
    </div>

    <!-- 加载/空态 -->
    <el-empty
      v-if="!loading && items.length === 0"
      :description="t('booking.empty')"
      :image-size="60"
    />

    <div v-else class="booking-items">
      <div v-for="b in items" :key="b.id" class="booking-item" :class="`status-${b.status}`">
        <div class="booking-item-main">
          <div class="booking-item-top">
            <el-tag size="small" :type="kindTag(b.kind)">{{ kindLabel(b.kind) }}</el-tag>
            <el-tag size="small" effect="plain" class="provider-tag">{{ providerLabel(b.provider) }}</el-tag>
            <span class="booking-status">{{ statusLabel(b.status) }}</span>
          </div>
          <div class="booking-item-title">{{ b.title || '—' }}</div>
          <div v-if="b.amount" class="booking-item-price">
            {{ t('booking.amountText', { amount: b.amount, currency: b.currency }) }}
          </div>
          <div v-if="b.order_no" class="booking-item-order">
            {{ t('booking.orderNo') }}: {{ b.order_no }}
          </div>
        </div>

        <div class="booking-item-actions">
          <!-- suggested/pending: 可跳转预订 -->
          <el-button
            v-if="b.status === 'suggested' || b.status === 'pending'"
            size="small"
            type="primary"
            :disabled="!b.provider_url"
            @click="openBooking(b)"
          >
            {{ t('booking.bookNow') }}
          </el-button>
          <!-- 回填凭证（偶发手动） -->
          <el-button v-if="b.status === 'suggested'" size="small" plain @click="openConfirm(b)">
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
    </div>

    <!-- 回填凭证对话框 -->
    <el-dialog v-model="confirmVisible" :title="t('booking.confirmTitle')" width="420px">
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
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import { addBooking, listBookings, updateBookingStatus } from '../api'

const props = defineProps({
  tripId: { type: String, required: true },
})
const emit = defineEmits(['changed'])

const { t } = useI18n()
const items = ref([])
const loading = ref(false)
const confirming = ref(false)
const confirmVisible = ref(false)
const current = ref(null)
const confirmForm = reactive({ order_no: '', credential: '', amount: null })

function kindLabel(kind) {
  return kind === 'train' ? t('booking.kind.train') : t('booking.kind.hotel')
}
function kindTag(kind) {
  return kind === 'train' ? 'primary' : 'warning'
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

async function load() {
  loading.value = true
  try {
    const data = await listBookings(props.tripId)
    items.value = data.items || []
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
  confirmForm.order_no = ''
  confirmForm.credential = ''
  confirmForm.amount = null
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
    await updateBookingStatus(props.tripId, current.value.id, {
      status: 'confirmed',
      order_no: confirmForm.order_no,
      credential: confirmForm.credential,
    })
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
.booking-item-title {
  font-weight: 500;
  margin: 4px 0;
  line-height: 1.4;
}
.booking-item-price {
  font-size: 13px;
  color: var(--el-color-warning);
}
.booking-item-order {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.booking-item-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}
</style>