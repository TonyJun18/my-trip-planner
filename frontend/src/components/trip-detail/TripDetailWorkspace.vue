<script setup>
import { Grid, Tools } from '@element-plus/icons-vue'

/**
 * 次级内容工作台（收纳 10 个工具箱面板）。
 *
 * 为什么要它：旧版把 AI 修订 / PlanB / 时间校验 / 质检 / 预订 / 追踪 / 护照 /
 * 故事卡 / 行李 / 交通服务 / 酒店 / 事件流 平铺在同一条滚动流里（12 个折叠头 ≈
 * 400px 纯标题噪音），核心内容（地图 + 逐日行程）被次级功能淹没。
 *
 * 设计取舍：
 * - 只收纳**次级**面板；地图与逐日行程永远在首屏主路径上，不进 tab（这是与
 *   上一版 4-tab 方案最大的区别——那版把行程塞进 tab，反而埋了主路径）
 * - tab 按「时机」给，不是按功能堆给；每个 tab 带徽标，避免「收起来就找不到」
 * - 「全部工具」开关常驻：默认干净，需要时一键看到全部（导出/打印自动全开）
 */
defineProps({
  tabs: { type: Array, default: () => [] }, // [{ key, label, badge }]
  modelValue: { type: String, default: '' },
  showAll: { type: Boolean, default: false },
  title: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'toggle-all'])

function select(key) {
  emit('update:modelValue', key)
}
</script>

<template>
  <section class="workspace" :class="{ 'is-all': showAll }">
    <div class="ws-head">
      <div class="ws-tabs" role="tablist" :aria-label="title">
        <template v-if="tabs.length > 1">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="ws-tab"
            :class="{ active: !showAll && tab.key === modelValue }"
            type="button"
            role="tab"
            :aria-selected="!showAll && tab.key === modelValue"
            @click="select(tab.key)"
          >
            <span class="ws-tab-label">{{ tab.label }}</span>
            <span v-if="tab.badge" class="ws-tab-badge">{{ tab.badge }}</span>
          </button>
        </template>
        <template v-else>
          <div class="ws-title">
            <el-icon class="ws-title-icon"><Tools /></el-icon>
            <span>{{ showAll ? $t('tripDetail.toolsAll') : (tabs[0]?.label || title) }}</span>
            <span v-if="tabs[0]?.badge && !showAll" class="ws-tab-badge">{{ tabs[0].badge }}</span>
          </div>
        </template>

        <button
          class="ws-all"
          type="button"
          :aria-pressed="showAll"
          @click="emit('toggle-all')"
        >
          <el-icon><Grid /></el-icon>
          {{ showAll ? $t('tripDetail.toolsCategorized') : $t('tripDetail.toolsAll') }}
        </button>
      </div>
    </div>

    <div class="ws-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.workspace {
  margin-top: 18px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(0, 0, 0, 0.04));
  overflow: hidden;
}

.ws-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, var(--fill), transparent 90%);
}

.ws-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.ws-tabs::-webkit-scrollbar { display: none; }

.ws-tab {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 12px;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: background 0.18s, color 0.18s, border-color 0.18s;
  -webkit-tap-highlight-color: transparent;
}
.ws-tab:hover { background: var(--card); color: var(--ink); border-color: var(--line); }
.ws-tab:focus-visible { outline: 2px solid var(--brand); outline-offset: 1px; }
.ws-tab.active {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: rgba(255, 56, 92, 0.22);
}
.ws-tab-badge {
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1;
  padding: 2px 6px;
  border-radius: var(--radius-full);
  background: rgba(0, 0, 0, 0.06);
  color: var(--muted);
}
.ws-tab.active .ws-tab-badge { background: rgba(255, 56, 92, 0.14); color: var(--brand); }

.ws-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
  padding-left: 2px;
}
.ws-title-icon { color: var(--muted); font-size: 15px; }

.ws-all {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: color 0.18s, border-color 0.18s;
}
.ws-all:hover { color: var(--brand); border-color: var(--brand); }
.ws-all:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.workspace.is-all .ws-all { color: var(--brand); border-color: rgba(255, 56, 92, 0.35); background: var(--brand-soft); }

.ws-body { padding: 6px 14px 10px; }

@media (max-width: 640px) {
  .ws-head { padding: 8px 10px; }
  .ws-body { padding: 4px 10px 8px; }
  .ws-tab { height: 34px; }
}
</style>
