<template>
  <div
    class="collapsible-section"
    :class="{ collapsed: isCollapsed, plain }"
  >
    <button
      class="cs-head"
      type="button"
      :aria-expanded="!isCollapsed"
      @click="toggle"
    >
      <span class="cs-title">
        <el-icon v-if="icon" class="cs-icon" :size="15"><component :is="icon" /></el-icon>
        <slot name="title">{{ title }}</slot>
      </span>
      <span class="cs-right">
        <slot name="extra" />
        <el-icon class="cs-chevron" :class="{ open: !isCollapsed }"><ArrowDown /></el-icon>
      </span>
    </button>
    <el-collapse-transition>
      <div v-show="!isCollapsed" class="cs-body">
        <slot />
      </div>
    </el-collapse-transition>
  </div>
</template>

<script setup>
import { ArrowDown } from '@element-plus/icons-vue'
import { computed, onMounted, ref, watch } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  icon: { type: [String, Object], default: null },
  // 默认展开还是收起
  defaultOpen: { type: Boolean, default: false },
  // 父组件强制展开（导出/打印前）
  forceOpen: { type: Boolean, default: false },
  // plain：无边框容器，仅折叠头（子内容保留自身卡片外观）
  plain: { type: Boolean, default: false },
  // localStorage 记忆 key（含 trip_id 可做到每次程独立记忆）
  storageKey: { type: String, default: '' },
})

const isCollapsed = ref(!props.defaultOpen)

// forceOpen 优先级高于用户手动折叠状态
const effectiveOpen = computed(() => {
  if (props.forceOpen) return true
  return !isCollapsed.value
})

onMounted(() => {
  if (props.forceOpen) return
  if (!props.storageKey) return
  try {
    const saved = localStorage.getItem(props.storageKey)
    if (saved != null) isCollapsed.value = saved === '1'
  } catch {
    /* localStorage 不可用时降级默认态 */
  }
})

function toggle() {
  if (props.forceOpen) return
  isCollapsed.value = !isCollapsed.value
  if (!props.storageKey) return
  try {
    localStorage.setItem(props.storageKey, isCollapsed.value ? '1' : '0')
  } catch {
    /* 静默 */
  }
}

// 供父组件强制展开（例如导出前）
watch(
  () => props.defaultOpen,
  (v) => {
    isCollapsed.value = !v
  },
)
defineExpose({ expand: () => { isCollapsed.value = false } })
</script>

<style scoped>
.collapsible-section {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  margin-bottom: 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
  overflow: hidden;
}
.cs-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 13px 16px;
  background: transparent;
  border: none;
  cursor: pointer;
  font: inherit;
  color: var(--ink);
  text-align: left;
  transition: background 0.15s;
  -webkit-tap-highlight-color: transparent;
}
.cs-head:hover { background: var(--fill); }
.cs-head:focus-visible { outline: 2px solid var(--brand); outline-offset: -2px; }
.cs-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14.5px;
  font-weight: 600;
  min-width: 0;
}
.cs-icon { color: var(--muted); flex-shrink: 0; }
.cs-right { display: inline-flex; align-items: center; gap: 8px; flex-shrink: 0; margin-left: auto; }
.cs-chevron {
  color: var(--faint);
  font-size: 14px;
  transition: transform 0.2s;
}
.cs-chevron.open { transform: rotate(180deg); }
.cs-body { border-top: 1px solid var(--line); padding: 14px 16px; }

/* plain：无边框容器模式，子内容保留自身卡片外观 */
.collapsible-section.plain {
  background: transparent;
  border: none;
  border-radius: 0;
  box-shadow: none;
  margin-bottom: 4px;
  overflow: visible;
}
.plain .cs-head { padding: 10px 2px; }
.plain .cs-head:hover { background: transparent; }
.plain .cs-title { font-size: 14px; }
.plain .cs-body {
  border-top: none;
  padding: 0 0 14px;
}
</style>