<script setup>
/**
 * 打包清单（task-packing-expense · 最小版一）
 *
 * 设计哲学（对齐项目「零凭证最小版」路线）：
 * - **纯前端 + localStorage**：无数据库、无 API、无凭证——零后端成本；
 * - **按 tripId 隔离**：key = `packing:{tripId}`，不同行程互不串扰；
 * - **预设模板 + 自定义**：按出行类型给基础清单（默认/亲子/商务/海滩/徒步），
 *   可增删改条目、勾选完成，完全自由；
 * - **行程无关的纯本地体验**：单人可用，不做多人同步（那是后端功能）。
 *
 * 竞品基准（MonkeyTravel 行中三件套之一）：打包清单是「行中管理一体化」2026
 * 分水岭的最轻量入口（Stippl 免费档标配、Wanderlog 无预算无分摊），
 * 纯前端实现即可达感知价值，费用分摊留待后端预算 schema 扩展。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox, ElMessage } from 'element-plus'

const props = defineProps({
  tripId: { type: [String, Number], required: true },
  // 可选：从行程数据推断出行类型（默认/亲子/商务…），用于模板推荐
  tripType: { type: String, default: '' },
})

const { t } = useI18n()

// ── 数据模型 ─────────────────────────────────────────────
// items: [{ id, label, done }]
const items = ref([])
const newItemLabel = ref('')
const storageKey = computed(() => `packing:${props.tripId}`)
const restored = ref(false)

// 预设模板（按键分组，随 locale 显示；label 用 t() 实时取）
const TEMPLATES = () => ({
  general: [
    'packing.general.docs', 'packing.general.phone', 'packing.general.charger',
    'packing.general.powerbank', 'packing.general.id', 'packing.general.cash',
    'packing.general.meds', 'packing.general.clothes', 'packing.general.shoes',
    'packing.general.toiletries', 'packing.general.umbrella', 'packing.general.snacks',
  ],
  family: [
    'packing.general.docs', 'packing.general.meds', 'packing.family.snacks',
    'packing.family.baby', 'packing.family.toys', 'packing.family.wipes',
    'packing.family.change', 'packing.family.stroller', 'packing.family.bottle',
  ],
  business: [
    'packing.general.docs', 'packing.general.phone', 'packing.general.charger',
    'packing.business.laptop', 'packing.business.cable', 'packing.business.namecard',
    'packing.business.formal', 'packing.business.notebook', 'packing.business.powerbank',
  ],
  beach: [
    'packing.general.docs', 'packing.beach.sunscreen', 'packing.beach.swimsuit',
    'packing.beach.towel', 'packing.beach.hat', 'packing.beach.sunglasses',
    'packing.beach.sandals', 'packing.beach.water', 'packing.beach.drybag',
  ],
  hiking: [
    'packing.general.docs', 'packing.hiking.boots', 'packing.hiking.backpack',
    'packing.hiking.water', 'packing.hiking.snacks', 'packing.hiking.firstaid',
    'packing.hiking.sunblock', 'packing.hiking.rain', 'packing.hiking.powerbank',
  ],
})

// 出行类型 → 模板键映射
const typeToTemplate = {
  family: 'family',
  business: 'business',
  honeymoon: 'beach',
  visiting: 'general',
  leisure: 'general',
}

// ── 持久化 ───────────────────────────────────────────────
function load() {
  try {
    const raw = localStorage.getItem(storageKey.value)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed.items)) items.value = parsed.items
    }
  } catch (e) {
    // localStorage 不可用（隐私模式）→ 静默降级为内存态
  }
  restored.value = true
}

function save() {
  try {
    localStorage.setItem(storageKey.value, JSON.stringify({ items: items.value }))
  } catch (e) {
    // 静默：写不进去就当内存态用
  }
}

watch(items, save, { deep: true })
watch(storageKey, () => { load() })
onMounted(load)

// ── 操作 ─────────────────────────────────────────────────
function addItem() {
  const label = newItemLabel.value.trim()
  if (!label) return
  items.value.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, label, done: false })
  newItemLabel.value = ''
}

function removeItem(id) {
  items.value = items.value.filter((it) => it.id !== id)
}

function toggleItem(id) {
  const it = items.value.find((i) => i.id === id)
  if (it) it.done = !it.done
}

function clearDone() {
  ElMessageBox.confirm(t('packing.clearConfirm'), t('packing.title'), {
    confirmButtonText: t('packing.clearDone'),
    cancelButtonText: t('common.cancel'),
    type: 'warning',
  }).then(() => {
    items.value = items.value.filter((i) => !i.done)
    ElMessage.success(t('packing.cleared'))
  }).catch(() => {})
}

function applyTemplate(templateKey) {
  if (!templateKey) return
  const template = TEMPLATES()[templateKey]
  if (!template) return
  // 已有同 key 条目则跳过（幂等，不重复添加）
  const existing = new Set(items.value.map((i) => i.label))
  for (const key of template) {
    if (!existing.has(key)) {
      items.value.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, label: key, done: false })
    }
  }
  ElMessage.success(t('packing.templateApplied'))
}

// 推荐模板（基于 tripType，可选）
const recommendedTemplate = computed(() => {
  const key = typeToTemplate[props.tripType] || 'general'
  return key
})

const doneCount = computed(() => items.value.filter((i) => i.done).length)
const progress = computed(() => (items.value.length ? Math.round((doneCount.value / items.value.length) * 100) : 0))
const hasItems = computed(() => items.value.length > 0)
</script>

<template>
  <div class="packing-card">
    <div class="packing-head">
      <span class="packing-title">
        <el-icon style="margin-right: 6px"><Suitcase /></el-icon>
        {{ t('packing.title') }}
      </span>
      <span v-if="hasItems" class="packing-progress">{{ doneCount }}/{{ items.length }} · {{ progress }}%</span>
    </div>

    <!-- 进度条 -->
    <div v-if="hasItems" class="packing-bar">
      <div class="packing-bar-fill" :style="{ width: progress + '%' }"></div>
    </div>

    <!-- 模板快捷添加 -->
    <div class="packing-templates">
      <span class="packing-tpl-label">{{ t('packing.templateLabel') }}</span>
      <el-button size="small" text type="primary" @click="applyTemplate('general')">{{ t('packing.tplGeneral') }}</el-button>
      <el-button size="small" text type="primary" @click="applyTemplate('family')">{{ t('packing.tplFamily') }}</el-button>
      <el-button size="small" text type="primary" @click="applyTemplate('business')">{{ t('packing.tplBusiness') }}</el-button>
      <el-button size="small" text type="primary" @click="applyTemplate('beach')">{{ t('packing.tplBeach') }}</el-button>
      <el-button size="small" text type="primary" @click="applyTemplate('hiking')">{{ t('packing.tplHiking') }}</el-button>
    </div>

    <!-- 条目列表 -->
    <ul v-if="hasItems" class="packing-list">
      <li v-for="it in items" :key="it.id" class="packing-item" :class="{ done: it.done }">
        <el-checkbox :model-value="it.done" @change="toggleItem(it.id)" size="small" />
        <span class="packing-label">{{ t(it.label) }}</span>
        <el-button size="small" text class="packing-del" @click="removeItem(it.id)">
          <el-icon><Close /></el-icon>
        </el-button>
      </li>
    </ul>
    <div v-else class="packing-empty">{{ t('packing.empty') }}</div>

    <!-- 自定义添加 -->
    <div class="packing-add">
      <el-input
        v-model="newItemLabel"
        :placeholder="t('packing.addPlaceholder')"
        size="small"
        @keyup.enter="addItem"
      >
        <template #append>
          <el-button @click="addItem">{{ t('packing.add') }}</el-button>
        </template>
      </el-input>
    </div>

    <!-- 清空已完成 -->
    <div v-if="doneCount > 0" class="packing-clear">
      <el-button size="small" text type="warning" @click="clearDone">{{ t('packing.clearDone') }}</el-button>
    </div>
  </div>
</template>

<style scoped>
.packing-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 16px;
}
.packing-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.packing-title {
  font-size: 14px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  color: #1f2937;
}
.packing-progress {
  font-size: 12px;
  color: #6b7280;
}
.packing-bar {
  height: 6px;
  background: #f3f4f6;
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 10px;
}
.packing-bar-fill {
  height: 100%;
  background: #10b981;
  border-radius: 999px;
  transition: width 0.3s;
}
.packing-templates {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 10px;
}
.packing-tpl-label {
  font-size: 12px;
  color: #9ca3af;
  margin-right: 4px;
}
.packing-list {
  margin: 0 0 10px;
  padding: 0;
  list-style: none;
  max-height: 260px;
  overflow-y: auto;
}
.packing-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed #f3f4f6;
}
.packing-item.done .packing-label {
  text-decoration: line-through;
  color: #9ca3af;
}
.packing-label {
  flex: 1;
  font-size: 13px;
  color: #374151;
}
.packing-del {
  flex-shrink: 0;
}
.packing-empty {
  color: #9ca3af;
  font-size: 13px;
  padding: 8px 0;
}
.packing-add {
  display: flex;
  gap: 8px;
}
.packing-clear {
  margin-top: 6px;
  text-align: right;
}
</style>