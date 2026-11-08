<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api'
import GalleryCard from '@/components/gallery/GalleryCard.vue'

/**
 * 灵感画廊（task-gallery-v2）。
 *
 * 在此之前导航「灵感画廊」指向 `/?view=gallery`——用户落到营销首页，画廊只是页面
 * 最底部的一个 section，等于"发布到画廊"没有落地页。本页是它的正式落点：
 * - 全部精选：公开可逛（免登录），筛选（目的地）/ 排序（最新 / 最热）/ 分页
 * - 我发布的：登录后管理自己的发布，支持撤回（发布闭环）
 * - 卡片两个动作：看详情（/share/:token 只读页）/ 以此为蓝本创建（clone）
 * - 城市模板：规则生成的开工起点，深链预填 PlanWizard
 */
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const auth = useAuthStore()

const tab = ref(route.query.tab === 'mine' ? 'mine' : 'all')
const destination = ref('')
const sort = ref('new')
const page = ref(1)
const pageSize = 12

const items = ref([])
const total = ref(0)
const loading = ref(false)
const loaded = ref(false)
const needsLogin = ref(false)
const templates = ref([])

const destinations = computed(() => {
  const set = new Set()
  templates.value.forEach((tpl) => tpl.destination && set.add(tpl.destination))
  items.value.forEach((it) => it.destination && set.add(it.destination))
  return [...set]
})

const isEmpty = computed(() => loaded.value && items.value.length === 0)
const showTemplates = computed(() => tab.value === 'all' && page.value === 1 && !destination.value)

async function load() {
  needsLogin.value = false
  if (tab.value === 'mine' && !auth.isLoggedIn) {
    items.value = []
    total.value = 0
    loaded.value = true
    needsLogin.value = true
    return
  }
  loading.value = true
  try {
    const params = { limit: pageSize, offset: (page.value - 1) * pageSize, sort: sort.value }
    if (destination.value) params.destination = destination.value
    if (tab.value === 'mine') params.mine = 1
    const r = await api.getGallery(params)
    items.value = r.items || []
    total.value = Number(r.total || 0)
  } catch (e) {
    items.value = []
    total.value = 0
    ElMessage.error(t('gallery.loadFail'))
  } finally {
    loading.value = false
    loaded.value = true
  }
}

async function loadTemplates() {
  try {
    const r = await api.getCityTemplates({ limit: 8 })
    templates.value = r.items || []
  } catch {
    /* 模板失败静默：画廊主列表不因模板缺失而报错 */
  }
}

function resetAndLoad() {
  page.value = 1
  load()
}

function switchTab(next) {
  if (tab.value === next) return
  tab.value = next
  resetAndLoad()
}

function onPageChange(p) {
  page.value = p
  load()
}

// ── 卡片动作 ────────────────────────────────────────────
function openDetail(item) {
  if (!item.share_token) return
  router.push(`/share/${item.share_token}?from=gallery`)
}

async function cloneItem(item) {
  if (!auth.isLoggedIn) {
    router.push(`/login?redirect=${encodeURIComponent('/gallery')}`)
    return
  }
  try {
    const cloned = await api.cloneGalleryTrip(item.trip_id)
    ElMessage.success(t('gallery.cloneDone'))
    router.push(`/trips/${cloned.id}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.error?.message || t('gallery.cloneFail'))
  }
}

async function unpublishItem(item) {
  try {
    await ElMessageBox.confirm(t('gallery.unpublishConfirm'), t('gallery.cardUnpublish'), {
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await api.unpublishFromGallery(item.trip_id)
    ElMessage.success(t('gallery.unpublishDone'))
    // 撤回后当前页可能空掉 → 回退一页再拉
    if (items.value.length === 1 && page.value > 1) page.value -= 1
    load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.error?.message || t('gallery.loadFail'))
  }
}

function startFromTemplate(tpl) {
  const query = { destination: tpl.destination }
  if (tpl.days) query.days = tpl.days
  const target = `/plan?${new URLSearchParams(query).toString()}`
  if (auth.isLoggedIn) router.push(target)
  else router.push(`/login?redirect=${encodeURIComponent(target)}`)
}

function goPublish() {
  if (auth.isLoggedIn) router.push('/trips')
  else router.push('/login?redirect=/trips')
}

onMounted(() => {
  load()
  loadTemplates()
})
</script>

<template>
  <div class="gallery-page">
    <header class="g-head">
      <div class="g-head-copy">
        <h1 class="g-head-title">{{ $t('gallery.title') }}</h1>
        <p class="g-head-sub">{{ $t('gallery.subtitle') }}</p>
      </div>
      <el-button class="g-publish" @click="goPublish">{{ $t('gallery.publishCta') }}</el-button>
    </header>

    <div class="g-bar">
      <div class="g-tabs" role="tablist">
        <button
          class="g-tab"
          :class="{ on: tab === 'all' }"
          type="button"
          role="tab"
          :aria-selected="tab === 'all'"
          @click="switchTab('all')"
        >{{ $t('gallery.tabAll') }}</button>
        <button
          class="g-tab"
          :class="{ on: tab === 'mine' }"
          type="button"
          role="tab"
          :aria-selected="tab === 'mine'"
          @click="switchTab('mine')"
        >{{ $t('gallery.tabMine') }}</button>
      </div>

      <div class="g-filters">
        <el-select
          v-model="destination"
          class="g-select"
          clearable
          :placeholder="$t('gallery.filterDest')"
          @change="resetAndLoad"
        >
          <el-option v-for="d in destinations" :key="d" :label="d" :value="d" />
        </el-select>
        <el-radio-group v-model="sort" size="small" @change="resetAndLoad">
          <el-radio-button value="new">{{ $t('gallery.sortNew') }}</el-radio-button>
          <el-radio-button value="hot">{{ $t('gallery.sortHot') }}</el-radio-button>
        </el-radio-group>
        <span class="g-count">{{ $t('gallery.count', { n: total }) }}</span>
      </div>
    </div>

    <!-- 城市模板：开工起点（首屏、无筛选时出现；规则生成，诚实标注在服务端 basis） -->
    <section v-if="showTemplates && templates.length" class="g-block">
      <div class="g-block-head">
        <h2 class="g-block-title">{{ $t('gallery.templatesTitle') }}</h2>
        <span class="g-block-hint">{{ $t('gallery.templatesHint') }}</span>
      </div>
      <div class="g-tpl-grid">
        <article
          v-for="tpl in templates"
          :key="'tpl-' + tpl.destination"
          class="g-tpl"
          @click="startFromTemplate(tpl)"
        >
          <span class="g-tpl-name">{{ tpl.destination }}</span>
          <span class="g-tpl-meta">{{ $t('gallery.templateMeta', { days: tpl.days, tier: tpl.budget_tier }) }}</span>
          <span class="g-tpl-cta">{{ $t('gallery.useTemplate') }} →</span>
        </article>
      </div>
    </section>

    <!-- 未登录看「我发布的」 -->
    <div v-if="needsLogin" class="g-empty">
      <p class="g-empty-title">{{ $t('gallery.loginToBrowse') }}</p>
      <el-button type="primary" @click="router.push('/login?redirect=/gallery?tab=mine')">
        {{ $t('gallery.login') }}
      </el-button>
    </div>

    <!-- 空态 -->
    <div v-else-if="isEmpty" class="g-empty">
      <template v-if="tab === 'mine'">
        <p class="g-empty-title">{{ $t('gallery.emptyMineTitle') }}</p>
        <p class="g-empty-sub">{{ $t('gallery.emptyMineSub') }}</p>
        <el-button type="primary" @click="goPublish">{{ $t('gallery.goTrips') }}</el-button>
      </template>
      <template v-else>
        <p class="g-empty-title">{{ $t('gallery.emptyTitle') }}</p>
        <p class="g-empty-sub">{{ $t('gallery.emptySub') }}</p>
        <el-button type="primary" @click="goPublish">{{ $t('gallery.publishCta') }}</el-button>
      </template>
    </div>

    <!-- 卡片网格 -->
    <div v-else v-loading="loading" class="g-grid">
      <GalleryCard
        v-for="item in items"
        :key="item.trip_id"
        :item="item"
        :mine="tab === 'mine'"
        @open="openDetail(item)"
        @clone="cloneItem(item)"
        @unpublish="unpublishItem(item)"
      />
    </div>

    <div v-if="!needsLogin && total > pageSize" class="g-pager">
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
</template>

<style scoped>
.gallery-page { max-width: 1080px; margin: 0 auto; padding-bottom: 32px; }

.g-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin: 8px 0 18px;
}
.g-head-title { margin: 0 0 6px; font-size: 26px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); }
.g-head-sub { margin: 0; font-size: 13.5px; color: var(--muted); line-height: 1.6; }
.g-publish { flex-shrink: 0; }

.g-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 18px;
}
.g-tabs { display: inline-flex; gap: 4px; padding: 3px; background: var(--brand-soft); border-radius: var(--radius-full); }
.g-tab {
  padding: 6px 14px;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
  background: none;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: background 0.18s, color 0.18s;
}
.g-tab.on { background: var(--card); color: var(--brand); box-shadow: var(--shadow-card); }
.g-tab:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }

.g-filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-left: auto; }
.g-select { width: 150px; }
.g-count { font-size: 12.5px; color: var(--faint); }

.g-block { margin-bottom: 22px; }
.g-block-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.g-block-title { margin: 0; font-size: 15px; font-weight: 700; color: var(--ink); }
.g-block-hint { font-size: 12.5px; color: var(--muted); }
.g-tpl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.g-tpl {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 12px 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: transform 0.18s, border-color 0.18s;
}
.g-tpl:hover { transform: translateY(-2px); border-color: var(--brand); }
.g-tpl-name { font-size: 14px; font-weight: 650; color: var(--ink); }
.g-tpl-meta { font-size: 11.5px; color: var(--muted); }
.g-tpl-cta { margin-top: 4px; font-size: 12px; font-weight: 600; color: var(--brand); }

.g-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; min-height: 120px; }

.g-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 56px 20px;
  text-align: center;
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: var(--radius-lg);
}
.g-empty-title { margin: 0; font-size: 16px; font-weight: 650; color: var(--ink); }
.g-empty-sub { margin: 0; font-size: 13px; color: var(--muted); max-width: 460px; line-height: 1.6; }

.g-pager { display: flex; justify-content: center; margin-top: 22px; }

@media (max-width: 640px) {
  .g-head-title { font-size: 22px; }
  .g-filters { margin-left: 0; width: 100%; }
  .g-select { flex: 1 1 140px; }
  .g-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
}
</style>
