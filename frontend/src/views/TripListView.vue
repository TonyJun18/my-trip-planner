<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import * as api from '@/api'

const router = useRouter()
const { t } = useI18n()

const loading = ref(false)
const trips = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(9)

// ── 手动创建行程（PATCH/POST /trips 后端已支持，前端补入口） ──
const createVisible = ref(false)
const creating = ref(false)
const createForm = ref({ title: '', destination: '', start_date: '', end_date: '', travelers: 1, budget: 3000 })

function openCreate() {
  createForm.value = { title: '', destination: '', start_date: '', end_date: '', travelers: 1, budget: 3000 }
  createVisible.value = true
}
async function submitCreate() {
  if (!createForm.value.title.trim() || !createForm.value.destination.trim() || !createForm.value.start_date || !createForm.value.end_date) {
    ElMessage.warning(t('tripList.fillRequired'))
    return
  }
  creating.value = true
  try {
    const trip = await api.createTrip(createForm.value)
    ElMessage.success(t('tripList.tripCreated'))
    createVisible.value = false
    router.push(`/trips/${trip.id}`)
  } catch {
    // api 拦截器已提示
  } finally {
    creating.value = false
  }
}

const statusMap = computed(() => ({
  draft: { label: t('tripList.statusDraft'), type: 'info' },
  planning: { label: t('tripList.statusPlanning'), type: 'warning' },
  confirmed: { label: t('tripList.statusConfirmed'), type: 'success' },
  archived: { label: t('tripList.statusArchived'), type: 'info' },
}))

// 目的地 → 氛围渐变（按城市名哈希取色，避免每次不同）
const gradients = [
  'linear-gradient(135deg, #ff9a9e 0%, #fad0c4 100%)',
  'linear-gradient(135deg, #a1c4fd 0%, #c2e9fb 100%)',
  'linear-gradient(135deg, #fbc2eb 0%, #a6c1ee 100%)',
  'linear-gradient(135deg, #fdcbf1 0%, #e6dee9 100%)',
  'linear-gradient(135deg, #f6d365 0%, #fda085 100%)',
  'linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%)',
  'linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%)',
  'linear-gradient(135deg, #fddb92 0%, #e6b0f4 100%)',
  'linear-gradient(135deg, #96fbc4 0%, #f9f586 100%)',
]
function gradientOf(dest) {
  if (!dest) return gradients[0]
  let h = 0
  for (const ch of dest) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return gradients[h % gradients.length]
}

const tripCountLabel = computed(() => (total.value ? t('tripList.totalTrips', { count: total.value }) : t('tripList.noTrips')))

async function load() {
  loading.value = true
  try {
    const data = await api.listTrips({ offset: (page.value - 1) * pageSize.value, limit: pageSize.value })
    trips.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onPageChange(p) {
  page.value = p
  load()
}

function dateRange(trip) {
  if (!trip.start_date && !trip.end_date) return t('tripList.dateUndecided')
  return t('tripList.dateRange', { start: trip.start_date || '?', end: trip.end_date || '?' })
}

function dayCount(t) {
  return t.days?.length || 0
}

async function removeTrip(trip) {
  try {
    await ElMessageBox.confirm(t('tripList.deleteConfirmMsg', { title: trip.title }), t('tripList.deleteConfirmTitle'), {
      type: 'warning',
      confirmButtonText: t('common.delete'),
      cancelButtonText: t('common.cancel'),
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  await api.deleteTrip(trip.id)
  ElMessage.success(t('tripList.deleted'))
  load()
}

onMounted(load)
</script>

<template>
  <div>
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h2 class="page-title">{{ t('tripList.title') }}</h2>
        <p class="page-sub">
          <template v-if="trips.length">{{ t('tripList.subHas') }}</template>
          <template v-else>{{ t('tripList.subEmpty') }}</template>
        </p>
      </div>
      <button class="btn-primary" @click="router.push('/plan')">
        <el-icon style="margin-right: 6px"><MagicStick /></el-icon>{{ t('tripList.planNew') }}
      </button>
      <button class="btn-ghost" @click="openCreate">
        <el-icon style="margin-right: 6px"><Plus /></el-icon>{{ t('tripList.manualCreate') }}
      </button>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && !trips.length" class="empty">
      <div class="empty-illustration">
        <svg width="120" height="120" viewBox="0 0 120 120" fill="none" aria-hidden="true">
          <circle cx="60" cy="60" r="54" fill="#fff0f3" />
          <path d="M60 28c-9 12-16 21-16 30 0 11 7.2 18 16 18s16-7 16-18c0-9-7-18-16-30z" fill="#ff385c" opacity="0.85" />
          <circle cx="60" cy="57" r="6.5" fill="#fff" />
          <path d="M38 88h44" stroke="#ff8a5c" stroke-width="3" stroke-linecap="round" />
          <path d="M30 98h60" stroke="#ffb199" stroke-width="3" stroke-linecap="round" />
        </svg>
      </div>
      <p class="empty-title">{{ t('tripList.emptyTitle') }}</p>
      <p class="empty-sub">{{ t('tripList.emptySub') }}</p>
      <button class="btn-primary" @click="router.push('/plan')">
        <el-icon style="margin-right: 6px"><MagicStick /></el-icon>{{ t('tripList.startPlan') }}
      </button>
    </div>

    <!-- 卡片网格 -->
    <div v-loading="loading" class="grid-wrap">
      <div class="trip-grid" v-if="trips.length">
        <article
          v-for="trip in trips"
          :key="trip.id"
          class="trip-card"
          @click="router.push(`/trips/${trip.id}`)"
        >
          <!-- 氛围头图 -->
          <div class="card-cover" :style="{ background: gradientOf(trip.destination) }">
            <span class="cover-city">{{ (trip.destination || '?').slice(0, 1) }}</span>
            <span class="cover-name">{{ trip.destination }}</span>
            <span class="status-badge" :class="(statusMap[trip.status] || statusMap.draft).type">
              {{ (statusMap[trip.status] || statusMap.draft).label }}
            </span>
          </div>

          <!-- 卡片内容 -->
          <div class="card-body">
            <h3 class="card-title">{{ trip.title }}</h3>
            <div class="card-meta">
              <span class="meta-item">
                <el-icon><Calendar /></el-icon>{{ dateRange(trip) }}
              </span>
              <span class="meta-item">
                <el-icon><User /></el-icon>{{ trip.travelers }} {{ t('common.people') }}
              </span>
              <span class="meta-item">
                <el-icon><Clock /></el-icon>{{ dayCount(trip) }} {{ t('common.days') }}
              </span>
            </div>
            <div class="card-bottom">
              <span class="budget" v-if="trip.budget != null">¥{{ trip.budget }}</span>
              <span class="budget muted" v-else>{{ t('tripList.budgetUnset') }}</span>
              <div class="card-actions" @click.stop>
                <el-button link type="primary" @click="router.push(`/trips/${trip.id}`)">{{ t('common.view') }}</el-button>
                <el-button link type="danger" @click="removeTrip(trip)">{{ t('common.delete') }}</el-button>
              </div>
            </div>
          </div>
        </article>
      </div>

      <!-- 分页 -->
      <div class="pager" v-if="total > pageSize">
        <el-pagination
          layout="prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          background
          @current-change="onPageChange"
        />
      </div>
    </div>

    <!-- 手动创建行程对话框 -->
    <el-dialog v-model="createVisible" :title="t('tripList.createDialogTitle')" width="460px">
      <el-form label-width="80px">
        <el-form-item :label="t('tripList.title')" required>
          <el-input v-model="createForm.title" :placeholder="t('tripList.titlePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('tripList.destination')" required>
          <el-input v-model="createForm.destination" :placeholder="t('tripList.destinationPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('tripList.date')" required>
          <el-date-picker
            v-model="createForm.start_date"
            type="date"
            value-format="YYYY-MM-DD"
            :placeholder="t('tripList.startDate')"
            style="width: 48%"
          />
          <span class="date-sep">→</span>
          <el-date-picker
            v-model="createForm.end_date"
            type="date"
            value-format="YYYY-MM-DD"
            :placeholder="t('tripList.endDate')"
            style="width: 48%"
          />
        </el-form-item>
        <el-form-item :label="t('tripList.travelers')">
          <el-input-number v-model="createForm.travelers" :min="1" :max="20" />
        </el-form-item>
        <el-form-item :label="t('tripList.budgetYuan')">
          <el-input-number v-model="createForm.budget" :min="0" :step="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">{{ t('common.create') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head {
  display: flex; align-items: flex-end; justify-content: space-between;
  margin-bottom: 24px; gap: 16px; flex-wrap: wrap;
}
.page-title {
  margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink);
}
.page-sub { margin: 6px 0 0; font-size: 14px; color: var(--muted); }

.btn-primary {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--brand); color: #fff; border: none; cursor: pointer;
  font-size: 14px; font-weight: 500; padding: 11px 20px;
  border-radius: var(--radius-full);
  box-shadow: 0 2px 10px rgba(255,56,92,0.28);
  transition: background .2s, transform .15s, box-shadow .2s;
}
.btn-primary:hover { background: var(--brand-dark); box-shadow: 0 4px 16px rgba(255,56,92,0.38); transform: translateY(-1px); }

.btn-ghost {
  display: inline-flex; align-items: center; gap: 4px;
  background: transparent; border: 1px solid var(--line); cursor: pointer;
  font-size: 14px; font-weight: 500; color: var(--ink-2);
  padding: 11px 20px; border-radius: var(--radius-full);
  transition: border-color .2s, color .2s;
}
.btn-ghost:hover { border-color: var(--brand); color: var(--brand); }

/* ── 空状态 ── */
.empty { text-align: center; padding: 80px 0 60px; }
.empty-illustration { margin-bottom: 20px; }
.empty-title { font-size: 22px; font-weight: 600; margin: 0 0 8px; color: var(--ink); }
.empty-sub { font-size: 14px; color: var(--muted); line-height: 1.7; margin: 0 0 24px; }

/* ── 卡片网格 ── */
.grid-wrap { min-height: 200px; }
.trip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}
.trip-card {
  background: var(--surface);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-card);
  overflow: hidden;
  cursor: pointer;
  transition: transform .2s ease, box-shadow .2s ease;
  border: 1px solid var(--line);
}
.trip-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-hover);
}

.card-cover {
  position: relative;
  height: 132px;
  display: flex; align-items: center; justify-content: center;
  gap: 10px;
}
.cover-city {
  font-size: 52px; font-weight: 700; color: rgba(255,255,255,0.95);
  text-shadow: 0 2px 12px rgba(0,0,0,0.12);
}
.cover-name {
  font-size: 22px; font-weight: 700; color: rgba(255,255,255,0.95);
  letter-spacing: 0.02em;
  text-shadow: 0 2px 10px rgba(0,0,0,0.15);
}
.status-badge {
  position: absolute; top: 12px; right: 12px;
  font-size: 11px; font-weight: 600;
  padding: 4px 10px; border-radius: var(--radius-full);
  background: rgba(255,255,255,0.9);
}
.status-badge.success { color: var(--success); }
.status-badge.warning { color: var(--warning); }
.status-badge.info { color: var(--muted); }

.card-body { padding: 16px 18px 14px; }
.card-title {
  margin: 0 0 10px; font-size: 17px; font-weight: 600; color: var(--ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.card-meta {
  display: flex; flex-wrap: wrap; gap: 8px 14px;
  font-size: 12.5px; color: var(--muted); margin-bottom: 12px;
}
.meta-item { display: inline-flex; align-items: center; gap: 4px; }
.meta-item .el-icon { font-size: 13px; color: var(--faint); }

.card-bottom {
  display: flex; align-items: center; justify-content: space-between;
  border-top: 1px solid var(--line); padding-top: 10px;
}
.budget { font-size: 15px; font-weight: 600; color: var(--ink); }
.budget.muted { color: var(--faint); font-weight: 400; font-size: 13px; }
.card-actions { display: flex; gap: 2px; }

.pager { display: flex; justify-content: center; margin-top: 28px; }

@media (max-width: 720px) {
  .trip-grid { grid-template-columns: 1fr; }
}
</style>