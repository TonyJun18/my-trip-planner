<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick, Star, View, Delete, Share } from '@element-plus/icons-vue'
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