<!--
  模板商店页（frame-marketplace，任务 6.1）。

  免费/付费分栏；示例小样用真实数据渲染；付费包带兑换码入口。
  未登录可浏览（public 路由），兑换时由路由守卫引导注册。
-->
<template>
  <div class="frame-store">
    <div class="store-head">
      <h1>🖼️ {{ t('frames.store.title') }}</h1>
      <p class="store-sub">{{ t('frames.store.subtitle') }}</p>
    </div>

    <!-- 兑换码入口 -->
    <el-card class="redeem-card" shadow="never">
      <div class="redeem-row">
        <el-input
          v-model="codeInput"
          :placeholder="t('frames.store.codePlaceholder')"
          class="redeem-input"
          @keyup.enter="doRedeem"
        />
        <el-button type="primary" :loading="redeeming" @click="doRedeem">
          {{ t('frames.store.redeem') }}
        </el-button>
      </div>
      <div class="redeem-hint">{{ t('frames.store.redeemHint') }}</div>
    </el-card>

    <!-- 模板包（付费） -->
    <h2 class="store-section">{{ t('frames.store.packs') }}</h2>
    <div class="pack-grid">
      <el-card v-for="pack in packs" :key="pack.slug" class="pack-card" shadow="hover">
        <div class="pack-name">{{ pack.name }}</div>
        <div class="pack-desc">{{ pack.description }}</div>
        <div class="pack-templates">
          <el-tag v-for="slug in pack.template_slugs" :key="slug" size="small" class="pack-tag">
            {{ templateName(slug) }}
          </el-tag>
        </div>
        <div class="pack-foot">
          <span class="pack-price">¥{{ (pack.price_cents / 100).toFixed(1) }}</span>
          <el-tag v-if="ownedPacks.has(pack.slug)" type="success" size="small">
            {{ t('frames.store.owned') }}
          </el-tag>
        </div>
      </el-card>
      <div v-if="!packs.length" class="store-empty">{{ t('frames.store.noPacks') }}</div>
    </div>

    <!-- 免费模板 -->
    <h2 class="store-section">{{ t('frames.store.freeTemplates') }}</h2>
    <div class="tpl-grid">
      <div v-for="tpl in freeTemplates" :key="tpl.slug" class="tpl-card">
        <canvas :ref="(el) => setSampleCanvas(tpl.slug, el)" class="tpl-sample"></canvas>
        <div class="tpl-name">{{ tpl.name }}</div>
      </div>
    </div>

    <!-- 使用入口 -->
    <div class="store-cta">
      <router-link to="/trips">{{ t('frames.store.goTrips') }}</router-link>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'

import { getFrameCatalog, getFrameEntitlements, redeemFrameCode } from '@/api/modules/frames'
import { renderDayCard } from '@/frames/renderer'
import { FREE_TEMPLATES } from '@/frames/templates'

const { t } = useI18n()

const templates = ref([])
const packs = ref([])
const ownedPacks = ref(new Set())
const codeInput = ref('')
const redeeming = ref(false)
const sampleCanvases = ref({})

const freeTemplates = computed(() =>
  templates.value.filter((tpl) => tpl.tier === 'free' && tpl.active !== false),
)

function templateName(slug) {
  return templates.value.find((tpl) => tpl.slug === slug)?.name || slug
}

function setSampleCanvas(slug, el) {
  if (el) sampleCanvases.value[slug] = el
}

function renderSamples() {
  for (const tpl of freeTemplates.value) {
    const canvas = sampleCanvases.value[tpl.slug]
    if (!canvas) continue
    // 示例小样：真实杭州样例数据（不打码、无用户照片）
    renderDayCard(canvas, tpl, {
      day: {
        destination: t('frames.store.sampleDestination'),
        day_number: 1,
        date: new Date().toISOString().slice(0, 10),
        day_note: t('frames.store.sampleNote'),
      },
      photos: [],
      route: [
        { name: '西湖', lat: 30.24, lng: 120.15 },
        { name: '雷峰塔', lat: 30.23, lng: 120.15 },
        { name: '河坊街', lat: 30.24, lng: 120.17 },
      ],
    })
  }
}

onMounted(async () => {
  try {
    const jobs = [getFrameCatalog()]
    const authed = !!localStorage.getItem('trip_planner_token')
    if (authed) jobs.push(getFrameEntitlements())
    const [catalog, ent] = await Promise.all(jobs)
    templates.value = catalog.templates || []
    packs.value = catalog.packs || []
    if (ent) ownedPacks.value = new Set(ent.entitlements.map((e) => e.pack_slug))
    await new Promise((r) => setTimeout(r, 0)) // 等 ref 绑定
    renderSamples()
  } catch {
    ElMessage.error(t('frames.store.loadFailed'))
  }
})

async function doRedeem() {
  const code = codeInput.value.trim()
  if (!code) return
  redeeming.value = true
  try {
    const out = await redeemFrameCode(code)
    ownedPacks.value = new Set(out.entitlements.map((e) => e.pack_slug))
    ElMessage.success(t('frames.store.redeemOk', { pack: templateNameOfPack(out.pack_slug) }))
    codeInput.value = ''
  } catch (err) {
    const status = err?.response?.status
    const msg = err?.response?.data?.error?.message
    if (status === 409) ElMessage.error(msg || t('frames.store.errUsed'))
    else if (status === 410) ElMessage.error(msg || t('frames.store.errRevoked'))
    else if (status === 401) ElMessage.warning(t('frames.store.errLogin'))
    else ElMessage.error(msg || t('frames.store.errNotFound'))
  } finally {
    redeeming.value = false
  }
}

function templateNameOfPack(packSlug) {
  return packs.value.find((p) => p.slug === packSlug)?.name || packSlug
}
</script>

<style scoped>
.frame-store { max-width: 960px; margin: 0 auto; padding: 24px; }
.store-head h1 { margin-bottom: 4px; }
.store-sub { color: #888; margin: 0 0 20px; }
.redeem-card { margin-bottom: 24px; }
.redeem-row { display: flex; gap: 8px; }
.redeem-input { max-width: 360px; }
.redeem-hint { color: #aaa; font-size: 12px; margin-top: 8px; }
.store-section { margin: 28px 0 12px; font-size: 18px; }
.pack-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.pack-name { font-weight: 700; font-size: 16px; }
.pack-desc { color: #888; font-size: 13px; margin: 6px 0; min-height: 36px; }
.pack-templates { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; }
.pack-tag { margin: 1px; }
.pack-foot { display: flex; align-items: center; justify-content: space-between; }
.pack-price { font-weight: 700; color: var(--el-color-warning); }
.tpl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.tpl-card { text-align: center; }
.tpl-sample { width: 100%; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
.tpl-name { margin-top: 6px; font-weight: 600; }
.store-cta { margin-top: 28px; text-align: center; }
.store-empty { color: #aaa; }
</style>
