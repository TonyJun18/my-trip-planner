<script setup>
// 内容导入对话框（task-import-ui-wiring）：四通道接线后端零凭证导入 API。
// - 笔记 / 截图 / 分享链接 / 预订邮件 → 纯规则解析 → 站点候选（外部内容按敌意源，
//   指令型行由后端剥离为 flagged_lines，前端只作数据展示，绝不当作指令执行）
// - 勾选候选 → 选目标行程 + 汇入日程 → 逐个 addStop 落库（串行避免同日 order 竞态）
import { ref, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import * as api from '@/api'
import { buildByoPrompt, parseByoDraft } from '@/utils/byoPrompt'

const visible = defineModel({ type: Boolean, default: false })
const props = defineProps({
  // 从详情页打开时预选当前行程（TripDetailView 导入入口）
  presetTripId: { type: String, default: '' },
  // PWA Web Share Target 预填（task-share-target-eval）：系统分享进来时
  // 直接带着 { tab: 'social'|'link', text?, url? } 打开并自动解析。
  // 外部内容只作为候选数据展示（后端 social/link import 已做敌意行剥离）。
  prefill: { type: Object, default: null },
})
const emit = defineEmits(['imported'])
const { t, locale: i18nLocale } = useI18n()

const tab = ref('note')
const textInput = ref('')
const linkInput = ref('')
// BYO-AI 草稿（task-byo-ai-import-kit）：用户在自己 AI 生成草稿 → 粘贴解析为候选
const byoInput = ref('')
const byoPromptCopied = ref(false)
const byoPrompt = computed(() => buildByoPrompt(i18nLocale.value))
// 批量截图导入（task-photo-batch-screenshot）：多选 → 串行 OCR → 合并去重
const MAX_SCREENSHOTS = 12
const screenshotFiles = ref([]) // [{ uid, raw, name }]
const parseProgress = ref({ done: 0, total: 0 })

const parsing = ref(false)
const importing = ref(false)
const creatingDay = ref(false)
const collecting = ref(false)

const candidates = ref([]) // { _checked, name, stop_type, description, estimated_cost, estimated_duration_minutes }
const bookings = ref([])
const flaggedLines = ref([])
const linkResult = ref(null)

const trips = ref([])
const targetTripId = ref('')
const targetDayId = ref('')

const dialogWidth = 'min(680px, 94vw)'

const canParse = computed(() => {
  if (tab.value === 'screenshot') return screenshotFiles.value.length > 0
  if (tab.value === 'link') return linkInput.value.trim().length >= 6
  if (tab.value === 'byo') return byoInput.value.trim().length > 0
  return textInput.value.trim().length > 0
})
const parseButtonText = computed(() =>
  parsing.value && tab.value === 'screenshot' && parseProgress.value.total
    ? t('importDialog.parsingProgress', parseProgress.value)
    : t('importDialog.parse'),
)
const checkedCount = computed(() => candidates.value.filter((c) => c._checked).length)
const flaggedSummary = computed(() =>
  flaggedLines.value.map((f) => `L${f.line_number} ${f.content || ''}`).join('；').slice(0, 200),
)
const targetTripDays = computed(() => {
  const tr = trips.value.find((x) => x.id === targetTripId.value)
  return (tr?.days || []).slice().sort((a, b) => a.day_number - b.day_number)
})

// 小红书「抄作业」引导：平台反爬拿不到正文（link_import 的 _DEEP_EXTRACT_PLATFORMS 不含 xiaohongshu），
// 与其让用户以为解析成功，不如直接把「粘贴正文」这条路指出来（零凭证，不破反爬）。
const XHS_RE = /xiaohongshu\.com|xhslink\.com/i
const isXhsPlatform = computed(
  () => linkResult.value?.platform === 'xiaohongshu' || XHS_RE.test(linkInput.value),
)
const showXhsGuide = computed(
  () =>
    tab.value === 'link' &&
    isXhsPlatform.value &&
    (!linkResult.value || !linkResult.value.extracted || !(linkResult.value.candidates || []).length),
)

function usePasteBody() {
  const url = linkResult.value?.url || linkInput.value.trim()
  tab.value = 'social'
  textInput.value = url ? `${url}\n` : ''
}

watch(visible, (v) => {
  if (v) {
    reset()
    loadTrips()
    // PWA Web Share Target 预填（task-share-target-eval）：有分享内容则
    // 自动切到对应 tab 并解析；无则空对话框（用户手动粘贴）。
    if (props.prefill) {
      if (props.prefill.tab === 'link' && props.prefill.url) {
        tab.value = 'link'
        linkInput.value = props.prefill.url
        nextTick(() => parse())
      } else if (props.prefill.tab === 'social' && props.prefill.text) {
        tab.value = 'social'
        textInput.value = props.prefill.text
        nextTick(() => parse())
      }
    }
  }
})

function reset() {
  textInput.value = ''
  linkInput.value = ''
  byoInput.value = ''
  byoPromptCopied.value = false
  screenshotFiles.value = []
  parseProgress.value = { done: 0, total: 0 }
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
  const raw = file?.raw
  if (!raw) return
  // el-upload 对多选逐张触发 on-change：按 uid 去重（受控列表在本地维护）
  if (screenshotFiles.value.some((f) => f.uid === file.uid)) return
  if (screenshotFiles.value.length >= MAX_SCREENSHOTS) {
    ElMessage.warning(t('importDialog.screenshotLimit', { n: MAX_SCREENSHOTS }))
    return
  }
  screenshotFiles.value.push({ uid: file.uid, raw, name: file.name || 'image' })
}

function onExceed() {
  ElMessage.warning(t('importDialog.screenshotLimit', { n: MAX_SCREENSHOTS }))
}

function removeScreenshot(index) {
  screenshotFiles.value.splice(index, 1)
}

function typeLabel(type) {
  const map = { attraction: 'typeAttraction', food: 'typeFood', hotel: 'typeHotel' }
  return t('importDialog.' + (map[type] || 'typeAttraction'))
}

function bookingTagType(kind) {
  return { flight: 'primary', hotel: 'success', activity: 'warning' }[kind] || 'info'
}

function normalizeName(name) {
  return String(name || '').trim().toLowerCase().replace(/\s+/g, '')
}

// 批量截图：逐张串行 OCR（并发会抢 CPU 且 macOS Vision 单进程易排队），
// 合并候选并按站点名去重；单张失败只跳过该张，不整体失败。
async function parseScreenshots() {
  const files = screenshotFiles.value
  const merged = []
  const seen = new Set()
  const flagged = []
  const failed = []
  let deduped = 0

  parseProgress.value = { done: 0, total: files.length }
  for (const f of files) {
    try {
      const res = await api.importScreenshot(f.raw, { silent: true })
      for (const c of res.candidates || []) {
        const key = normalizeName(c.name)
        if (!key) continue
        if (seen.has(key)) {
          deduped += 1
          continue
        }
        seen.add(key)
        merged.push({ ...c, _source: f.name })
      }
      if (res.flagged_lines?.length) flagged.push(...res.flagged_lines)
    } catch {
      failed.push(f.name) // 拦截器已静默（silent），失败整批汇总后提示
    } finally {
      parseProgress.value = { done: parseProgress.value.done + 1, total: files.length }
    }
  }

  applyResult({ candidates: merged, bookings: [], flagged_lines: flagged })
  if (deduped) ElMessage.info(t('importDialog.screenshotDedupe', { n: deduped }))
  if (failed.length) ElMessage.warning(t('importDialog.screenshotPartial', { n: failed.length }))
}

async function parse() {
  if (tab.value === 'screenshot') {
    if (!screenshotFiles.value.length) return
    parsing.value = true
    try {
      await parseScreenshots()
    } finally {
      parsing.value = false
      parseProgress.value = { done: 0, total: 0 }
    }
    return
  }

  parsing.value = true
  try {
    let res
    if (tab.value === 'link') {
      res = await api.importLink({ url: linkInput.value.trim() })
    } else if (tab.value === 'email') {
      res = await api.importEmail({ text: textInput.value })
    } else if (tab.value === 'social') {
      res = await api.importSocial({ text: textInput.value })
    } else if (tab.value === 'byo') {
      // BYO-AI 草稿：纯前端解析（零后端），散文降级走 note import 提示
      const parsed = parseByoDraft(byoInput.value)
      if (!parsed.length) {
        ElMessage.warning(t('importDialog.byoFallback'))
        tab.value = 'note'
        textInput.value = byoInput.value
        return
      }
      applyResult({ candidates: parsed, bookings: [], flagged_lines: [] })
      return
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

// BYO-AI：复制 prompt（带版本号）到剪贴板
async function copyByoPrompt() {
  try {
    await navigator.clipboard.writeText(byoPrompt.value)
    byoPromptCopied.value = true
    setTimeout(() => (byoPromptCopied.value = false), 2000)
  } catch {
    ElMessage.warning(t('importDialog.byoCopyFail'))
  }
}

function applyResult(res) {
  candidates.value = (res.candidates || []).map((c) => ({ ...c, _checked: true }))
  bookings.value = (res.bookings || []).map((b) => ({ ...b, _checked: true }))
  flaggedLines.value = res.flagged_lines || []
  linkResult.value = res.extracted !== undefined ? res : null
  // 保留已选目标（详情页预选当前行程）；仅未选时默认第一条
  if (trips.value.length && !targetTripId.value) {
    targetTripId.value = trips.value[0].id
    targetDayId.value = targetTripDays.value[0]?.id || ''
  }
}

// ── 邮件条目并入台账（task-booking-ledger-rhythm） ─────────────
// 解析是候选、落库是决定：只提交用户勾选的条目；服务端强制 pending +
// reference=email.import（绝不采信解析结果/前端状态），凭证由用户稍后回填。
const checkedBookings = computed(() => bookings.value.filter((b) => b._checked))
const mergingBookings = ref(false)

async function mergeBookingsToLedger() {
  const picked = checkedBookings.value
  if (!picked.length || mergingBookings.value) return
  if (!targetTripId.value) {
    ElMessage.warning(t('booking.mergeNeedTrip'))
    return
  }
  mergingBookings.value = true
  try {
    const items = picked.map((b) => ({
      kind: b.kind,
      name: b.name || undefined,
      code: b.code || undefined,
      datetime: b.datetime || undefined,
      amount: b.amount ?? undefined,
      currency: b.currency || 'CNY',
    }))
    const res = await api.mergeEmailBookings(targetTripId.value, items)
    ElMessage.success(t('booking.mergedOk', { n: res.total }))
    picked.forEach((b) => {
      b._checked = false
    })
    emit('imported')
  } catch {
    /* 拦截器已提示 */
  } finally {
    mergingBookings.value = false
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

// 存入收集箱（collect-first：导入候选先攒成地点收藏，行程定了再汇入）
// 不需要先选行程/日程；只取 schema 白名单字段，外部内容按敌意源处理。
async function collectToBox() {
  const picked = candidates.value.filter((c) => c._checked)
  if (!picked.length || collecting.value) return
  collecting.value = true
  try {
    const spots = picked.slice(0, 50).map((c) => {
      const spot = { name: c.name, stop_type: c.stop_type || 'attraction' }
      if (c.lat != null) spot.lat = c.lat
      if (c.lng != null) spot.lng = c.lng
      if (c.description) spot.description = c.description
      if (c.estimated_cost != null) spot.estimated_cost = c.estimated_cost
      if (c.estimated_duration_minutes != null) {
        spot.estimated_duration_minutes = c.estimated_duration_minutes
      }
      if (tab.value) spot.source_platform = tab.value
      return spot
    })
    const res = await api.collectFavoriteSpots(spots)
    ElMessage.success(
      t('importDialog.collectDone', { n: res.collected, skipped: res.skipped }),
    )
  } catch {
    /* 拦截器已提示 */
  } finally {
    collecting.value = false
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
      <el-tab-pane :label="t('importDialog.tabSocial')" name="social" />
      <el-tab-pane :label="t('importDialog.tabByo')" name="byo" />
    </el-tabs>

    <!-- BYO-AI 草稿（task-byo-ai-import-kit）：三步引导 + 可复制 prompt + 粘贴框 -->
    <div v-if="tab === 'byo'" class="input-area">
      <ol class="byo-steps">
        <li>{{ t('importDialog.byoStep1') }}</li>
        <li>
          {{ t('importDialog.byoStep2') }}
          <el-button size="small" plain class="byo-copy" :class="{ copied: byoPromptCopied }" @click="copyByoPrompt">
            {{ byoPromptCopied ? t('importDialog.byoCopied') : t('importDialog.byoCopy') }}
          </el-button>
        </li>
        <li>{{ t('importDialog.byoStep3') }}</li>
      </ol>
      <el-input
        v-model="byoInput"
        type="textarea"
        :rows="8"
        :placeholder="t('importDialog.byoPlaceholder')"
        maxlength="20000"
        show-word-limit
      />
      <p class="hint">{{ t('importDialog.byoHint') }}</p>
    </div>
    <!-- 输入区 -->
    <div v-if="tab === 'note' || tab === 'email' || tab === 'social'" class="input-area">
      <el-input
        v-model="textInput"
        type="textarea"
        :rows="8"
        :placeholder="tab === 'note' ? t('importDialog.notePlaceholder') : tab === 'email' ? t('importDialog.emailPlaceholder') : t('importDialog.socialPlaceholder')"
        maxlength="20000"
        show-word-limit
      />
    </div>
    <div v-else-if="tab === 'screenshot'" class="input-area">
      <el-upload
        :auto-upload="false"
        :show-file-list="false"
        accept="image/*"
        multiple
        :limit="MAX_SCREENSHOTS"
        :on-change="onFileChange"
        :on-exceed="onExceed"
      >
        <el-button type="primary" plain :loading="parsing">
          <el-icon style="margin-right: 4px"><Upload /></el-icon>{{ t('importDialog.chooseImage') }}
        </el-button>
      </el-upload>
      <p class="hint">{{ t('importDialog.screenshotHint', { n: MAX_SCREENSHOTS }) }}</p>
      <div v-if="screenshotFiles.length" class="shot-list">
        <span class="shot-count">{{ t('importDialog.screenshotSelected', { n: screenshotFiles.length }) }}</span>
        <el-tag
          v-for="(f, i) in screenshotFiles"
          :key="f.uid"
          size="small"
          :type="parsing ? 'info' : 'primary'"
          effect="plain"
          closable
          :disable-transitions="true"
          @close="removeScreenshot(i)"
        >
          {{ f.name }}
        </el-tag>
      </div>
    </div>
    <div v-else class="input-area">
      <el-input v-model="linkInput" :placeholder="t('importDialog.linkPlaceholder')" clearable>
        <template #prepend>URL</template>
      </el-input>
    </div>

    <div class="actions">
      <el-button type="primary" :loading="parsing" :disabled="!canParse" @click="parse">
        {{ parseButtonText }}
      </el-button>
    </div>

    <!-- 邮件：识别到的预订条目（勾选后可一键并入台账；服务端强制 pending） -->
    <div v-if="bookings.length" class="result-block">
      <h4>{{ t('importDialog.bookingTitle') }}</h4>
      <div v-for="(b, i) in bookings" :key="i" class="booking-row">
        <el-checkbox v-model="b._checked" />
        <el-tag size="small" :type="bookingTagType(b.kind)">{{ t('importDialog.bookingKind' + (b.kind[0].toUpperCase() + b.kind.slice(1))) }}</el-tag>
        <span class="booking-name">{{ b.name || '-' }}</span>
        <span v-if="b.code" class="booking-code">{{ b.code }}</span>
        <span v-if="b.datetime" class="booking-date">{{ b.datetime }}</span>
        <span v-if="b.amount != null" class="booking-amount">{{ b.currency }} {{ b.amount }}</span>
      </div>
      <p class="hint">{{ t('importDialog.bookingMergeHint') }}</p>
      <div class="booking-merge-row">
        <el-select v-model="targetTripId" filterable :placeholder="t('importDialog.selectTrip')" size="small" style="min-width: 220px">
          <el-option v-for="tr in trips" :key="tr.id" :label="`${tr.title}（${tr.destination || '?'}）`" :value="tr.id" />
        </el-select>
        <el-button
          size="small"
          type="primary"
          :loading="mergingBookings"
          :disabled="!checkedBookings.length || !targetTripId"
          @click="mergeBookingsToLedger"
        >
          <el-icon style="margin-right: 4px"><Download /></el-icon>{{ t('booking.mergeToLedger') }}（{{ checkedBookings.length }}）
        </el-button>
      </div>
    </div>

    <!-- 小红书：链接读不到正文 → 直接引导粘贴（零凭证，不破反爬） -->
    <el-alert
      v-if="showXhsGuide"
      type="warning"
      :closable="false"
      class="result-block"
      :title="t('importDialog.xhsGuideTitle')"
    >
      <p class="xhs-guide-body">{{ t('importDialog.xhsGuideBody') }}</p>
      <el-button size="small" type="primary" plain @click="usePasteBody">
        {{ t('importDialog.xhsGuideAction') }}
      </el-button>
    </el-alert>

    <!-- 链接提取失败：静默降级为链接收藏 -->
    <el-alert
      v-if="linkResult && !linkResult.extracted && !showXhsGuide"
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
        <span v-if="c._source" class="candidate-src" :title="c._source">📷 {{ c._source }}</span>
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
      <el-button :loading="collecting" @click="collectToBox">
        <el-icon style="margin-right: 4px"><Star /></el-icon>{{ t('importDialog.collectToBox') }}
      </el-button>
      <p class="hint">{{ t('importDialog.collectHint') }}</p>
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
.xhs-guide-body { margin: 4px 0 8px; font-size: 12.5px; line-height: 1.5; }
/* 批量截图：已选文件 chips（可单个移除，最多 12 张） */
.shot-list { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.shot-count { font-size: 12px; color: var(--muted); }
.candidate-src {
  font-size: 11px;
  color: var(--muted);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.actions { margin: 4px 0 8px; }
.byo-steps { margin: 0 0 10px; padding-left: 18px; font-size: 12.5px; line-height: 1.9; color: var(--ink-2); }
.byo-copy { margin-left: 8px; }
.byo-copy.copied { color: var(--success); border-color: var(--success); }

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
.booking-merge-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; }

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