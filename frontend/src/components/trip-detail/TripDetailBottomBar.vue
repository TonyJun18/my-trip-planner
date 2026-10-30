<script setup>
import { Plus, Calendar, Document, Picture, Download, Printer } from '@element-plus/icons-vue'

// 底部操作栏：加天 / 批量生成 / 导出 split（PDF 主按钮 + 下拉）
defineProps({
  exporting: { type: Boolean, default: false },
})
const emit = defineEmits(['add-day', 'gen-days', 'export', 'export-cmd'])
</script>

<template>
  <div class="bottom-bar">
    <el-button @click="emit('add-day')"><el-icon style="margin-right: 4px"><Plus /></el-icon>{{ $t('tripDetail.addDay') }}</el-button>
    <el-button @click="emit('gen-days')"><el-icon style="margin-right: 4px"><Calendar /></el-icon>{{ $t('tripDetail.genDays') }}</el-button>
    <el-dropdown split-button type="primary" :loading="exporting" @click="emit('export')" @command="(cmd) => emit('export-cmd', cmd)">
      <el-icon style="margin-right: 4px"><Document /></el-icon>{{ $t('tripDetail.exportPdf') }}
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="image" :icon="Picture">{{ $t('tripDetail.exportImage') }}</el-dropdown-item>
          <el-dropdown-item command="json" :icon="Download">{{ $t('tripDetail.exportJson') }}</el-dropdown-item>
          <el-dropdown-item command="print" :icon="Printer">{{ $t('tripDetail.exportPrint') }}</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<style scoped>
.bottom-bar {
  display: flex;
  gap: 12px;
  margin-top: 20px;
  padding: 8px 0 20px;
  flex-wrap: wrap;
}
@media (max-width: 640px) {
  .bottom-bar { gap: 8px; }
  .bottom-bar > :deep(.el-button) { flex: 1 1 calc(50% - 4px); margin-left: 0; min-height: 44px; }
  .bottom-bar > :deep(.el-dropdown) { flex: 1 1 100%; }
  .bottom-bar > :deep(.el-dropdown) :deep(.el-button-group) { width: 100%; }
}
</style>