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
      <div class="story-title">{{ story.title }}</div>
      <div class="story-body">{{ story.body }}</div>
      <div v-if="story.topics && story.topics.length" class="story-topics">
        <span v-for="tp in story.topics" :key="tp" class="story-topic">#{{ tp }}</span>
      </div>
      <div class="story-actions">
        <el-button size="small" type="primary" @click="copyStory">
          <el-icon><CopyDocument /></el-icon>&nbsp;{{ t('story.copy') }}
        </el-button>
        <el-button size="small" @click="generate">{{ t('story.regenerate') }}</el-button>
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
</style>