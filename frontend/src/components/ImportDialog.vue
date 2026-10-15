<script setup>
// 内容导入对话框（task-import-ui-wiring）：四通道接线后端零凭证导入 API。
// - 笔记 / 截图 / 分享链接 / 预订邮件 → 纯规则解析 → 站点候选（外部内容按敌意源，
//   指令型行由后端剥离为 flagged_lines，前端只作数据展示，绝不当作指令执行）
// - 勾选候选 → 选目标行程 + 汇入日程 → 逐个 addStop 落库（串行避免同日 order 竞态）
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import * as api from '@/api'

const visible = defineModel({ type: Boolean, default: false })
const props = defineProps({
  // 从详情页打开时预选当前行程（TripDetailView 导入入口）
  presetTripId: { type: String, default: '' },
})
const emit = defineEmits(['imported'])
const { t } = useI18n()

const tab = ref('note')
const textInput = ref('')
const linkInput = ref('')
const screenshotName = ref('')
let fileRaw = null

const parsing = ref(false)
const importing = ref(false)
const creatingDay = ref(false)

const candidates = ref([]) // { _checked, name, stop_type, description, estimated_cost, estimated_duration_minutes }
const bookings = ref([])
const flaggedLines = ref([])
const linkResult = ref(null)

const trips = ref([])
const targetTripId = ref('')
const targetDayId = ref('')

const dialogWidth = 'min(680px, 94vw)'

const canParse = computed(() => {
  if (tab.value === 'screenshot') return !!fileRaw
  if (tab.value === 'link') return linkInput.value.trim().length >= 6
  return textInput.value.trim().length > 0
})
const checkedCount = computed(() => candidates.value.filter((c) => c._checked).length)
const flaggedSummary = computed(() =>
  flaggedLines.value.map((f) => `L${f.line_number} ${f.content || ''}`).join('；').slice(0, 200),
)
const targetTripDays = computed(() => {
  const tr = trips.value.find((x) => x.id === targetTripId.value)
  return (tr?.days || []).slice().sort((a, b) => a.day_number - b.day_number)
})

watch(visible, (v) => {
  if (v) {
    reset()
    loadTrips()
  }
})

function reset() {
  textInput.value = ''
  linkInput.value = ''
  screenshotName.value = ''
  fileRaw = null
  candidates.value = []
  bookings.value = []
  flaggedLines.value = []
  linkResult.value = null
  targetTripId.value = ''
  targetDayId.value = ''
}

async function loadTrips() {
  try {
    const data = await api.listTrips({ limit: 100 })
    trips.value = data.items || []
    // 预选当前行程（详情页导入入口）：列表里存在则直接选中其首个日程
    if (props.presetTripId && trips.value.some((x) => x.id === props.presetTripId)) {
      targetTripId.value = props.presetTripId
      targetDayId.value = targetTripDays.value[0]?.id || ''
    }
  } catch {
    /* 拦截器已提示 */
  }
}

function onFileChange(file) {
  fileRaw = file.raw || null
  screenshotName.value = file.name || ''
}

function typeLabel(type) {
  const map = { attraction: 'typeAttraction', food: 'typeFood', hotel: 'typeHotel' }
  return t('importDialog.' + (map[type] || 'typeAttraction'))
}

function bookingTagType(kind) {
  return { flight: 'primary', hotel: 'success', activity: 'warning' }[kind] || 'info'
}

async function parse() {
  parsing.value = true
  try {
    let res
    if (tab.value === 'screenshot') {
      if (!fileRaw) return
      res = await api.importScreenshot(fileRaw)
    } else if (tab.value === 'link') {
      res = await api.importLink({ url: linkInput.value.trim() })
    } else if (tab.value === 'email') {
      res = await api.importEmail({ text: textInput.value })
    } else {
      res = await api.importNote({ text: textInput.value })
    }
    applyResult(res)
  } catch {
    /* api 拦截器已统一提示 */
  } finally {
    parsing.value = false
  }
}

function applyResult(res) {
  candidates.value = (res.candidates || []).map((c) => ({ ...c, _checked: true }))
  bookings.value = res.bookings || []
  flaggedLines.value = res.flagged_lines || []
  linkResult.value = res.extracted !== undefined ? res : null
  if (trips.value.length) {
    targetTripId.value = trips.value[0].id
    targetDayId.value = targetTripDays.value[0]?.id || ''
  }
}

async function ensureDay() {
  if (!targetTripId.value) return
  creatingDay.value = true
  try {
    const day = await api.addDay(targetTripId.value, { day_number: 1 })
    await loadTrips()
    targetDayId.value = day.id
    ElMessage.success(t('importDialog.dayCreated'))
  } catch {
    /* 拦截器已提示 */
  } finally {
    creatingDay.value = false
  }
}

async function commit() {
  const dayId = targetDayId.value
  const picked = candidates.value.filter((c) => c._checked)
  if (!dayId || !picked.length) return
  importing.value = true
  try {
    // 串行落库：同日并发 addStop 可能造成 order_index 竞态
    for (const c of picked) {
      const payload = { name: c.name, stop_type: c.stop_type, description: c.description || undefined }
      if (c.estimated_cost != null) payload.estimated_cost = c.estimated_cost
      if (c.estimated_duration_minutes != null) payload.estimated_duration_minutes = c.estimated_duration_minutes
      await api.addStop(dayId, payload)
    }
    ElMessage.success(t('importDialog.committed', { n: picked.length }))
    visible.value = false
    emit('imported')
  } catch {
    /* 拦截器已提示 */
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="t('importDialog.title')" :width="dialogWidth" destroy-on-close>
    <el-tabs v-model="tab" class="import-tabs">
      <el-tab-pane :label="t('importDialog.tabNote')" name="note" />
      <el-tab-pane :label="t('importDialog.tabScreenshot')" name="screenshot" />
      <el-tab-pane :label="t('importDialog.tabLink')" name="link" />
      <el-tab-pane :label="t('importDialog.tabEmail')" name="email" />
    </el-tabs>

    <!-- 输入区 -->
    <div v-if="tab === 'note' || tab === 'email'" class="input-area">
      <el-input
        v-model="textInput"
        type="textarea"
        :rows="8"
        :placeholder="tab === 'note' ? t('importDialog.notePlaceholder') : t('importDialog.emailPlaceholder')"
        maxlength="20000"
        show-word-limit
      />
    </div>
    <div v-else-if="tab === 'screenshot'" class="input-area">
      <el-upload :auto-upload="false" :show-file-list="false" accept="image/*" :limit="1" :on-change="onFileChange">
        <el-button type="primary" plain :loading="parsing">
          <el-icon style="margin-right: 4px"><Upload /></el-icon>{{ t('importDialog.chooseImage') }}
        </el-button>
      </el-upload>
      <p class="hint">{{ t('importDialog.screenshotHint') }}</p>
      <p v-if="screenshotName" class="file-name">{{ screenshotName }}</p>
    </div>
    <div v-else class="input-area">
      <el-input v-model="linkInput" :placeholder="t('importDialog.linkPlaceholder')" clearable>
        <template #prepend>URL</template>
      </el-input>
    </div>

    <div class="actions">
      <el-button type="primary" :loading="parsing" :disabled="!canParse" @click="parse">
        {{ t('importDialog.parse') }}
      </el-button>
    </div>

    <!-- 邮件：识别到的预订条目（仅展示，金额供预算参考） -->
    <div v-if="bookings.length" class="result-block">
      <h4>{{ t('importDialog.bookingTitle') }}</h4>
      <div v-for="(b, i) in bookings" :key="i" class="booking-row">
        <el-tag size="small" :type="bookingTagType(b.kind)">{{ t('importDialog.bookingKind' + (b.kind[0].toUpperCase() + b.kind.slice(1))) }}</el-tag>
        <span class="booking-name">{{ b.name || '-' }}</span>
        <span v-if="b.code" class="booking-code">{{ b.code }}</span>
        <span v-if="b.datetime" class="booking-date">{{ b.datetime }}</span>
        <span v-if="b.amount != null" class="booking-amount">{{ b.currency }} {{ b.amount }}</span>
      </div>
    </div>

    <!-- 链接提取失败：静默降级为链接收藏 -->
    <el-alert
      v-if="linkResult && !linkResult.extracted"
      type="info"
      :closable="false"
      class="result-block"
      :title="t('importDialog.linkFallback') + (linkResult.title ? '：' + linkResult.title : '')"
    />

    <!-- 站点候选 -->
    <div v-if="candidates.length" class="result-block">
      <h4>{{ t('importDialog.candidateTitle') }}（{{ checkedCount }}/{{ candidates.length }}）</h4>
      <div v-for="(c, idx) in candidates" :key="idx" class="candidate-row">
        <el-checkbox v-model="c._checked">{{ c.name }}</el-checkbox>
        <el-tag size="small" type="info">{{ typeLabel(c.stop_type) }}</el-tag>
        <span v-if="c.estimated_cost != null" class="candidate-cost">¥{{ c.estimated_cost }}</span>
        <span v-if="c.estimated_duration_minutes != null" class="candidate-dur">{{ c.estimated_duration_minutes }}min</span>
        <p v-if="c.description" class="candidate-desc">{{ c.description }}</p>
      </div>
    </div>

    <!-- 敌意行（已剥离，不进入候选） -->
    <el-alert
      v-if="flaggedLines.length"
      type="warning"
      :closable="false"
      class="result-block"
      :title="t('importDialog.flaggedTitle')"
      :description="flaggedSummary"
    />

    <!-- 目标选择：行程 + 汇入日程 -->
    <div v-if="candidates.length && checkedCount" class="target-area">
      <el-form label-position="top">
        <el-form-item :label="t('importDialog.targetTrip')" style="margin-bottom: 12px">
          <el-select v-model="targetTripId" filterable :placeholder="t('importDialog.selectTrip')" style="width: 100%">
            <el-option v-for="tr in trips" :key="tr.id" :label="`${tr.title}（${tr.destination || '?'}）`" :value="tr.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('importDialog.targetDay')" style="margin-bottom: 12px">
          <template v-if="targetTripDays.length">
            <el-select v-model="targetDayId" style="width: 100%">
              <el-option v-for="d in targetTripDays" :key="d.id" :label="t('importDialog.dayLabel', { n: d.day_number })" :value="d.id" />
            </el-select>
          </template>
          <el-button v-else type="primary" plain size="small" :loading="creatingDay" @click="ensureDay">
            {{ t('importDialog.createDay') }}
          </el-button>
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="importing" :disabled="!targetDayId" @click="commit">
        <el-icon style="margin-right: 4px"><Download /></el-icon>{{ t('importDialog.commit') }}
      </el-button>
    </div>

    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.import-tabs { margin-bottom: 14px; }
.input-area { margin-bottom: 12px; }
.hint { font-size: 12px; color: var(--muted); margin: 8px 0 0; }
.file-name { font-size: 12px; color: var(--brand); margin: 4px 0 0; }
.actions { margin: 4px 0 8px; }

.result-block {
  margin: 10px 0;
  padding: 12px 14px;
  background: var(--surface-2, #fafafa);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.result-block h4 { margin: 0 0 8px; font-size: 13px; color: var(--ink-2); }
.booking-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 4px 0; font-size: 13px; }
.booking-name { font-weight: 500; }
.booking-code { color: var(--muted); font-family: monospace; }
.booking-date { color: var(--muted); }
.booking-amount { color: var(--success); font-weight: 600; }

.candidate-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 6px 0; border-bottom: 1px dashed var(--line);
}
.candidate-row:last-child { border-bottom: none; }
.candidate-cost { color: var(--success); font-size: 12px; font-weight: 500; }
.candidate-dur { color: var(--muted); font-size: 12px; }
.candidate-desc { flex-basis: 100%; margin: 2px 0 0 24px; font-size: 12px; color: var(--muted); }

.target-area {
  margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line);
}
</style>