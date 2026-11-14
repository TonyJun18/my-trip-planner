<script setup>
// 单日导航按钮（task-day-map-deeplink，2026-11-14）
//
// 复用方：TripDetailDayCard 日头操作区 + ShareView 每日行程头（同一组件自动生效）。
// 行为：
// - ≤9 站（Google waypoints 上限）：下拉选 Google / Apple / 高德，直接打开全天路线。
// - >9 站：降级为复制逐站导航链接列表（copyList 语义），并 toast 提示。
// - 全部站点缺坐标：不渲染按钮（避免死链）。
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Guide } from '@element-plus/icons-vue'
import { dayMapLinks } from '@/utils/mapLinks'

const props = defineProps({
  stops: { type: Array, default: () => [] },
})

const { t } = useI18n()

const links = computed(() => dayMapLinks(props.stops))
const hasAny = computed(() => links.value.url != null || links.value.list.length > 0)

function openNav(provider) {
  const { url, list } = links.value
  if (url) {
    window.open(url, '_blank', 'noopener')
    return
  }
  if (list.length > 1) {
    // 超 9 站：复制逐站链接列表；剪贴板不可用时退化为打开第一站
    if (navigator.clipboard?.writeText) {
      navigator.clipboard
        .writeText(list.join('\n'))
        .then(() => ElMessage.success(t('mapNav.copied', { n: list.length })))
        .catch(() => window.open(list[0], '_blank', 'noopener'))
    } else {
      window.open(list[0], '_blank', 'noopener')
    }
    return
  }
  if (list.length === 1) window.open(list[0], '_blank', 'noopener')
}
</script>

<template>
  <el-dropdown v-if="hasAny" trigger="click" @command="openNav">
    <el-button size="small" plain circle :aria-label="t('mapNav.buttonHint')">
      <el-icon><Guide /></el-icon>
    </el-button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="google">Google Maps</el-dropdown-item>
        <el-dropdown-item command="apple">Apple Maps</el-dropdown-item>
        <el-dropdown-item command="amap">{{ t('mapNav.amap') }}</el-dropdown-item>
        <el-dropdown-item
          v-if="links.list.length > 1"
          divided
          disabled
        >
          {{ t('mapNav.tooMany', { n: links.list.length }) }}
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>