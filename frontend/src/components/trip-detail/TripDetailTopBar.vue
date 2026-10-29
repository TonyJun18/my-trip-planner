<script setup>
import { useRouter } from 'vue-router'
import {
  MoreFilled, Star, StarFilled, Upload, Promotion, Setting, EditPen, Lock, Delete,
  ChatDotRound, Share, ArrowLeft,
} from '@element-plus/icons-vue'

// 顶栏：返回 + 编辑 / 问AI / 分享 + 更多（低频/管理/危险动作收口）
// 状态全在 orchestrator；本组件只做展示与事件上抛。
defineProps({
  sharing: { type: Boolean, default: false },
  isFavorite: { type: Boolean, default: false },
  favoriting: { type: Boolean, default: false },
  hasSharedToken: { type: Boolean, default: false },
  editToken: { type: String, default: '' },
})

const emit = defineEmits(['back', 'edit', 'ask-ai', 'share', 'more'])

const router = useRouter()

function goBack() {
  emit('back')
  router.push('/trips')
}
</script>

<template>
  <div class="topbar">
    <button class="back-btn" type="button" @click="goBack">
      <el-icon><ArrowLeft /></el-icon> {{ $t('tripDetail.backToTrips') }}
    </button>
    <div class="topbar-actions">
      <el-button @click="emit('edit')">{{ $t('tripDetail.editBasic') }}</el-button>
      <el-button type="primary" plain :loading="sharing" @click="emit('ask-ai')">
        <el-icon style="margin-right: 4px"><ChatDotRound /></el-icon>{{ $t('tripDetail.askAi') }}
      </el-button>
      <el-button type="primary" :loading="sharing" @click="emit('share')">
        <el-icon style="margin-right: 4px"><Share /></el-icon>{{ $t('tripDetail.shareTrip') }}
      </el-button>
      <el-dropdown trigger="click" @command="(cmd) => emit('more', cmd)">
        <el-button plain>
          <el-icon style="margin-right: 4px"><MoreFilled /></el-icon>{{ $t('tripDetail.more') }}
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-if="hasSharedToken" command="favorite" :icon="isFavorite ? StarFilled : Star">
              {{ isFavorite ? $t('tripDetail.favorited') : $t('tripDetail.favorite') }}
            </el-dropdown-item>
            <el-dropdown-item command="import" :icon="Upload">{{ $t('tripDetail.importContent') }}</el-dropdown-item>
            <el-dropdown-item command="gallery" :icon="Star">{{ $t('tripDetail.galleryPublish') }}</el-dropdown-item>
            <el-dropdown-item command="xhs" :icon="Promotion">{{ $t('tripDetail.shareToXhs') }}</el-dropdown-item>
            <el-dropdown-item command="share-settings" :icon="Setting" divided>{{ $t('tripDetail.shareSettings') }}</el-dropdown-item>
            <el-dropdown-item
              v-if="!editToken"
              command="share-edit"
              :icon="EditPen"
            >{{ $t('tripDetail.openEdit') }}</el-dropdown-item>
            <el-dropdown-item
              v-else
              command="revoke-edit"
              :icon="Lock"
            >{{ $t('tripDetail.revokeEdit') }}</el-dropdown-item>
            <el-dropdown-item command="delete" :icon="Delete" divided class="detail-dropdown-danger">{{ $t('tripDetail.deleteTrip') }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: var(--ink-2);
  font-weight: 500;
  padding: 8px 12px;
  border-radius: var(--radius-full);
  transition: all 0.2s;
}
.back-btn:hover {
  background: var(--fill);
  color: var(--ink);
}

@media (max-width: 640px) {
  .topbar {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  .topbar-actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 6px;
  }
  .topbar-actions :deep(.el-button) {
    margin-left: 0;
    min-height: 40px;
  }
}

@media print {
  .topbar {
    display: none !important;
  }
}
</style>