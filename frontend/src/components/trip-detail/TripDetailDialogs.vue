<script setup>
import { computed, ref, watch } from 'vue'
import XhsNoteDialog from '@/components/XhsNoteDialog.vue'
import ImportDialog from '@/components/ImportDialog.vue'

// 对话框编排容器：小红书 / 内容导入 / 批量生成日程 / 分享设置 / 编辑三合一。
// 全部状态仍由 orchestrator 持有（useTripShareActions / useEditDialog / genDays 局部），
// 本组件只做渲染绑定与事件上抛 —— 契约 = 原模板绑定原样搬移。
const props = defineProps({
  trip: { type: Object, default: null },
  // 导入 / 小红书可见性（orchestrator 透传）
  xhsNoteVisible: { type: Boolean, default: false },
  importVisible: { type: Boolean, default: false },
  // 编辑三合一同构状态
  editType: { type: String, default: '' },
  dialogVisible: { type: Boolean, default: false },
  stopFormRef: { type: Object, default: null },
  stopForm: { type: Object, default: () => ({}) },
  dayForm: { type: Object, default: () => ({}) },
  tripForm: { type: Object, default: () => ({}) },
  tripTypeOptions: { type: Array, default: () => [] },
  tripTypeDisplay: { type: Function, default: () => (v) => v },
  // 批量生成日程
  genDaysVisible: { type: Boolean, default: false },
  genRange: { type: Array, default: () => [] },
  genDaysLoading: { type: Boolean, default: false },
  // 分享设置
  shareSettingsVisible: { type: Boolean, default: false },
  lifecycleItems: { type: Array, default: () => [] },
  lifecycleLoading: { type: Boolean, default: false },
  revokingKind: { type: String, default: '' },
  ttlOptions: { type: Array, default: () => [] },
  windowOrigin: { type: String, default: '' },
  lifecycleStatus: { type: Function, default: () => () => 'active' },
})

const emit = defineEmits([
  // 编辑三合一
  'update:dialog-visible', 'update:stop-form', 'update:day-form', 'update:trip-form', 'update:stop-form-ref',
  'save-trip', 'save-day', 'save-stop', 'save-edit-stop',
  // 批量生成
  'update:gen-days-visible', 'update:gen-range', 'gen-days',
  // 分享设置
  'update:share-settings-visible', 'load-share-lifecycle', 'copy-share-url', 'set-ttl', 'revoke-share-link',
  // 导入
  'imported', 'update:import-visible',
  'update:xhs-visible',
])

// 分享设置生命周期状态机
const lifecycleState = computed(() => (item) => props.lifecycleStatus(item))

// 表单本地副本：props → 本地（打开时同步），本地 → emit（每次变更同步回 orchestrator）
// 这样 el-input v-model 绑定本地 ref 即可，避免嵌套 computed 不可写问题。
const tripFormLocal = ref({ ...props.tripForm })
const dayFormLocal = ref({ ...props.dayForm })
const stopFormLocal = ref({ ...props.stopForm })
watch(
  () => props.tripForm,
  (v) => { tripFormLocal.value = { ...(v || {}) } },
  { deep: true },
)
watch(
  () => props.dayForm,
  (v) => { dayFormLocal.value = { ...(v || {}) } },
  { deep: true },
)
watch(
  () => props.stopForm,
  (v) => { stopFormLocal.value = { ...(v || {}) } },
  { deep: true },
)
function onTripFormChange() { emit('update:trip-form', { ...tripFormLocal.value }) }
function onDayFormChange() { emit('update:day-form', { ...dayFormLocal.value }) }
function onStopFormChange() { emit('update:stop-form', { ...stopFormLocal.value }) }

// 表单 ref：本地 el-form 元素，绑定后实时上抛给 orchestrator（useEditDialog 用它 validate）
const localStopFormEl = ref(null)
watch(localStopFormEl, (el) => {
  emit('update:stop-form-ref', el)
})
</script>

<template>
  <!-- 小红书笔记（生成文案/封面 → 复制 → App 发布） -->
  <XhsNoteDialog :model-value="xhsNoteVisible" @update:model-value="(v) => emit('update:xhs-visible', v)" :trip-id="trip?.id" :trip="trip" />

  <!-- 内容导入（笔记/截图/链接/邮件 → 候选并入当前行程） -->
  <ImportDialog :model-value="importVisible" @update:model-value="(v) => emit('update:import-visible', v)" :preset-trip-id="trip?.id" @imported="emit('imported')" />

  <!-- 批量生成日程对话框 -->
  <el-dialog
    :model-value="genDaysVisible"
    :title="$t('tripDetail.genDaysTitle')"
    width="440px"
    @update:model-value="(v) => emit('update:gen-days-visible', v)"
  >
    <el-form label-width="80px">
      <el-form-item :label="$t('tripDetail.genRange')">
        <el-date-picker
          :model-value="genRange"
          type="daterange"
          :range-separator="$t('tripDetail.genRangeSep')"
          :start-placeholder="$t('tripDetail.genStartPh')"
          :end-placeholder="$t('tripDetail.genEndPh')"
          value-format="YYYY-MM-DD"
          style="width: 100%"
          @update:model-value="(v) => emit('update:gen-range', v)"
        />
      </el-form-item>
      <div class="gen-days-hint">{{ $t('tripDetail.genDaysHint') }}</div>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:gen-days-visible', false)">{{ $t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="genDaysLoading" @click="emit('gen-days')">{{ $t('tripDetail.genBtn') }}</el-button>
    </template>
  </el-dialog>

  <!-- 分享设置（生命周期：TTL / 吊销 / 审计） -->
  <el-dialog
    :model-value="shareSettingsVisible"
    :title="$t('tripDetail.shareSettingsTitle')"
    width="680px"
    @update:model-value="(v) => emit('update:share-settings-visible', v)"
    @open="emit('load-share-lifecycle')"
  >
    <div class="share-settings-hint">{{ $t('tripDetail.shareSettingsHint') }}</div>
    <div v-loading="lifecycleLoading" class="share-settings-body">
      <div v-if="!lifecycleLoading && !lifecycleItems.length" class="share-settings-empty">
        {{ $t('tripDetail.shareLinkFetchFail') }}
      </div>
      <div v-for="item in lifecycleItems" :key="item.kind" class="share-setting-card" :class="lifecycleState(item)">
        <div class="ss-head">
          <span class="ss-kind">{{ item.kind === 'edit' ? $t('tripDetail.shareKindEdit') : $t('tripDetail.shareKindShare') }}</span>
          <el-tag size="small" round :type="lifecycleState(item) === 'revoked' ? 'danger' : lifecycleState(item) === 'expired' ? 'warning' : 'success'">
            {{ lifecycleState(item) === 'revoked' ? $t('tripDetail.shareStatusRevoked') : lifecycleState(item) === 'expired' ? $t('tripDetail.shareStatusExpired') : $t('tripDetail.shareStatusActive') }}
          </el-tag>
        </div>

        <div class="ss-row">
          <span class="ss-label">{{ $t('tripDetail.shareUrl') }}</span>
          <span class="ss-value ss-url">
            <template v-if="item.kind === 'edit'">{{ windowOrigin }}/share/{{ item.token }}?edit=1</template>
            <template v-else>{{ item.share_url }}</template>
          </span>
          <el-button link type="primary" size="small" @click="emit('copy-share-url', item)">{{ $t('tripDetail.copyLink') }}</el-button>
        </div>

        <div class="ss-row">
          <span class="ss-label">{{ $t('tripDetail.shareExpires') }}</span>
          <span class="ss-value">{{ item.expires_at ? new Date(item.expires_at).toLocaleString() : $t('tripDetail.shareNever') }}</span>
          <el-select
            :model-value="0"
            size="small"
            style="width: 120px"
            :disabled="lifecycleState(item) !== 'active'"
            @change="(v) => emit('set-ttl', item.kind, v)"
          >
            <el-option v-for="opt in ttlOptions" :key="opt.value" :value="opt.value" :label="opt.label" />
          </el-select>
        </div>

        <div class="ss-row">
          <span class="ss-label">{{ $t('tripDetail.shareLastUsed') }}</span>
          <span class="ss-value">{{ item.last_used_at ? new Date(item.last_used_at).toLocaleString() : $t('tripDetail.shareNeverUsed') }}</span>
        </div>

        <div class="ss-actions" v-if="lifecycleState(item) === 'active'">
          <el-button type="danger" plain size="small" :loading="revokingKind === item.kind" @click="emit('revoke-share-link', item)">
            {{ $t('tripDetail.shareStatusRevoked') }}
          </el-button>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('update:share-settings-visible', false)">{{ $t('common.cancel') }}</el-button>
    </template>
  </el-dialog>

  <!-- 编辑对话框（三合一：行程 / 日程 / 站点） -->
  <el-dialog
    :model-value="dialogVisible"
    :title="editType === 'edit-trip' ? $t('tripDetail.editTripTitle') : editType === 'add-day' ? $t('tripDetail.addDayTitle') : editType === 'edit-stop' ? $t('tripDetail.editStopTitle') : $t('tripDetail.addStopTitle')"
    width="480px"
    @update:model-value="(v) => emit('update:dialog-visible', v)"
  >
    <el-form v-if="editType === 'edit-trip'" :model="tripFormLocal" label-width="80px">
      <el-form-item :label="$t('tripDetail.lblTitle')"><el-input v-model="tripFormLocal.title" @input="onTripFormChange" /></el-form-item>
      <el-form-item :label="$t('tripDetail.lblDestination')"><el-input v-model="tripFormLocal.destination" @input="onTripFormChange" /></el-form-item>
      <el-form-item :label="$t('tripDetail.lblDeparture')">
        <el-input v-model="tripFormLocal.departure" :placeholder="$t('tripDetail.departurePlaceholder')" @input="onTripFormChange" />
      </el-form-item>
      <el-form-item :label="$t('tripDetail.lblTripType')">
        <el-select v-model="tripFormLocal.trip_type" style="width: 100%" @change="onTripFormChange">
          <el-option v-for="opt in tripTypeOptions" :key="opt.key" :label="tripTypeDisplay(opt.value)" :value="opt.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="$t('tripDetail.lblTravelers')"><el-input-number v-model="tripFormLocal.travelers" :min="1" @change="onTripFormChange" /></el-form-item>
      <el-form-item :label="$t('tripDetail.lblBudget')"><el-input-number v-model="tripFormLocal.budget" :min="0" :step="500" @change="onTripFormChange" /></el-form-item>
    </el-form>

    <el-form v-else-if="editType === 'add-day'" :model="dayFormLocal" label-width="80px">
      <el-form-item :label="$t('tripDetail.lblDayNumber')"><el-input-number v-model="dayFormLocal.day_number" :min="1" @change="onDayFormChange" /></el-form-item>
      <el-form-item :label="$t('tripDetail.lblDate')"><el-date-picker v-model="dayFormLocal.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" @change="onDayFormChange" /></el-form-item>
      <el-form-item :label="$t('tripDetail.lblNote')"><el-input v-model="dayFormLocal.note" type="textarea" :rows="2" @input="onDayFormChange" /></el-form-item>
    </el-form>

    <el-form v-else ref="localStopFormEl" :model="stopFormLocal" label-width="90px">
      <el-form-item :label="$t('tripDetail.lblName')" prop="name" :rules="[{ required: true, message: $t('tripDetail.stopNameRequired') }]">
        <el-input v-model="stopFormLocal.name" :placeholder="$t('tripDetail.stopNamePh')" @input="onStopFormChange" />
      </el-form-item>
      <el-form-item :label="$t('tripDetail.lblType')">
        <el-radio-group v-model="stopFormLocal.stop_type" @change="onStopFormChange">
          <el-radio-button value="attraction">{{ $t('common.typeAttraction') }}</el-radio-button>
          <el-radio-button value="food">{{ $t('common.typeFood') }}</el-radio-button>
          <el-radio-button value="hotel">{{ $t('common.typeHotel') }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item :label="$t('tripDetail.lblLatLng')">
        <div class="latlng">
          <el-input v-model="stopFormLocal.lat" :placeholder="$t('tripDetail.latPh')" @input="onStopFormChange" />
          <el-input v-model="stopFormLocal.lng" :placeholder="$t('tripDetail.lngPh')" @input="onStopFormChange" />
        </div>
      </el-form-item>
      <el-form-item :label="$t('tripDetail.lblEstCost')"><el-input-number v-model="stopFormLocal.estimated_cost" :min="0" :step="50" @change="onStopFormChange" /></el-form-item>
      <el-form-item :label="$t('tripDetail.lblDuration')"><el-input-number v-model="stopFormLocal.estimated_duration_minutes" :min="0" :step="30" @change="onStopFormChange" /></el-form-item>
      <el-form-item :label="$t('tripDetail.lblDesc')"><el-input v-model="stopFormLocal.description" type="textarea" :rows="2" @input="onStopFormChange" /></el-form-item>
    </el-form>
    <template #footer>
      <template v-if="editType === 'edit-trip'">
        <el-button @click="emit('update:dialog-visible', false)">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" @click="emit('save-trip')">{{ $t('common.save') }}</el-button>
      </template>
      <template v-else-if="editType === 'add-day'">
        <el-button @click="emit('update:dialog-visible', false)">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" @click="emit('save-day')">{{ $t('common.save') }}</el-button>
      </template>
      <template v-else>
        <el-button @click="emit('update:dialog-visible', false)">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" @click="emit(editType === 'edit-stop' ? 'save-edit-stop' : 'save-stop')">
          {{ editType === 'edit-stop' ? $t('common.save') : $t('tripDetail.addStop') }}
        </el-button>
      </template>
    </template>
  </el-dialog>
</template>

<style scoped>
.gen-days-hint { font-size: 12px; color: var(--faint); line-height: 1.6; }
.latlng { display: flex; gap: 8px; width: 100%; }

/* 分享设置 */
.share-settings-hint { font-size: 13px; color: var(--muted); margin-bottom: 14px; }
.share-settings-body { min-height: 80px; }
.share-settings-empty { text-align: center; color: var(--faint); padding: 24px 0; }
.share-setting-card { border: 1px solid var(--line); border-radius: var(--radius-lg); padding: 14px 16px; margin-bottom: 12px; background: #fff; }
.share-setting-card.revoked { opacity: 0.65; background: #fafafa; }
.ss-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.ss-kind { font-size: 14px; font-weight: 600; color: var(--ink); }
.ss-row { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--ink-2); padding: 5px 0; flex-wrap: wrap; }
.ss-label { color: var(--faint); flex-shrink: 0; min-width: 64px; }
.ss-value { flex: 1; min-width: 0; word-break: break-all; }
.ss-url { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--brand); }
.ss-actions { margin-top: 6px; display: flex; justify-content: flex-end; }

@media (max-width: 640px) {
  .latlng { flex-direction: column; }
}
</style>