<script setup>
// 小红书笔记生成/分享对话框（方案 A：内容工厂 + 手动发布）
// 主路径：后端 LLM 生成文案 → 用户编辑 → 复制 → 小红书 App 粘贴发布
// 附带：3:4 封面卡（1080×1440 等效）导出为 PNG（复用 html2canvas，与导出图片一致）
import { ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Picture, CopyDocument, Refresh, Promotion } from '@element-plus/icons-vue'
import * as api from '@/api'
import { exportImage, renderToDataUrl } from '@/utils/export'

const props = defineProps({
  modelValue: Boolean,
  tripId: { type: String, required: true },
  trip: { type: Object, default: null }, // 行程对象（含 destination/title/days），用于封面卡
})
const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// ── 文案状态 ─────────────────────────────
const loading = ref(false)
const note = ref(null) // { title, body, topics, full_text, source }
const title = ref('')
const body = ref('')
const topicsText = ref('')

const sourceLabel = computed(() =>
  note.value?.source === 'llm' ? t('xhsNote.aiGenerated') : t('xhsNote.templateGenerated')
)
const sourceTagType = computed(() => (note.value?.source === 'llm' ? 'success' : 'warning'))

const fullText = computed(() => {
  const topics = topicsText.value
    .split(/[#\s,，]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  const topicsLine = topics.length ? `\n\n${topics.map((x) => `#${x}`).join(' ')}` : ''
  return `${title.value}\n${body.value}${topicsLine}`
})

function fmtDayRange(start, end) {
  if (!start || !end) return ''
  const d = (x) => new Date(x)
  const days = Math.max(1, Math.round((d(end) - d(start)) / 86400000) + 1)
  return `${days}天`
}

function fmtStops() {
  const days = props.trip?.days || []
  const stops = []
  for (const day of days) {
    for (const s of day.stops || []) {
      if (s.name) stops.push({ name: s.name, type: s.stop_type })
    }
  }
  return stops
}

// ── 生成 ────────────────────────────────
async function generate() {
  loading.value = true
  try {
    const r = await api.generateXhsNote(props.tripId)
    note.value = r
    title.value = r.title
    body.value = r.body
    topicsText.value = (r.topics || []).map((x) => `#${x}`).join(' ')
    ElMessage.success(t('xhsNote.generatedOk'))
  } catch (e) {
    ElMessage.error(t('xhsNote.genFail'))
  } finally {
    loading.value = false
  }
}

async function regenerate() {
  await generate()
}

// ── 复制 / 打开 App ─────────────────────
async function copyText(text, okKey) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(t(okKey))
  } catch {
    // 剪贴板不可用（如非 https）→ 回退提示
    ElMessage.success(t('xhsNote.copyFallback', { text }))
  }
}

function copyAll() {
  copyText(fullText.value, 'xhsNote.copiedAll')
}

function copyBody() {
  copyText(body.value, 'xhsNote.copiedBody')
}

function openApp() {
  // 打开小红书（App 或网页）。Web 端无公开发布接口，App 粘贴体验最佳。
  window.open('https://www.xiaohongshu.com/', '_blank')
}

// ── 封面图导出（3:4 卡） ─────────────────
const coverRef = ref(null)
const coverExporting = ref(false)

async function exportCover() {
  if (!coverRef.value) return
  coverExporting.value = true
  try {
    await nextTick()
    const name = `${props.trip?.destination || 'trip'}-xhs-cover`
    await exportImage(coverRef.value, name)
    ElMessage.success(t('xhsNote.coverExported'))
  } catch (e) {
    ElMessage.error(t('xhsNote.coverFail', { msg: e.message }))
  } finally {
    coverExporting.value = false
  }
}

const coverStops = computed(() => fmtStops().slice(0, 6))
const coverDays = computed(() => {
  if (!props.trip) return 0
  const end = new Date(props.trip.end_date)
  const start = new Date(props.trip.start_date)
  return Math.max(1, Math.round((end - start) / 86400000) + 1)
})

function coverEmoji(type) {
  return { attraction: '🏞️', food: '🍜', hotel: '🏨' }[type] || '📍'
}

// ── 发布通道（策略 + 工厂；后端默认 manual） ──────────
// channel.mode: manual（复制文案）/ agent（本机发布助手）/ rpa（服务端自动填表）
const channel = ref({ mode: 'manual', requires_images: false, supports_auto_submit: false })
const publishState = ref('') // pending_agent / queued / running / ready / published / unknown / failed / manual
const publishMessage = ref('')
const publishUrl = ref('')
const publishAutoSubmit = ref(false)
const publishing = ref(false)

// 非手动通道都显示「发布」按钮：agent 下发任务到本地助手，rpa 由服务端填表
const canAutoPublish = computed(() => ['rpa', 'agent'].includes(channel.value?.mode))
const isAgent = computed(() => channel.value?.mode === 'agent')
const publishBusy = computed(
  () => publishing.value || ['pending_agent', 'queued', 'running'].includes(publishState.value),
)
const publishStateType = computed(
  () =>
    ({
      pending_agent: 'info',
      ready: 'warning',
      published: 'success',
      unknown: 'warning',
      failed: 'danger',
      manual: 'info',
    })[publishState.value] || 'info',
)
const publishStateLabel = computed(() => {
  const key = `xhsNote.publishState.${publishState.value}`
  return publishState.value ? t(key) : ''
})
const channelLabel = computed(() =>
  isAgent.value
    ? t('xhsNote.publishModeAgent')
    : channel.value?.mode === 'rpa'
      ? t('xhsNote.publishModeRpa')
      : t('xhsNote.publishModeManual'),
)
const channelHint = computed(() =>
  isAgent.value
    ? t('xhsNote.publishAgentHint')
    : channel.value?.mode === 'rpa'
      ? t('xhsNote.publishRpaHint')
      : t('xhsNote.publishManualHint'),
)

async function loadChannel() {
  try {
    channel.value = await api.getXhsChannels(props.tripId)
  } catch {
    // 通道能力是旁路信息：拿不到就按手动模式渲染，绝不阻断对话框
    channel.value = { mode: 'manual', requires_images: false, supports_auto_submit: false }
  }
}

function topicsList() {
  return topicsText.value
    .split(/[#\s,，]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function publishReasonText(job) {
  const map = {
    login_required: t('xhsNote.publishReasonLogin'),
    driver_not_ready: t('xhsNote.publishReasonDriver'),
    semi_auto_requires_visible_browser: t('xhsNote.publishReasonSemiAuto'),
    no_images: t('xhsNote.publishReasonNoImage'),
    asset_missing: t('xhsNote.publishReasonNoImage'),
    asset_path_not_ascii: t('xhsNote.publishReasonNoImage'),
    title_too_long: t('xhsNote.publishReasonTitle'),
    body_too_long: t('xhsNote.publishReasonBody'),
    submit_failed: t('xhsNote.publishReasonStructure'),
    submit_disabled: t('xhsNote.publishReasonStructure'),
    selector_miss: t('xhsNote.publishReasonStructure'),
    expired: t('xhsNote.publishReasonAgentExpired'),
    superseded: t('xhsNote.publishReasonSuperseded'),
  }
  return map[job?.reason] || job?.message || ''
}

async function pollJob(jobId) {
  for (let i = 0; i < 80; i += 1) {
    await new Promise((r) => setTimeout(r, 1500))
    if (!visible.value) return
    try {
      const job = await api.getXhsPublishJob(props.tripId, jobId)
      publishState.value = job.state
      publishMessage.value = publishReasonText(job)
      if (job.note_url) publishUrl.value = job.note_url
      if (!['queued', 'running'].includes(job.state)) return
    } catch (e) {
      publishState.value = 'failed'
      publishMessage.value = e?.response?.data?.error?.message || e.message
      return
    }
  }
  publishState.value = 'unknown'
  publishMessage.value = t('xhsNote.publishReasonTimeout')
}

async function publishToXhs() {
  if (publishBusy.value) return
  if (!title.value.trim() || !body.value.trim()) {
    ElMessage.warning(t('xhsNote.publishNeedContent'))
    return
  }
  publishing.value = true
  publishState.value = 'queued'
  publishMessage.value = ''
  publishUrl.value = ''
  try {
    let assetIds = []
    if (channel.value?.requires_images) {
      // 发布通道要"服务端能读到的文件"：把封面卡 canvas 转 PNG 上传
      if (!coverRef.value) throw new Error(t('xhsNote.publishReasonNoImage'))
      const dataUrl = await renderToDataUrl(coverRef.value)
      const asset = await api.uploadXhsAsset(props.tripId, dataUrl)
      assetIds = [asset.asset_id]
    }
    const job = await api.publishXhsNote(props.tripId, {
      title: title.value,
      body: body.value,
      topics: topicsList(),
      asset_ids: assetIds,
      // agent 通道由本地助手发布，auto_submit 无意义
      auto_submit: !isAgent.value && canAutoPublish.value && publishAutoSubmit.value,
    })
    publishState.value = job.state
    if (isAgent.value && job.state === 'pending_agent') {
      publishMessage.value = t('xhsNote.publishAgentDispatched')
    }
    await pollJob(job.job_id)
  } catch (e) {
    publishState.value = 'failed'
    publishMessage.value =
      e?.response?.data?.error?.message || e?.message || t('xhsNote.publishFailed')
  } finally {
    publishing.value = false
  }
}

// 打开对话框时若尚无文案则自动生成一次；同时拉取发布通道能力
watch(visible, (v) => {
  if (v) {
    loadChannel()
    if (!note.value && !loading.value) generate()
  }
})
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="t('xhsNote.title')"
    width="720px"
    :close-on-click-modal="false"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <div v-loading="loading" class="xhs-dialog">
      <!-- 顶部操作 -->
      <div class="xhs-toolbar">
        <el-tag v-if="note" size="small" :type="sourceTagType" round>{{ sourceLabel }}</el-tag>
        <span class="flex-spacer"></span>
        <el-button size="small" :loading="loading" @click="regenerate">
          <el-icon><Refresh /></el-icon>&nbsp;{{ t('xhsNote.regenerate') }}
        </el-button>
        <el-button size="small" type="primary" :loading="loading" @click="generate">
          {{ t('xhsNote.generate') }}
        </el-button>
      </div>

      <!-- 文案编辑（标题 / 正文 / 话题） -->
      <div class="xhs-form">
        <div class="xhs-field">
          <div class="xhs-label">{{ t('xhsNote.titleLabel') }}</div>
          <el-input v-model="title" :maxlength="20" show-word-limit :placeholder="t('xhsNote.titlePh')" />
        </div>
        <div class="xhs-field">
          <div class="xhs-label">{{ t('xhsNote.bodyLabel') }}</div>
          <el-input
            v-model="body"
            type="textarea"
            :rows="9"
            :maxlength="1000"
            show-word-limit
            :placeholder="t('xhsNote.bodyPh')"
          />
        </div>
        <div class="xhs-field">
          <div class="xhs-label">{{ t('xhsNote.topicsLabel') }}</div>
          <el-input v-model="topicsText" :placeholder="t('xhsNote.topicsPh')" />
        </div>
      </div>

      <!-- 预览 -->
      <div class="xhs-preview">
        <div class="xhs-preview-title">{{ t('xhsNote.preview') }}</div>
        <pre class="xhs-preview-body">{{ fullText }}</pre>
      </div>

      <!-- 操作：复制 + 打开 App -->
      <div class="xhs-actions">
        <el-button type="primary" @click="copyAll">
          <el-icon><CopyDocument /></el-icon>&nbsp;{{ t('xhsNote.copyAll') }}
        </el-button>
        <el-button @click="copyBody">
          {{ t('xhsNote.copyBody') }}
        </el-button>
        <el-button plain @click="openApp">
          <el-icon><Promotion /></el-icon>&nbsp;{{ t('xhsNote.openApp') }}
        </el-button>
        <span class="xhs-hint">{{ t('xhsNote.stepsHint') }}</span>
      </div>

      <!-- 封面图（3:4） -->
      <div class="xhs-cover-section">
        <div class="xhs-cover-head">
          <span>{{ t('xhsNote.coverLabel') }}</span>
          <el-button size="small" :loading="coverExporting" @click="exportCover">
            <el-icon><Picture /></el-icon>&nbsp;{{ t('xhsNote.exportCover') }}
          </el-button>
        </div>
        <div ref="coverRef" class="xhs-cover">
          <div class="cover-top">
            <div class="cover-dest">{{ props.trip?.destination || 'Trip' }}</div>
            <div class="cover-days">{{ coverDays }} {{ t('xhsNote.daysUnit') }}</div>
          </div>
          <div class="cover-title">{{ title || props.trip?.title || t('xhsNote.coverShareTag') }}</div>
          <div class="cover-stops">
            <div v-for="(s, i) in coverStops" :key="i" class="cover-stop">
              <span class="cover-stop-emoji">{{ coverEmoji(s.type) }}</span>
              <span class="cover-stop-name">{{ s.name }}</span>
            </div>
            <div v-if="!coverStops.length" class="cover-stop-empty">{{ t('xhsNote.coverEmpty') }}</div>
          </div>
          <div class="cover-foot">
            <span>#{{ props.trip?.destination || '' }}</span>
            <span>{{ t('xhsNote.coverShareTag') }}</span>
          </div>
        </div>
        <div class="xhs-cover-spec">{{ t('xhsNote.coverSpec') }}</div>
      </div>

      <!-- 发布通道（方案 C：自动填表 / 手动复制；能力由后端工厂下发） -->
      <div class="xhs-publish">
        <div class="xhs-publish-head">
          <span class="xhs-publish-name">{{ t('xhsNote.publishTitle') }}</span>
          <el-tag size="small" :type="canAutoPublish ? 'success' : 'info'" round>
            {{ channelLabel }}
          </el-tag>
        </div>
        <div class="xhs-publish-hint">
          {{ channelHint }}
        </div>
        <div class="xhs-publish-actions">
          <el-button
            v-if="canAutoPublish"
            type="primary"
            size="small"
            :loading="publishBusy"
            @click="publishToXhs"
          >
            <el-icon><Promotion /></el-icon>&nbsp;{{ t('xhsNote.publishAction') }}
          </el-button>
          <el-checkbox
            v-if="canAutoPublish && !isAgent"
            v-model="publishAutoSubmit"
            :disabled="publishBusy"
          >
            {{ t('xhsNote.publishAutoSubmit') }}
          </el-checkbox>
          <el-tag v-if="publishState" size="small" :type="publishStateType">
            {{ publishStateLabel }}
          </el-tag>
        </div>
        <div v-if="publishMessage" class="xhs-publish-msg">{{ publishMessage }}</div>
        <a
          v-if="publishUrl"
          :href="publishUrl"
          target="_blank"
          rel="noopener"
          class="xhs-publish-link"
          >{{ publishUrl }}</a
        >
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">{{ t('common.close') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.xhs-dialog {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.xhs-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.flex-spacer {
  flex: 1;
}
.xhs-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.xhs-field .xhs-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.xhs-preview {
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--el-fill-color-lighter);
}
.xhs-preview-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.xhs-preview-body {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  max-height: 180px;
  overflow: auto;
  font-family: inherit;
}
.xhs-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.xhs-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.xhs-cover-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.xhs-cover-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
}
.xhs-cover {
  /* 小红书图文笔记封面 3:4；导出按源元素渲染（html2canvas scale=2 → 对应 1080×1440 语义） */
  width: 540px;
  height: 720px;
  border-radius: 12px;
  background: linear-gradient(160deg, #ffe9ef 0%, #ffd6e0 55%, #ffb8c9 100%);
  padding: 28px 24px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: #3d2b30;
}
.cover-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.cover-days {
  background: rgba(255, 255, 255, 0.75);
  padding: 4px 10px;
  border-radius: 999px;
}
.cover-title {
  font-size: 30px;
  font-weight: 800;
  line-height: 1.25;
  margin-top: 26px;
  margin-bottom: 18px;
}
.cover-stops {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}
.cover-stop {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 15px;
  font-weight: 600;
}
.cover-stop-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cover-stop-empty {
  color: rgba(61, 43, 48, 0.6);
  font-size: 14px;
}
.cover-foot {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 700;
  margin-top: 14px;
}
.xhs-cover-spec {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
/* ── 发布通道 ─────────────────────────────── */
.xhs-publish {
  border-top: 1px dashed var(--el-border-color);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.xhs-publish-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.xhs-publish-name {
  font-size: 13px;
  font-weight: 600;
}
.xhs-publish-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.xhs-publish-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.xhs-publish-msg {
  font-size: 12px;
  color: var(--el-text-color-regular);
  word-break: break-word;
}
.xhs-publish-link {
  font-size: 12px;
  word-break: break-all;
}
</style>