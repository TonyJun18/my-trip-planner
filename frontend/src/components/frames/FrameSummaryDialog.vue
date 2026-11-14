<!--
  整程总结图生成器（frame-marketplace，Phase 2 任务 7）。

  与单日卡同源渲染器：封面头图 + 按日区块 + 全程轨迹 + 统计水印。
  照片仅内存；导出 PNG + 复制总结配文；无自动发布副作用。
-->
<template>
  <el-dialog
    v-model="visible"
    :title="t('frames.summary.title')"
    width="760px"
    :close-on-click-modal="false"
    @open="onOpen"
  >
    <div v-if="loaded && summary?.empty" class="frames-empty">
      📍 {{ t('frames.summary.emptyHint') }}
    </div>

    <template v-else-if="loaded">
      <div class="frames-layout">
        <div class="frames-controls">
          <div class="frames-section-title">{{ t('frames.summary.pickTemplate') }}</div>
          <div class="frames-template-grid">
            <div
              v-for="tpl in templates"
              :key="tpl.slug"
              class="frames-template-item"
              :class="{ active: tpl.slug === selectedSlug }"
              @click="selectedSlug = tpl.slug"
            >
              <div class="frames-template-name">{{ tpl.name || tpl.slug }}</div>
              <div class="frames-template-tier">
                <el-tag v-if="tpl.locked" size="small" type="warning">{{ t('frames.dialog.locked') }}</el-tag>
                <el-tag v-else-if="tpl.tier === 'free'" size="small" type="info">{{ t('frames.dialog.free') }}</el-tag>
                <el-tag v-else size="small" type="success">{{ t('frames.dialog.owned') }}</el-tag>
              </div>
            </div>
          </div>

          <div class="frames-section-title">{{ t('frames.summary.pickPhotos') }}</div>
          <div class="frames-photo-row">
            <input ref="fileRef" type="file" accept="image/*" multiple style="display: none" @change="onPickPhotos" />
            <el-button size="small" @click="fileRef?.click()">🖼️ {{ t('frames.dialog.addPhotos') }}</el-button>
            <span class="frames-photo-count">{{ photos.length }} / {{ maxPhotos }} {{ t('frames.dialog.photoUnit') }}</span>
            <el-button v-if="photos.length" size="small" text type="danger" @click="photos = []">
              {{ t('frames.dialog.clearPhotos') }}
            </el-button>
          </div>
          <div class="frames-privacy">{{ t('frames.dialog.privacyNote') }}</div>

          <div class="frames-section-title">{{ t('frames.dialog.copy') }}</div>
          <el-radio-group v-model="channel" size="small">
            <el-radio-button value="xhs">{{ t('frames.channel.xhs') }}</el-radio-button>
            <el-radio-button value="moments">{{ t('frames.channel.moments') }}</el-radio-button>
          </el-radio-group>
          <el-button class="frames-copy-btn" size="small" type="primary" plain :loading="copyLoading" @click="generateCopy">
            ✍️ {{ t('frames.dialog.genCopy') }}
          </el-button>
          <div v-if="copy" class="frames-copy-result">
            <el-tag size="small" :type="copy.source === 'llm' ? 'primary' : 'info'">
              {{ copy.source === 'llm' ? t('story.source.llm') : t('story.source.template') }}
            </el-tag>
            <pre class="frames-copy-text">{{ shareText }}</pre>
            <el-button size="small" @click="doCopyText">{{ t('story.copy') }}</el-button>
          </div>
        </div>

        <div class="frames-preview">
          <canvas ref="canvasRef" class="frames-canvas"></canvas>
          <el-button type="primary" :disabled="selectedLocked" @click="exportCard">
            ⬇️ {{ t('frames.dialog.export') }}
          </el-button>
          <div v-if="selectedLocked" class="frames-locked-hint">
            {{ t('frames.dialog.lockedExportHint') }}
            <router-link to="/frames">{{ t('frames.dialog.goStore') }}</router-link>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="frames-loading">{{ t('common.loading') }}</div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'

import { getFrameCatalog, getFrameSummaryData } from '@/api/modules/frames'
import http from '@/api/http'
import { composeShareText, copyText, downloadCanvas } from '@/frames/export'
import { renderSummaryCard } from '@/frames/renderer'

const props = defineProps({
  tripId: { type: String, required: true },
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loaded = ref(false)
const summary = ref(null)
const templates = ref([])
const selectedSlug = ref('')
const photos = ref([])
const channel = ref('xhs')
const copy = ref(null)
const copyLoading = ref(false)
const canvasRef = ref(null)
const fileRef = ref(null)

const selectedTemplate = computed(() => templates.value.find((tpl) => tpl.slug === selectedSlug.value))
const selectedLocked = computed(() => !!selectedTemplate.value?.locked)
const slotCount = computed(() => selectedTemplate.value?.layout_config?.photo_slots || 3)
const maxPhotos = computed(() => Math.max(1, (summary.value?.days?.length || 0) + 1))
const shareText = computed(() => composeShareText(copy.value))

async function onOpen() {
  loaded.value = false
  copy.value = null
  photos.value = []
  try {
    const [data, catalog] = await Promise.all([getFrameSummaryData(props.tripId), getFrameCatalog()])
    summary.value = data
    templates.value = catalog.templates || []
    const unlocked = templates.value.filter((tpl) => !tpl.locked)
    selectedSlug.value = (unlocked[0] || templates.value[0])?.slug || ''
    loaded.value = true
    await nextTick()
    drawPreview()
  } catch {
    ElMessage.error(t('frames.dialog.loadFailed'))
  }
}

function drawPreview() {
  if (!canvasRef.value || !summary.value) return
  renderSummaryCard(canvasRef.value, selectedTemplate.value || {}, {
    summary: summary.value,
    photos: photos.value.slice(0, maxPhotos.value),
    locked: selectedLocked.value,
  })
}

watch([selectedSlug, photos], () => drawPreview(), { deep: true })
watch(slotCount, () => {
  photos.value = photos.value.slice(0, maxPhotos.value)
})

async function onPickPhotos(ev) {
  const files = Array.from(ev.target?.files || [])
  ev.target.value = ''
  const bitmaps = []
  for (const f of files.slice(0, maxPhotos.value)) {
    try {
      bitmaps.push(await createImageBitmap(f))
    } catch {
      // 损坏格式跳过
    }
  }
  photos.value = [...photos.value, ...bitmaps].slice(0, maxPhotos.value)
}

async function generateCopy() {
  copyLoading.value = true
  try {
    copy.value = await http
      .post(`/trips/${props.tripId}/frames/summary/copy`, {
        channel: channel.value,
        provider: 'auto',
      })
      .then((r) => r.data)
  } catch {
    ElMessage.error(t('frames.dialog.copyFailed'))
  } finally {
    copyLoading.value = false
  }
}

async function doCopyText() {
  const ok = await copyText(shareText.value)
  ElMessage[ok ? 'success' : 'error'](t(ok ? 'story.copied' : 'story.copyFallback'))
}

function exportCard() {
  if (selectedLocked.value) return
  downloadCanvas(canvasRef.value, `trip-summary-${props.tripId.slice(0, 8)}.png`)
}

</script>

<style scoped>
.frames-layout { display: flex; gap: 16px; }
.frames-controls { flex: 1; min-width: 300px; }
.frames-preview { width: 310px; text-align: center; }
.frames-canvas { width: 300px; height: 400px; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.12); margin-bottom: 12px; background: #f5f5f5; }
.frames-section-title { font-weight: 600; margin: 12px 0 6px; font-size: 13px; }
.frames-template-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.frames-template-item { border: 1.5px solid transparent; border-radius: 8px; padding: 8px; cursor: pointer; background: #fafafa; }
.frames-template-item.active { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.frames-template-name { font-size: 13px; font-weight: 600; }
.frames-template-tier { margin-top: 4px; }
.frames-photo-row { display: flex; align-items: center; gap: 8px; }
.frames-photo-count { color: #999; font-size: 12px; }
.frames-privacy { color: var(--el-color-success); font-size: 12px; margin-top: 4px; }
.frames-copy-btn { margin-top: 6px; }
.frames-copy-result { margin-top: 8px; }
.frames-copy-text { background: #f7f7f7; border-radius: 6px; padding: 8px; font-size: 12px; white-space: pre-wrap; max-height: 140px; overflow: auto; }
.frames-locked-hint { font-size: 12px; color: var(--el-color-warning); margin-top: 6px; }
.frames-empty { padding: 40px 0; text-align: center; color: #999; }
.frames-loading { padding: 40px 0; text-align: center; color: #999; }
</style>
