<script setup>
import {
  MoreFilled, Star, StarFilled, Upload, Promotion, Setting, EditPen, Lock, Delete, MagicStick,
  Document, Picture, Download, Printer,
} from '@element-plus/icons-vue'

// 详情页「更多」菜单：低频 / 管理 / 危险动作统一收口（顶栏最多 3 个主操作，其余都进这里）。
// 纯展示组件：不持有状态，命令原样上抛给 orchestrator。
defineProps({
  isFavorite: { type: Boolean, default: false },
  favoriting: { type: Boolean, default: false },
  hasSharedToken: { type: Boolean, default: false },
  editToken: { type: String, default: '' },
  // 非规划时机：「调整行程」快捷入口（主路径上的 AI 调整卡片常驻，这里是顶栏直达）
  showAdjust: { type: Boolean, default: false },
  // 导出：默认四项全给；finished 时机页头已有「导出 PDF」主按钮，这里只留长图/JSON/打印，避免同屏两份 PDF
  showExport: { type: Boolean, default: true },
  showExportPdf: { type: Boolean, default: true },
  // 是否显示文字（默认仅图标，节省顶栏宽度）
  withLabel: { type: Boolean, default: false },
})

const emit = defineEmits(['command'])
</script>

<template>
  <el-dropdown trigger="click" @command="(cmd) => emit('command', cmd)">
    <button class="more-trigger" type="button" :aria-label="$t('tripDetail.more')">
      <el-icon><MoreFilled /></el-icon>
      <span v-if="withLabel" class="more-label">{{ $t('tripDetail.more') }}</span>
    </button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item v-if="showAdjust" command="adjust" :icon="MagicStick">
          {{ $t('tripDetail.quickRevise') }}
        </el-dropdown-item>
        <el-dropdown-item
          v-if="hasSharedToken"
          command="favorite"
          :icon="isFavorite ? StarFilled : Star"
          :disabled="favoriting"
        >{{ isFavorite ? $t('tripDetail.favorited') : $t('tripDetail.favorite') }}</el-dropdown-item>
        <el-dropdown-item command="import" :icon="Upload">{{ $t('tripDetail.importContent') }}</el-dropdown-item>
        <!-- 导出：原底部操作条的 split 下拉搬到这里（页面级动作归页头，别再单起一条底栏切断版面） -->
        <template v-if="showExport">
          <el-dropdown-item v-if="showExportPdf" command="export-pdf" :icon="Document">
            {{ $t('tripDetail.exportPdf') }}
          </el-dropdown-item>
          <el-dropdown-item command="export-image" :icon="Picture">{{ $t('tripDetail.exportImage') }}</el-dropdown-item>
          <el-dropdown-item command="export-json" :icon="Download">{{ $t('tripDetail.exportJson') }}</el-dropdown-item>
          <el-dropdown-item command="export-print" :icon="Printer">{{ $t('tripDetail.exportPrint') }}</el-dropdown-item>
        </template>
        <el-dropdown-item command="gallery" :icon="Star">{{ $t('tripDetail.galleryPublish') }}</el-dropdown-item>
        <el-dropdown-item command="xhs" :icon="Promotion">{{ $t('tripDetail.shareToXhs') }}</el-dropdown-item>
        <el-dropdown-item command="share-settings" :icon="Setting" divided>{{ $t('tripDetail.shareSettings') }}</el-dropdown-item>
        <el-dropdown-item v-if="!editToken" command="share-edit" :icon="EditPen">{{ $t('tripDetail.openEdit') }}</el-dropdown-item>
        <el-dropdown-item v-else command="revoke-edit" :icon="Lock">{{ $t('tripDetail.revokeEdit') }}</el-dropdown-item>
        <el-dropdown-item command="delete" :icon="Delete" divided class="detail-dropdown-danger">{{ $t('tripDetail.deleteTrip') }}</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.more-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 34px;
  min-width: 34px;
  padding: 0 8px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-full);
  color: var(--ink-2);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  transition: border-color 0.18s, color 0.18s, background 0.18s;
}
.more-trigger:hover { border-color: var(--brand); color: var(--brand); background: var(--brand-soft); }
.more-trigger:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.more-label { line-height: 1; }

@media (max-width: 640px) {
  .more-trigger { min-width: 40px; height: 40px; }
}
</style>
