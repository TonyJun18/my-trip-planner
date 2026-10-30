<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, EditPen } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import * as api from '@/api'

const { t } = useI18n()

const loading = ref(false)
const items = ref([])
const total = ref(0)

// 新增/编辑弹窗
const dialogVisible = ref(false)
const saving = ref(false)
const editId = ref('')
const form = ref({ category: 'other', content: '' })

const categoryOptions = [
  { key: 'diet', label: t('profile.categoryDiet'), icon: '🍜' },
  { key: 'pace', label: t('profile.categoryPace'), icon: '🚶' },
  { key: 'interest', label: t('profile.categoryInterest'), icon: '🎯' },
  { key: 'other', label: t('profile.categoryOther'), icon: '📌' },
]

function categoryLabel(key) {
  return categoryOptions.find((c) => c.key === key)?.label || t('profile.categoryOther')
}
function categoryIcon(key) {
  return categoryOptions.find((c) => c.key === key)?.icon || '📌'
}

async function load() {
  loading.value = true
  try {
    const data = await api.listPreferences()
    items.value = data.items || []
    total.value = data.total || 0
  } catch {
    // api 拦截器已提示
  } finally {
    loading.value = false
  }
}

function openAdd() {
  editId.value = ''
  form.value = { category: 'other', content: '' }
  dialogVisible.value = true
}

function openEdit(item) {
  editId.value = item.id
  form.value = { category: item.category || 'other', content: item.content || '' }
  dialogVisible.value = true
}

async function save() {
  const content = form.value.content.trim()
  if (!content) {
    ElMessage.warning(t('profile.contentRequired'))
    return
  }
  saving.value = true
  try {
    if (editId.value) {
      await api.updatePreference(editId.value, { category: form.value.category, content })
    } else {
      await api.addPreference({ category: form.value.category, content, source: 'user' })
    }
    ElMessage.success(t('profile.saved'))
    dialogVisible.value = false
    await load()
  } catch {
    // api 拦截器已提示
  } finally {
    saving.value = false
  }
}

async function remove(item) {
  try {
    await ElMessageBox.confirm(t('profile.deleteConfirm'), t('common.delete'), {
      type: 'warning',
      confirmButtonText: t('common.delete'),
      cancelButtonText: t('common.cancel'),
    })
  } catch {
    return
  }
  try {
    await api.deletePreference(item.id)
    ElMessage.success(t('profile.forgotten'))
    await load()
  } catch {
    // api 拦截器已提示
  }
}

onMounted(load)
</script>

<template>
  <div class="profile-view">
    <div class="profile-head">
      <div>
        <h1>{{ t('profile.title') }}</h1>
        <p class="profile-sub">{{ t('profile.subtitle') }}</p>
      </div>
      <el-button type="primary" round :icon="Plus" @click="openAdd">
        {{ t('profile.addItem') }}
      </el-button>
    </div>

    <!-- 优先级语义提示（Story 2 AC-3：本次明确需求优先于历史画像） -->
    <div class="priority-note">
      <span class="priority-icon">💡</span>
      <span>{{ t('profile.priorityHint') }}</span>
    </div>

    <el-empty v-if="!loading && items.length === 0" :description="t('profile.empty')" />

    <div v-loading="loading" class="item-list">
      <div v-for="item in items" :key="item.id" class="item-card">
        <span class="item-icon">{{ categoryIcon(item.category) }}</span>
        <div class="item-body">
          <div class="item-content">{{ item.content }}</div>
          <div class="item-meta">
            <span class="item-category">{{ categoryLabel(item.category) }}</span>
            <span v-if="item.source === 'rule'" class="item-source">{{ t('profile.sourceRule') }}</span>
            <span v-else class="item-source user">{{ t('profile.sourceUser') }}</span>
            <span class="item-time">{{ item.updated_at ? new Date(item.updated_at).toLocaleString() : '' }}</span>
          </div>
        </div>
        <div class="item-actions">
          <el-button link :icon="EditPen" @click="openEdit(item)">{{ t('common.edit') }}</el-button>
          <el-button link type="danger" :icon="Delete" @click="remove(item)">{{ t('profile.forget') }}</el-button>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editId ? t('profile.editItem') : t('profile.addItem')"
      width="420px"
      append-to-body
    >
      <el-form label-position="top">
        <el-form-item :label="t('profile.category')">
          <el-select v-model="form.category" style="width: 100%">
            <el-option
              v-for="c in categoryOptions"
              :key="c.key"
              :label="c.label"
              :value="c.key"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('profile.content')">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
            :placeholder="t('profile.contentPlaceholder')"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.profile-view {
  max-width: 760px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}
.profile-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.profile-head h1 {
  margin: 0 0 6px;
  font-size: 24px;
}
.profile-sub {
  margin: 0;
  color: var(--faint);
  font-size: 14px;
}
.priority-note {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  background: var(--bg-soft, #f7f8fa);
  border: 1px dashed var(--line, #e5e7eb);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.5;
}
.item-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 120px;
}
.item-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--card, #fff);
  border: 1px solid var(--line, #e5e7eb);
  border-radius: 12px;
  padding: 14px 16px;
}
.item-icon {
  font-size: 20px;
  flex-shrink: 0;
}
.item-body {
  flex: 1;
  min-width: 0;
}
.item-content {
  font-size: 15px;
  line-height: 1.5;
  word-break: break-word;
}
.item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--faint);
}
.item-category {
  background: var(--bg-soft, #f4f5f7);
  border-radius: 6px;
  padding: 2px 8px;
}
.item-source {
  color: #b45309;
}
.item-source.user {
  color: var(--brand, #4c6fff);
}
.item-time {
  margin-left: auto;
}
.item-actions {
  display: flex;
  flex-shrink: 0;
}
@media (max-width: 640px) {
  .item-card {
    flex-wrap: wrap;
  }
  .item-actions {
    width: 100%;
    justify-content: flex-end;
  }
  .item-time {
    display: none;
  }
}
</style>