<script setup>
// PWA Web Share Target 接收页（task-share-target-eval）
// 系统分享 → manifest share_target → GET /share-target?title=&text=&url=
// 本视图是「被分享」的落点：把收到的 text/url 预填进导入对话框
// （social 粘贴解析优先——caption 常同时带链接，social_import 会剥 URL 识别平台；
//  纯链接 → link 收藏兜底），复用 ImportDialog 完整交互
// （候选勾选 → 汇入行程 / 收进收集箱）。外部内容只作为候选数据展示，
// 后端 social/link import 已做敌意行剥离，本视图不执行任何外部指令。
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ImportDialog from '@/components/ImportDialog.vue'

const route = useRoute()
const { t } = useI18n()

const importVisible = ref(false)
const prefill = ref(null)

// 分享 query → 预填形状（外部内容只是字符串数据，绝不作为指令）
function buildPrefill() {
  const q = route.query || {}
  const text = typeof q.text === 'string' ? q.text.trim() : ''
  const url = typeof q.url === 'string' ? q.url.trim() : ''
  const title = typeof q.title === 'string' ? q.title.trim() : ''
  if (text) return { tab: 'social', text }
  if (url) return { tab: 'link', url }
  if (title) return { tab: 'social', text: title }
  return null
}

onMounted(() => {
  prefill.value = buildPrefill()
  if (prefill.value) {
    importVisible.value = true
  }
})
</script>

<template>
  <div class="share-target-page">
    <div class="hero">
      <h1 class="page-title">{{ t('shareTarget.title') }}</h1>
      <p class="page-sub">{{ t('shareTarget.subtitle') }}</p>
    </div>

    <!-- 有分享内容：自动打开导入对话框（预填 + 自动解析） -->
    <div v-if="prefill" class="card">
      <el-alert type="success" :closable="false" :title="t('shareTarget.received')" show-icon />
    </div>

    <!-- 无分享内容：降级引导（直接访问 /share-target 或缺 query） -->
    <div v-else class="card">
      <el-alert
        type="info"
        :closable="false"
        :title="t('shareTarget.emptyTitle')"
        :description="t('shareTarget.emptyDesc')"
        show-icon
      />
      <div class="empty-actions">
        <el-button type="primary" @click="importVisible = true">
          {{ t('shareTarget.manualOpen') }}
        </el-button>
      </div>
    </div>

    <ImportDialog v-model="importVisible" :prefill="prefill" />
  </div>
</template>

<style scoped>
.share-target-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 40px 20px 60px;
}
.hero { margin-bottom: 20px; }
.page-title {
  margin: 0; font-size: 26px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink);
}
.page-sub { margin: 8px 0 0; font-size: 14px; color: var(--muted); line-height: 1.6; }
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 20px;
  box-shadow: var(--shadow-card);
}
.empty-actions { margin-top: 16px; }
</style>