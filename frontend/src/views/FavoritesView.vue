<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick, Star, View, Delete } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import * as api from '@/api'

const router = useRouter()
const { t } = useI18n()

const loading = ref(false)
const favs = ref([])
const total = ref(0)
const agg = ref({ items: [], total: 0, trips: 0 })
const aggLoading = ref(false)
const creatingId = ref('')

// 收集箱（task-social-favorites-flow-eval：collect-first）——导入候选先攒着，
// 与「收藏行程」分离：这里装的是单个地点，还没有行程。
const spots = ref([])
const spotsTotal = ref(0)
const spotsLoading = ref(false)
const removingSpotId = ref('')
// 收集箱勾选 → 一键成路线（第二段聚合）
const spotChecked = ref({}) // { [spotId]: boolean }
const routeDialogVisible = ref(false)
const routeCreating = ref(false)
const routeForm = ref({
  title: '',
  destination: '',
  start_date: '',
  days: 3,
  travelers: 2,
})
const checkedSpots = computed(() => spots.value.filter((s) => spotChecked.value[s.id]))
const checkedSpotIds = computed(() => checkedSpots.value.map((s) => s.id))
const selectedCount = computed(() => checkedSpots.value.length)
const canCreateRoute = computed(() => selectedCount.value > 0)

async function load() {
  loading.value = true
  try {
    const data = await api.listFavorites({ limit: 200 })
    favs.value = data.items || []
    total.value = data.total || 0
  } catch {
    // api 拦截器已提示
  } finally {
    loading.value = false
  }
}

async function loadAgg() {
  aggLoading.value = true
  try {
    const data = await api.aggregateFavoriteStops({ limit: 200 })
    agg.value = data || { items: [], total: 0, trips: 0 }
  } catch {
    agg.value = { items: [], total: 0, trips: 0 }
  } finally {
    aggLoading.value = false
  }
}

async function loadSpots() {
  spotsLoading.value = true
  try {
    const data = await api.listFavoriteSpots({ limit: 200 })
    spots.value = data.items || []
    spotsTotal.value = data.total || 0
  } catch {
    // api 拦截器已提示
  } finally {
    spotsLoading.value = false
  }
}

async function removeSpot(spot) {
  if (removingSpotId.value) return
  removingSpotId.value = spot.id
  try {
    await api.removeFavoriteSpot(spot.id)
    ElMessage.success(t('favorites.boxRemoved'))
    spots.value = spots.value.filter((s) => s.id !== spot.id)
    spotsTotal.value = Math.max(0, spotsTotal.value - 1)
  } catch {
    // api 拦截器已提示
  } finally {
    removingSpotId.value = ''
  }
}

const aggPreview = computed(() => agg.value.items.slice(0, 8))
const aggMore = computed(() => Math.max(0, (agg.value.total || 0) - aggPreview.value.length))

function openShare(fav) {
  if (fav.share_token) router.push(`/share/${fav.share_token}`)
}

async function createRoute(fav) {
  if (creatingId.value) return
  creatingId.value = fav.trip_id
  try {
    const trip = await api.createRouteFromFavorite(fav.trip_id)
    ElMessage.success(t('favorites.routeCreated'))
    router.push(`/trips/${trip.id}`)
  } catch {
    // api 拦截器已提示（未收藏/行程失效 404 等）
  } finally {
    creatingId.value = ''
  }
}

function openRouteDialog() {
  if (!canCreateRoute.value) return
  routeDialogVisible.value = true
}

async function createRouteFromSpots() {
  if (!checkedSpotIds.value.length || routeCreating.value) return
  const form = routeForm.value
  if (!form.title.trim() || !form.destination.trim() || !form.start_date) {
    ElMessage.warning(t('favorites.createRoutePlaceholder'))
    return
  }
  routeCreating.value = true
  try {
    const payload = {
      spot_ids: checkedSpotIds.value,
      title: form.title.trim(),
      destination: form.destination.trim(),
      start_date: form.start_date,
      days: form.days,
      travelers: form.travelers,
    }
    const data = await api.createFavoriteSpotRoute(payload)
    const report = data.report || {}
    ElMessage.success(t('favorites.createRouteSuccess'))
    if (report.overflow > 0) {
      ElMessage.warning(t('favorites.createRouteOverflow', { overflow: report.overflow }))
    }
    if (report.hotel_overflow > 0) {
      ElMessage.warning(t('favorites.createRouteHotelOverflow', { count: report.hotel_overflow }))
    }
    if (report.skipped > 0) {
      ElMessage.info(t('favorites.createRouteSkipped', { count: report.skipped }))
    }
    routeDialogVisible.value = false
    router.push(`/trips/${data.trip.id}`)
  } catch {
    // api 拦截器已提示
  } finally {
    routeCreating.value = false
  }
}

async function removeFav(fav) {
  try {
    await ElMessageBox.confirm(
      t('favorites.removeConfirmMsg', { title: fav.title }),
      t('favorites.removeConfirmTitle'),
      { type: 'warning', confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel') },
    )
  } catch {
    return
  }
  try {
    await api.removeFavorite(fav.trip_id)
    ElMessage.success(t('favorites.removed'))
    await load()
    await loadAgg()
  } catch {
    // api 拦截器已提示
  }
}

function dateRange(fav) {
  if (!fav.start_date && !fav.end_date) return t('favorites.dateUndecided')
  return t('favorites.dateRange', { start: fav.start_date || '?', end: fav.end_date || '?' })
}

const typeLabels = {
  attraction: t('common.typeAttraction'),
  food: t('common.typeFood'),
  hotel: t('common.typeHotel'),
}

onMounted(() => {
  load()
  loadAgg()
  loadSpots()
})
</script>

<template>
  <div class="favorites-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">{{ t('favorites.title') }}</h2>
        <p class="page-sub">
          <template v-if="total">{{ t('favorites.subHas', { count: total }) }}</template>
          <template v-else>{{ t('favorites.subEmpty') }}</template>
        </p>
      </div>
    </div>

    <!-- 聚合预览：收藏的站点能组出什么 -->
    <div v-if="agg.total > 0" class="agg-card">
      <div class="agg-head">
        <span class="agg-title">
          <el-icon style="margin-right: 6px"><Star /></el-icon>
          {{ t('favorites.aggTitle', { stops: agg.total, trips: agg.trips }) }}
        </span>
        <span class="agg-hint">{{ t('favorites.aggHint') }}</span>
      </div>
      <div class="agg-chips">
        <span v-for="s in aggPreview" :key="s.name" class="agg-chip">
          {{ s.name }}
          <em class="agg-type">{{ typeLabels[s.stop_type] || s.stop_type }}</em>
        </span>
        <span v-if="aggMore > 0" class="agg-more">+{{ aggMore }}</span>
        <span v-if="aggLoading" class="agg-more">{{ t('common.loading') }}</span>
      </div>
    </div>

    <!-- 收集箱：导入候选先攒着（地点级，还没有行程） -->
    <div class="box-card">
      <div class="agg-head">
        <span class="agg-title">
          {{ t('favorites.boxTitle') }}
          <em v-if="spotsTotal" class="box-count">{{ spotsTotal }}</em>
        </span>
        <span class="agg-hint">{{ t('favorites.boxHint') }}</span>
      </div>
      <div v-if="spotsLoading" class="box-empty">{{ t('common.loading') }}</div>
      <div v-else-if="!spots.length" class="box-empty">{{ t('favorites.boxEmpty') }}</div>
      <div v-else class="box-chips">
        <span v-for="s in spots" :key="s.id" class="box-chip" :class="{ 'box-chip-checked': spotChecked[s.id] }">
          <label class="box-check">
            <input v-model="spotChecked[s.id]" type="checkbox" />
            <template v-if="s.source_platform" class="box-src">{{ s.source_platform }}</template>
          </label>
          {{ s.name }}
          <em class="agg-type">{{ typeLabels[s.stop_type] || s.stop_type }}</em>
          <button
            class="box-remove"
            type="button"
            :disabled="removingSpotId === s.id"
            :title="t('favorites.boxRemove')"
            @click="removeSpot(s)"
          >
            ×
          </button>
        </span>
      </div>
      <div v-if="spots.length" class="box-actions">
        <span v-if="selectedCount" class="box-selected">{{ t('favorites.createRouteSelect', { count: selectedCount }) }}</span>
        <button class="btn-primary btn-sm" :disabled="!canCreateRoute" @click="openRouteDialog">
          <el-icon style="margin-right: 4px"><MagicStick /></el-icon>{{ t('favorites.boxCreateRoute') }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="empty-hint">{{ t('common.loading') }}</div>
    <div v-else-if="!favs.length" class="empty-hint">{{ t('favorites.emptyHint') }}</div>

    <div v-else class="fav-list">
      <div v-for="fav in favs" :key="fav.id" class="fav-card">
        <div class="fav-main">
          <div class="fav-title">{{ fav.title }}</div>
          <div class="fav-meta">
            <span>{{ fav.destination }}</span>
            <span>{{ dateRange(fav) }}</span>
          </div>
        </div>
        <div class="fav-actions">
          <button class="btn-primary btn-sm" :disabled="creatingId === fav.trip_id" @click="createRoute(fav)">
            <el-icon style="margin-right: 4px"><MagicStick /></el-icon>
            {{ creatingId === fav.trip_id ? t('common.loading') : t('favorites.createRoute') }}
          </button>
          <button v-if="fav.share_token" class="btn-ghost btn-sm" @click="openShare(fav)">
            <el-icon style="margin-right: 4px"><View /></el-icon>{{ t('favorites.viewShare') }}
          </button>
          <button class="btn-ghost btn-sm btn-danger" @click="removeFav(fav)">
            <el-icon style="margin-right: 4px"><Delete /></el-icon>{{ t('favorites.remove') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 收集箱 → 一键成路线（第二段聚合）对话框 -->
    <el-dialog
      v-model="routeDialogVisible"
      :title="t('favorites.createRouteDialogTitle')"
      width="min(560px, 94vw)"
      destroy-on-close
    >
      <div class="route-dialog">
        <p class="route-selected">{{ t('favorites.createRouteSelect', { count: selectedCount }) }}</p>
        <div class="route-spots">
          <span v-for="s in checkedSpots" :key="s.id" class="route-spot-chip">
            <em class="agg-type">{{ typeLabels[s.stop_type] || s.stop_type }}</em>{{ s.name }}
          </span>
        </div>
        <el-form label-position="top" class="route-form">
          <el-form-item :label="t('favorites.createRouteTitle')">
            <el-input v-model="routeForm.title" :placeholder="t('favorites.createRouteTitlePlaceholder')" maxlength="200" />
          </el-form-item>
          <el-form-item :label="t('favorites.createRouteDestination')">
            <el-input v-model="routeForm.destination" :placeholder="t('favorites.createRouteDestinationPlaceholder')" maxlength="200" />
          </el-form-item>
          <el-form-item :label="t('favorites.createRouteStartDate')">
            <el-date-picker
              v-model="routeForm.start_date"
              type="date"
              value-format="YYYY-MM-DD"
              style="width: 100%"
            />
          </el-form-item>
          <div class="route-row">
            <el-form-item :label="t('favorites.createRouteDays')">
              <el-input-number v-model="routeForm.days" :min="1" :max="14" />
            </el-form-item>
            <el-form-item :label="t('favorites.createRouteTravelers')">
              <el-input-number v-model="routeForm.travelers" :min="1" :max="20" />
            </el-form-item>
          </div>
        </el-form>
        <p class="hint">{{ t('favorites.boxCreateHint') }}</p>
      </div>
      <template #footer>
        <el-button @click="routeDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="routeCreating" @click="createRouteFromSpots">
          <el-icon style="margin-right: 4px"><MagicStick /></el-icon>{{ t('favorites.createRouteSubmit') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.favorites-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 16px 60px;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
}
.page-title { font-size: 24px; font-weight: 700; margin: 0 0 6px; }
.page-sub { color: var(--faint); margin: 0; font-size: 14px; }

.agg-card {
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 20px;
  background: var(--card-bg, #fff);
}
.agg-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.agg-title { font-weight: 600; font-size: 14px; display: inline-flex; align-items: center; }
.agg-hint { color: var(--faint); font-size: 12px; }
.agg-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.agg-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--bg-soft, #f3f4f6);
  font-size: 13px;
}
.agg-type { font-style: normal; color: var(--faint); font-size: 11px; }
.agg-more { color: var(--faint); font-size: 13px; align-self: center; }

/* 收集箱（collect-first：地点级候选，尚未进行程） */
.box-card {
  border: 1px dashed var(--border-color, #e5e7eb);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 20px;
  background: var(--bg-soft, #fafafa);
}
.box-count {
  font-style: normal;
  font-size: 11px;
  color: var(--primary, #409eff);
  background: color-mix(in srgb, var(--primary, #409eff) 12%, transparent);
  border-radius: 999px;
  padding: 1px 7px;
  margin-left: 6px;
}
.box-empty { color: var(--faint); font-size: 13px; }
.box-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.box-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px 4px 10px;
  border-radius: 999px;
  background: var(--card-bg, #fff);
  border: 1px solid var(--border-color, #e5e7eb);
  font-size: 13px;
}
.box-src {
  font-size: 10px;
  color: var(--faint);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 999px;
  padding: 0 5px;
}
.box-remove {
  border: none;
  background: transparent;
  color: var(--faint);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 50%;
}
.box-remove:hover { color: #f56c6c; }
.box-chip-checked {
  border-color: var(--primary, #409eff);
  background: color-mix(in srgb, var(--primary, #409eff) 8%, #fff);
}
.box-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.box-check input {
  accent-color: var(--primary, #409eff);
  margin: 0;
}
.box-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-color, #e5e7eb);
}
.box-selected { color: var(--faint); font-size: 13px; }

/* 一键成路线对话框 */
.route-dialog .route-selected { margin: 0 0 8px; font-size: 13px; color: var(--faint); }
.route-dialog .route-spots { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
.route-spot-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--border-color, #e5e7eb);
  font-size: 13px;
}
.route-form { margin-bottom: 4px; }
.route-row { display: flex; gap: 20px; }
.route-row .el-form-item { flex: 1; }
.route-dialog .hint { font-size: 12px; color: var(--faint); margin: 0; }

.empty-hint { text-align: center; color: var(--faint); padding: 48px 0; }

.fav-list { display: flex; flex-direction: column; gap: 12px; }
.fav-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--card-bg, #fff);
}
.fav-main { min-width: 0; }
.fav-title { font-weight: 600; font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fav-meta { display: flex; gap: 12px; color: var(--faint); font-size: 13px; margin-top: 4px; }
.fav-actions { display: flex; gap: 8px; flex-shrink: 0; flex-wrap: wrap; }

.btn-sm { padding: 6px 12px; font-size: 13px; }
.btn-ghost {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  font-size: 13px;
  border-radius: 8px;
  border: 1px solid var(--border-color, #e5e7eb);
  background: transparent;
  color: var(--text-color, #333);
  cursor: pointer;
}
.btn-ghost:hover { border-color: var(--primary, #409eff); color: var(--primary, #409eff); }
.btn-danger:hover { border-color: #f56c6c; color: #f56c6c; }

@media (max-width: 640px) {
  .fav-card { flex-direction: column; align-items: flex-start; }
  .fav-actions { width: 100%; }
  .fav-actions .btn-primary, .fav-actions .btn-ghost { flex: 1; justify-content: center; }
  .agg-head { flex-direction: column; align-items: flex-start; gap: 4px; }
}
</style>