<template>
  <div class="story-generator">
    <div class="story-header">
      <span class="story-title">📸 {{ t('story.panelTitle') }}</span>
      <el-tooltip :content="t('story.hint')" placement="top">
        <el-icon class="story-hint-icon"><QuestionFilled /></el-icon>
      </el-tooltip>
    </div>

    <!-- 渠道选择 -->
    <el-radio-group v-model="channel" size="small" class="story-channels" @change="generate">
      <el-radio-button value="xhs">{{ t('story.channel.xhs') }}</el-radio-button>
      <el-radio-button value="moments">{{ t('story.channel.moments') }}</el-radio-button>
      <el-radio-button value="poster">{{ t('story.channel.poster') }}</el-radio-button>
    </el-radio-group>

    <!-- 空态引导 -->
    <div v-if="empty" class="story-empty">
      {{ t('story.empty') }}
    </div>

    <!-- 加载中 -->
    <div v-else-if="loading" class="story-loading">{{ t('story.generating') }}</div>

    <!-- 生成结果 -->
    <div v-else-if="story" class="story-result">
      <div class="story-source-label">
        <el-tag size="small" :type="story.source === 'llm' ? 'primary' : 'info'" effect="light">
          {{ story.source === 'llm' ? t('story.source.llm') : t('story.source.template') }}
        </el-tag>
      </div>

      <!-- poster 渠道：HTML 长图卡片预览（可直接浏览器截图保存） -->
      <div v-if="channel === 'poster'" class="story-poster" ref="posterRef">
        <div class="poster-bg">
          <div class="poster-head">
            <div class="poster-title">{{ story.title }}</div>
            <div class="poster-dest">{{ story.stats?.destination }}</div>
          </div>
          <div class="poster-body">
            <div v-if="story.stats" class="poster-stats">
              <div class="poster-stat">
                <div class="poster-stat-value">{{ story.stats.days }}</div>
                <div class="poster-stat-label">{{ t('poster.days') }}</div>
              </div>
              <div class="poster-stat">
                <div class="poster-stat-value">{{ story.stats.stops }}</div>
                <div class="poster-stat-label">{{ t('poster.stops') }}</div>
              </div>
              <div class="poster-stat">
                <div class="poster-stat-value">{{ story.stats.checked }}</div>
                <div class="poster-stat-label">{{ t('poster.checked') }}</div>
              </div>
              <div class="poster-stat">
                <div class="poster-stat-value">{{ story.stats.expense_total }}</div>
                <div class="poster-stat-label">{{ t('poster.expense') }}</div>
              </div>
            </div>
            <div v-if="story.badges && story.badges.length" class="poster-badges">
              <span v-for="b in story.badges" :key="b" class="poster-badge">{{ b }}</span>
            </div>
            <div class="poster-copy">{{ story.body }}</div>
          </div>
          <div class="poster-foot">Powered by my-trip-planner</div>
        </div>
      </div>
      <div v-else class="story-text-preview">
        <div class="story-title">{{ story.title }}</div>
        <div class="story-body">{{ story.body }}</div>
        <div v-if="story.topics && story.topics.length" class="story-topics">
          <span v-for="tp in story.topics" :key="tp" class="story-topic">#{{ tp }}</span>
        </div>
      </div>

      <div class="story-actions">
        <el-button size="small" type="primary" @click="copyStory">
          <el-icon><CopyDocument /></el-icon>&nbsp;{{ t('story.copy') }}
        </el-button>
        <el-button size="small" @click="generate">{{ t('story.regenerate') }}</el-button>
      </div>
      <div v-if="channel === 'poster'" class="poster-hint">
        {{ t('poster.hint') }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { CopyDocument, QuestionFilled } from '@element-plus/icons-vue'
import { generateStory } from '../api'

const props = defineProps({
  tripId: { type: String, required: true },
})

const { t } = useI18n()
const channel = ref('xhs')
const story = ref(null)
const loading = ref(false)
const empty = ref(false)

async function generate() {
  loading.value = true
  empty.value = false
  try {
    const data = await generateStory(props.tripId, channel.value)
    if (data.empty) {
      empty.value = true
      story.value = null
    } else {
      story.value = data
    }
  } catch (e) {
    ElMessage.warning(t('story.generateFailed'))
  } finally {
    loading.value = false
  }
}

function fullText() {
  if (!story.value) return ''
  const topics = (story.value.topics || []).map((x) => `#${x}`).join(' ')
  return `${story.value.title}\n\n${story.value.body}${topics ? `\n\n${topics}` : ''}`
}

async function copyStory() {
  const text = fullText()
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(t('story.copied'))
  } catch {
    ElMessage.warning(t('story.copyFallback'))
  }
}

onMounted(generate)
</script>

<style scoped>
.story-generator {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px;
}
.story-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}
.story-title {
  font-weight: 600;
  font-size: 15px;
}
.story-hint-icon {
  color: var(--el-text-color-secondary);
  cursor: help;
}
.story-channels {
  margin-bottom: 12px;
}
.story-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  padding: 10px 0;
}
.story-loading {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  padding: 10px 0;
}
.story-result {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.story-source-label {
  display: flex;
  justify-content: flex-end;
}
.story-title {
  font-weight: 600;
  font-size: 16px;
}
.story-body {
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.story-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 13px;
  color: var(--el-color-primary);
}
.story-actions {
  display: flex;
  gap: 8px;
}
.poster-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 8px;
}
.story-text-preview {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.story-poster {
  width: 100%;
  max-width: 340px;
  margin: 0 auto;
}
.poster-bg {
  background: linear-gradient(160deg, #1f2937 0%, #111827 100%);
  border-radius: 12px;
  padding: 18px 16px;
  color: #fff;
  width: 100%;
  min-height: 360px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.poster-head .poster-title {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.3;
}
.poster-dest {
  font-size: 13px;
  opacity: 0.8;
  margin-top: 4px;
}
.poster-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 10px 8px;
}
.poster-stat {
  text-align: center;
}
.poster-stat-value {
  font-size: 18px;
  font-weight: 700;
}
.poster-stat-label {
  font-size: 11px;
  opacity: 0.7;
  margin-top: 2px;
}
.poster-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.poster-badge {
  font-size: 12px;
  background: rgba(99, 102, 241, 0.3);
  border: 1px solid rgba(99, 102, 241, 0.5);
  border-radius: 999px;
  padding: 3px 10px;
}
.poster-copy {
  font-size: 13px;
  line-height: 1.6;
  opacity: 0.95;
  white-space: pre-wrap;
  color: #fff;
}
.poster-foot {
  margin-top: auto;
  font-size: 10px;
  text-align: center;
  opacity: 0.4;
}
</style>