<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const auth = useAuthStore()

// 已登录用户访问产品门面 → 直接进「我的行程」（门面面向陌生访客）；
// 但带 ?view=gallery 时保留首页，让登录用户也能看自己发布到画廊的行程
onMounted(() => {
  if (auth.isLoggedIn && route.query.view !== 'gallery') router.replace('/trips')
  loadGallery()
})

// 主 CTA：已登录直接进规划，未登录带去登录并回跳 /plan
function startPlanning() {
  if (auth.isLoggedIn) router.push('/plan')
  else router.push('/login?redirect=/plan')
}

// 灵感区：示例行程（静态示意，B 阶段接后端精选接口后可替换）
// key 用于 i18n 显示名（cities.*），点击只跳转规划不提交城市，可直接用翻译名
const showcaseTrips = [
  { key: 'hangzhou', days: 3, budget: 3000, emoji: '🍃', hue: 'linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%)' },
  { key: 'chengdu', days: 4, budget: 4000, emoji: '🐼', hue: 'linear-gradient(135deg, #f6d365 0%, #fda085 100%)' },
  { key: 'dali', days: 5, budget: 5000, emoji: '🏔️', hue: 'linear-gradient(135deg, #a1c4fd 0%, #c2e9fb 100%)' },
  { key: 'xiamen', days: 3, budget: 2500, emoji: '🌊', hue: 'linear-gradient(135deg, #fbc2eb 0%, #a6c1ee 100%)' },
  { key: 'xian', days: 4, budget: 3500, emoji: '🏛️', hue: 'linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%)' },
  { key: 'sanya', days: 5, budget: 6000, emoji: '🏝️', hue: 'linear-gradient(135deg, #fddb92 0%, #e6b0f4 100%)' },
]
function cityName(key) {
  return t('cities.' + key)
}

const features = computed(() => [
  { icon: 'MagicStick', title: t('landing.featAiTitle'), desc: t('landing.featAiDesc'), tags: [t('landing.tagAgents'), t('landing.tagMap'), t('landing.tagWeather')] },
  { icon: 'ChatDotRound', title: t('landing.featReviseTitle'), desc: t('landing.featReviseDesc'), tags: [t('landing.tagDiff'), t('landing.tagRollback')] },
  { icon: 'Van', title: t('landing.featSvcTitle'), desc: t('landing.featSvcDesc'), tags: [t('landing.tagTransport'), t('landing.tagCheckin'), t('landing.tagDiscount')] },
  { icon: 'UserFilled', title: t('landing.featCollabTitle'), desc: t('landing.featCollabDesc'), tags: [t('landing.tagShare'), t('landing.tagVote'), t('landing.tagEdit')] },
])

const whyPoints = computed(() => [
  { icon: 'DataLine', title: t('landing.whyRealTitle'), desc: t('landing.whyRealDesc') },
  { icon: 'View', title: t('landing.whyTraceTitle'), desc: t('landing.whyTraceDesc') },
  { icon: 'Document', title: t('landing.whyExportTitle'), desc: t('landing.whyExportDesc') },
])

const demoSteps = computed(() => [
  { no: '01', title: t('landing.demo1Title'), desc: t('landing.demo1Desc') },
  { no: '02', title: t('landing.demo2Title'), desc: t('landing.demo2Desc') },
  { no: '03', title: t('landing.demo3Title'), desc: t('landing.demo3Desc') },
])

// ── 灵感画廊 + 城市模板（task-gallery-featured / city-templates） ──
const galleryItems = ref([])
const cityTemplates = ref([])

async function loadGallery() {
  try {
    const [g, tpl] = await Promise.all([api.getGallery({ limit: 6 }), api.getCityTemplates({ limit: 8 })])
    galleryItems.value = g.items || []
    cityTemplates.value = tpl.items || []
  } catch {
    // 画廊/模板失败静默：门面页不因后端数据缺失而报错
  }
}

// 模板卡 → 深链预填规划（带目的地/天数；未登录先登录再回跳）
function startFromTemplate(tpl) {
  const query = { destination: tpl.destination }
  if (tpl.days) query.days = tpl.days
  const target = `/plan?${new URLSearchParams(query).toString()}`
  if (auth.isLoggedIn) router.push(target)
  else router.push(`/login?redirect=${encodeURIComponent(target)}`)
}

// 画廊卡 → 以此为基础创建（复制到我的账号）
async function createFromGallery(item) {
  if (!auth.isLoggedIn) {
    router.push('/login?redirect=/')
    return
  }
  try {
    const cloned = await api.cloneGalleryTrip(item.trip_id)
    router.push(`/trips/${cloned.id}`)
  } catch {
    // 复制失败静默（避免门面页弹错）
  }
}

// ── 滚动渐入（IntersectionObserver，进入视口 → visible，一次性） ──
const revealObserver = ref(null)
onMounted(() => {
  const els = document.querySelectorAll('.reveal')
  revealObserver.value = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible')
          revealObserver.value.unobserve(entry.target)
        }
      })
    },
    { threshold: 0.12 }
  )
  els.forEach((el) => revealObserver.value.observe(el))
})
onBeforeUnmount(() => {
  revealObserver.value?.disconnect()
})
</script>

<template>
  <div class="landing">
    <!-- ── Hero ── -->
    <section class="hero">
      <div class="hero-copy">
        <h1 class="hero-title">
          {{ t('landing.heroTitle1') }}<br />
          <span class="accent">{{ t('landing.heroTitle2') }}</span>
        </h1>
        <p class="hero-sub">{{ t('landing.heroSub') }}</p>
        <div class="hero-cta">
          <button class="btn-primary btn-lg" @click="startPlanning">
            <el-icon style="margin-right: 6px"><MagicStick /></el-icon>{{ t('landing.heroCtaPrimary') }}
          </button>
          <a class="btn-ghost btn-lg" href="#how">{{ t('landing.heroCtaSecondary') }} ↓</a>
        </div>
        <p class="hero-note">{{ t('landing.heroNote') }}</p>
      </div>

      <!-- 产品示意：Bento 卡片堆叠 + 漂浮 chips（真实组件风格复刻，B 阶段可替换为可交互试玩） -->
      <div class="hero-visual" aria-hidden="true">
        <div class="glow glow-brand"></div>
        <div class="glow glow-warm"></div>

        <div class="mock-trip-card mock-1">
          <div class="mock-cover" :style="{ background: showcaseTrips[0].hue }">
            <span class="mock-emoji">{{ showcaseTrips[0].emoji }}</span>
            <span class="mock-dest">{{ cityName(showcaseTrips[0].key) }}</span>
            <span class="mock-badge">{{ t('landing.statusConfirmed') }}</span>
          </div>
          <div class="mock-body">
            <div class="mock-title">{{ cityName(showcaseTrips[0].key) }} · {{ t('landing.daysN', { n: showcaseTrips[0].days }) }}</div>
            <div class="mock-meta">
              <span>📅 {{ t('landing.dateRangeSample') }}</span>
              <span>👥 2 {{ t('common.people') }}</span>
              <span>💰 ¥{{ showcaseTrips[0].budget }}</span>
            </div>
            <div class="mock-dots">
              <span v-for="n in 5" :key="n" class="dot" :class="{ on: n <= showcaseTrips[0].days }" />
            </div>
          </div>
        </div>

        <div class="mock-trip-card mock-2">
          <div class="mock-cover" :style="{ background: showcaseTrips[1].hue }">
            <span class="mock-emoji">{{ showcaseTrips[1].emoji }}</span>
            <span class="mock-dest">{{ cityName(showcaseTrips[1].key) }}</span>
          </div>
          <div class="mock-body">
            <div class="mock-title">{{ cityName(showcaseTrips[1].key) }} · {{ t('landing.daysN', { n: showcaseTrips[1].days }) }}</div>
            <div class="mock-meta">
              <span>👥 2 {{ t('common.people') }}</span>
              <span>💰 ¥{{ showcaseTrips[1].budget }}</span>
            </div>
          </div>
        </div>

        <div class="mock-trip-card mock-3">
          <div class="mock-cover" :style="{ background: showcaseTrips[2].hue }">
            <span class="mock-emoji">{{ showcaseTrips[2].emoji }}</span>
            <span class="mock-dest">{{ cityName(showcaseTrips[2].key) }}</span>
          </div>
          <div class="mock-body">
            <div class="mock-title">{{ cityName(showcaseTrips[2].key) }} · {{ t('landing.daysN', { n: showcaseTrips[2].days }) }}</div>
          </div>
        </div>

        <div class="float-chip chip-ai">
          <span class="live-dot"></span>{{ t('landing.chipAI') }}
        </div>
        <div class="float-chip chip-weather">
          <el-icon :size="13"><Sunny /></el-icon>{{ t('landing.chipWeather') }}
        </div>
        <div class="float-chip chip-budget">
          <el-icon :size="13"><Money /></el-icon>{{ t('landing.chipBudget') }}
        </div>
      </div>
    </section>

    <!-- ── How it works：四卡 ── -->
    <section class="section reveal" id="how">
      <h2 class="section-title">{{ t('landing.howTitle') }}</h2>
      <p class="section-sub">{{ t('landing.howSub') }}</p>
      <div class="feature-grid">
        <article class="feature-card reveal" v-for="(f, i) in features" :key="f.title" :style="{ '--delay': i * 90 + 'ms' }">
          <div class="feature-icon"><el-icon :size="22"><component :is="f.icon" /></el-icon></div>
          <h3>{{ f.title }}</h3>
          <p>{{ f.desc }}</p>
          <div class="tag-row">
            <span class="tag" v-for="tag in f.tags" :key="tag">{{ tag }}</span>
          </div>
        </article>
      </div>
    </section>

    <!-- ── 差异化：编号 timeline 卡 ── -->
    <section class="section section-tint reveal">
      <h2 class="section-title">{{ t('landing.whyTitle') }}</h2>
      <div class="why-grid">
        <article class="why-card reveal" v-for="(w, i) in whyPoints" :key="w.title" :style="{ '--delay': i * 90 + 'ms' }">
          <span class="why-no">{{ i + 1 }}</span>
          <div class="why-icon"><el-icon :size="20"><component :is="w.icon" /></el-icon></div>
          <h3>{{ w.title }}</h3>
          <p>{{ w.desc }}</p>
        </article>
      </div>
    </section>

    <!-- ── 演示：三步 ── -->
    <section class="section reveal">
      <h2 class="section-title">{{ t('landing.demoTitle') }}</h2>
      <p class="section-sub">{{ t('landing.demoSub') }}</p>
      <div class="demo-steps">
        <article class="demo-step reveal" v-for="(s, i) in demoSteps" :key="s.no" :style="{ '--delay': i * 90 + 'ms' }">
          <span class="demo-no">{{ s.no }}</span>
          <h3>{{ s.title }}</h3>
          <p>{{ s.desc }}</p>
        </article>
      </div>
      <div class="demo-cta">
        <button class="btn-primary" @click="startPlanning">
          <el-icon style="margin-right: 6px"><MagicStick /></el-icon>{{ t('landing.demoCta') }}
        </button>
      </div>
    </section>

    <!-- ── 灵感区（示例行程） ── -->
    <section class="section section-tint reveal" id="inspiration">
      <h2 class="section-title">{{ t('landing.inspTitle') }}</h2>
      <p class="section-sub">{{ t('landing.inspSub') }}</p>
      <div class="insp-grid">
        <article class="insp-card reveal" v-for="(trip, i) in showcaseTrips" :key="trip.key" :style="{ '--delay': (i % 3) * 70 + 'ms' }" @click="startPlanning">
          <div class="insp-cover" :style="{ background: trip.hue }">
            <span class="insp-emoji">{{ trip.emoji }}</span>
            <span class="insp-name">{{ cityName(trip.key) }}</span>
            <span class="insp-meta">{{ trip.days }} {{ t('common.days') }} · ¥{{ trip.budget }}</span>
          </div>
          <div class="insp-body">
            <span class="insp-go">{{ t('landing.inspCta') }} →</span>
          </div>
        </article>
      </div>
    </section>

    <!-- ── 社区精选 + 城市模板（task-gallery-featured / city-templates） ── -->
    <section v-if="galleryItems.length || cityTemplates.length" class="section reveal" id="gallery">
      <h2 class="section-title">社区精选与城市模板</h2>
      <p class="section-sub">真实用户分享的路线，或直接用城市模板开工——点一下就复制成你自己的行程。</p>

      <div v-if="cityTemplates.length" class="gallery-block">
        <div class="gallery-block-title">城市模板</div>
        <div class="gallery-grid">
          <article
            v-for="tpl in cityTemplates"
            :key="'tpl-' + tpl.destination"
            class="gallery-card"
            @click="startFromTemplate(tpl)"
          >
            <div class="gallery-emoji">📍</div>
            <div class="gallery-name">{{ tpl.destination }}</div>
            <div class="gallery-meta">{{ tpl.days }} 天 · {{ tpl.budget_tier }} · 约 ¥{{ tpl.est_daily_budget }}/天</div>
            <div class="gallery-cta">用它开工 →</div>
          </article>
        </div>
      </div>

      <div v-if="galleryItems.length" class="gallery-block">
        <div class="gallery-block-title">真实用户分享</div>
        <div class="gallery-grid">
          <article
            v-for="item in galleryItems"
            :key="'g-' + item.trip_id"
            class="gallery-card"
            @click="createFromGallery(item)"
          >
            <div class="gallery-emoji">🗺️</div>
            <div class="gallery-name">{{ item.title }}</div>
            <div class="gallery-meta">{{ item.destination }} · {{ item.days }} 天{{ item.budget ? ' · ¥' + item.budget : '' }}</div>
            <div v-if="item.blurb" class="gallery-blurb">{{ item.blurb }}</div>
            <div class="gallery-cta">以此为基础创建 →</div>
          </article>
        </div>
      </div>
    </section>

    <!-- ── 最终 CTA ── -->
    <section class="final-cta reveal">
      <div class="final-glow"></div>
      <h2>{{ t('landing.finalTitle') }}</h2>
      <p>{{ t('landing.finalSub') }}</p>
      <button class="btn-primary btn-lg" @click="startPlanning">
        <el-icon style="margin-right: 6px"><MagicStick /></el-icon>{{ t('landing.finalCta') }}
      </button>
      <p class="final-note">{{ t('landing.heroNote') }}</p>
    </section>
  </div>
</template>

<style scoped>
.landing { max-width: 1120px; margin: 0 auto; }

/* ── 通用按钮（Landing 此前缺失 .btn-primary/.btn-ghost 定义，补全保持全站一致） ── */
.btn-primary {
  display: inline-flex; align-items: center;
  background: var(--brand); color: #fff;
  border: none; cursor: pointer;
  font-size: 14px; font-weight: 500;
  padding: 11px 20px; border-radius: var(--radius-full);
  box-shadow: 0 2px 10px rgba(255, 56, 92, 0.28);
  transition: background 0.2s, transform 0.15s, box-shadow 0.2s;
}
.btn-primary:hover { background: var(--brand-dark); box-shadow: 0 4px 16px rgba(255, 56, 92, 0.38); transform: translateY(-1px); }
.btn-ghost {
  display: inline-flex; align-items: center;
  background: transparent; border: 1px solid var(--line); cursor: pointer;
  font-size: 14px; font-weight: 500; color: var(--ink-2);
  padding: 11px 20px; border-radius: var(--radius-full);
  transition: border-color 0.2s, color 0.2s;
}
.btn-ghost:hover { border-color: var(--brand); color: var(--brand); }
a.btn-ghost { text-decoration: none; }
.btn-lg { padding: 14px 26px; font-size: 15px; }

/* ── 滚动渐入：默认透明下移，进入视口后浮现；--delay 让同一网格内错峰 ── */
.reveal {
  opacity: 0;
  transform: translateY(22px);
  transition: opacity 0.6s ease, transform 0.6s ease;
  transition-delay: var(--delay, 0ms);
  will-change: opacity, transform;
}
.reveal.visible { opacity: 1; transform: translateY(0); }
@media (prefers-reduced-motion: reduce) {
  .reveal { opacity: 1; transform: none; transition: none; }
}

/* ── Hero ── */
.hero {
  display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 48px; align-items: center;
  padding: 72px 0 56px;
}
.hero-title { font-size: 46px; line-height: 1.2; font-weight: 700; letter-spacing: -0.03em; margin: 0 0 18px; color: var(--ink); }
.hero-title .accent {
  background: linear-gradient(90deg, var(--brand) 0%, #ff8a5c 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero-sub { font-size: 17px; line-height: 1.75; color: var(--muted); margin: 0 0 28px; max-width: 480px; }
.hero-cta { display: flex; gap: 14px; flex-wrap: wrap; }
.hero-note { margin-top: 18px; font-size: 13px; color: var(--faint); }

/* ── Hero 产品示意：Bento 卡片堆叠 + 氛围光晕 + 漂浮 chips ── */
.hero-visual { position: relative; min-height: 440px; }
.glow {
  position: absolute; border-radius: 50%;
  filter: blur(70px); pointer-events: none;
}
.glow-brand { width: 240px; height: 240px; top: 0; left: 8%; background: rgba(255, 56, 92, 0.28); }
.glow-warm { width: 260px; height: 260px; bottom: 0; right: 4%; background: rgba(255, 138, 92, 0.26); }

.mock-trip-card {
  position: absolute; width: 250px; background: var(--surface); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-hover); overflow: hidden; border: 1px solid var(--line);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.mock-trip-card:hover { transform: translateY(-4px) rotate(0deg) scale(1.02); box-shadow: var(--shadow-pop); }
.mock-1 { top: 30px; left: 6%; transform: rotate(-3deg); z-index: 2; width: 272px; }
.mock-2 { top: 8px; right: 2%; transform: rotate(3deg); z-index: 3; width: 210px; }
.mock-3 { top: 210px; right: 10%; transform: rotate(-4deg); z-index: 1; width: 200px; }
.mock-cover { height: 96px; display: flex; align-items: center; justify-content: center; gap: 8px; position: relative; }
.mock-2 .mock-cover { height: 84px; }
.mock-3 .mock-cover { height: 84px; }
.mock-emoji { font-size: 30px; }
.mock-dest { font-size: 20px; font-weight: 700; color: rgba(255,255,255,.95); text-shadow: 0 2px 10px rgba(0,0,0,.12); }
.mock-badge { position: absolute; top: 8px; right: 8px; font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: var(--radius-full); background: rgba(255,255,255,.92); color: var(--success); }
.mock-body { padding: 12px 14px; }
.mock-title { font-size: 14px; font-weight: 600; color: var(--ink); margin-bottom: 8px; }
.mock-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; color: var(--muted); margin-bottom: 10px; }
.mock-dots { display: flex; gap: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line); }
.dot.on { background: var(--brand); }

/* 漂浮 chips：毛玻璃 + 轻缓上下浮动 */
.float-chip {
  position: absolute; z-index: 4;
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: saturate(180%) blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.7);
  box-shadow: var(--shadow-card);
  border-radius: var(--radius-full);
  padding: 7px 14px;
  font-size: 12.5px; font-weight: 600; color: var(--ink-2);
  animation: float-y 5s ease-in-out infinite;
}
.chip-ai { top: 0; left: 34%; animation-delay: 0s; }
.chip-weather { top: 42%; right: -6px; animation-delay: 1.2s; }
.chip-budget { bottom: 14px; left: 30%; animation-delay: 2.1s; }
.live-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 0 0 rgba(13, 138, 95, 0.4);
  animation: live-pulse 2s ease-out infinite;
}
.chip-weather .el-icon, .chip-budget .el-icon { color: var(--brand); }
@keyframes float-y {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-7px); }
}
@keyframes live-pulse {
  0% { box-shadow: 0 0 0 0 rgba(13, 138, 95, 0.4); }
  70% { box-shadow: 0 0 0 7px rgba(13, 138, 95, 0); }
  100% { box-shadow: 0 0 0 0 rgba(13, 138, 95, 0); }
}
@media (prefers-reduced-motion: reduce) {
  .float-chip { animation: none; }
  .live-dot { animation: none; }
  .mock-trip-card { transition: none; }
  .mock-trip-card:hover { transform: none; box-shadow: var(--shadow-hover); }
}

/* ── 通用分区 ── */
.section { padding: 56px 0; }
.section-tint { background: #fff; border-radius: var(--radius-xl); box-shadow: 0 0 0 1px rgba(0,0,0,0.02), 0 8px 30px rgba(0,0,0,0.04); }
.section-title { font-size: 30px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 10px; color: var(--ink); text-align: center; }
.section-sub { font-size: 15px; color: var(--muted); margin: 0 0 36px; text-align: center; line-height: 1.6; }

/* ── 四卡 ── */
.feature-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 18px; }
.feature-card {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 24px; box-shadow: var(--shadow-card); transition: transform .2s, box-shadow .2s;
}
.feature-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }
.feature-icon { width: 44px; height: 44px; border-radius: var(--radius-md); background: var(--brand-soft); color: var(--brand); display: flex; align-items: center; justify-content: center; margin-bottom: 14px; }
.feature-card h3 { font-size: 16px; font-weight: 600; margin: 0 0 8px; color: var(--ink); }
.feature-card p { font-size: 13.5px; line-height: 1.65; color: var(--muted); margin: 0 0 14px; min-height: 66px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 11px; font-weight: 500; color: var(--brand); background: var(--brand-soft); border-radius: var(--radius-full); padding: 4px 10px; }

/* ── 差异化：编号 timeline 卡 ── */
.why-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; }
.why-card {
  position: relative; padding: 24px 24px 22px 56px; border-left: 3px solid var(--brand);
  background: var(--surface); border-radius: 0 var(--radius-md) var(--radius-md) 0;
  transition: transform .2s, box-shadow .2s;
}
.why-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }
.why-no {
  position: absolute; left: 16px; top: 22px;
  font-size: 15px; font-weight: 700; color: var(--brand);
  width: 26px; height: 26px; line-height: 26px; text-align: center;
  background: var(--brand-soft); border-radius: var(--radius-full);
}
.why-icon { color: var(--brand); margin-bottom: 8px; }
.why-card h3 { font-size: 15px; font-weight: 600; margin: 0 0 6px; color: var(--ink); }
.why-card p { font-size: 13.5px; line-height: 1.65; color: var(--muted); margin: 0; }

/* ── 演示三步 ── */
.demo-steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 18px; }
.demo-step { padding: 24px; text-align: center; }
.demo-no { display: inline-block; font-size: 13px; font-weight: 700; color: var(--brand); background: var(--brand-soft); border-radius: var(--radius-full); padding: 4px 14px; margin-bottom: 12px; }
.demo-step h3 { font-size: 16px; font-weight: 600; margin: 0 0 8px; color: var(--ink); }
.demo-step p { font-size: 13.5px; line-height: 1.65; color: var(--muted); margin: 0; }
.demo-cta { text-align: center; margin-top: 28px; }

/* ── 灵感区 ── */
.insp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 16px; }
.insp-card { border-radius: var(--radius-lg); overflow: hidden; border: 1px solid var(--line); background: var(--surface); cursor: pointer; box-shadow: var(--shadow-card); transition: transform .2s, box-shadow .2s; }
.insp-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }
.insp-cover { height: 110px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; position: relative; transition: transform .5s ease; }
.insp-card:hover .insp-cover { transform: scale(1.06); }
.insp-emoji { font-size: 30px; }
.insp-name { font-size: 18px; font-weight: 700; color: rgba(255,255,255,.95); text-shadow: 0 2px 8px rgba(0,0,0,.12); }
.insp-meta { font-size: 11px; color: rgba(255,255,255,.9); background: rgba(0,0,0,.18); padding: 2px 10px; border-radius: var(--radius-full); }
.insp-body { padding: 10px 14px; }
.insp-go { font-size: 13px; font-weight: 600; color: var(--brand); }

/* ── 社区精选 + 城市模板 ── */
.gallery-block { margin-top: 26px; }
.gallery-block-title { font-size: 14px; font-weight: 700; color: var(--ink); margin-bottom: 10px; }
.gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px; }
.gallery-card {
  border: 1px solid var(--line); background: var(--surface); border-radius: var(--radius-lg);
  padding: 14px; cursor: pointer; box-shadow: var(--shadow-card);
  transition: transform .2s, box-shadow .2s;
}
.gallery-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }
.gallery-emoji { font-size: 22px; }
.gallery-name { margin-top: 6px; font-size: 15px; font-weight: 650; color: var(--ink); }
.gallery-meta { margin-top: 4px; font-size: 12px; color: var(--muted); }
.gallery-blurb { margin-top: 6px; font-size: 12.5px; color: var(--ink-2); }
.gallery-cta { margin-top: 10px; font-size: 12.5px; font-weight: 600; color: var(--brand); }

/* ── 最终 CTA ── */
.final-cta { position: relative; text-align: center; padding: 72px 0 28px; overflow: hidden; }
.final-glow {
  position: absolute; left: 50%; top: 40%;
  transform: translate(-50%, -50%);
  width: 480px; height: 320px;
  background: radial-gradient(ellipse at center, rgba(255, 56, 92, 0.13) 0%, rgba(255, 138, 92, 0.08) 45%, transparent 70%);
  pointer-events: none;
}
.final-cta h2 { position: relative; font-size: 32px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 10px; color: var(--ink); }
.final-cta p { position: relative; font-size: 15px; color: var(--muted); margin: 0 0 26px; }
.final-cta .btn-primary { position: relative; }
.final-note { position: relative; margin-top: 16px; font-size: 13px; color: var(--faint); }

/* ── 响应式 ── */
@media (max-width: 860px) {
  .hero { grid-template-columns: 1fr; padding: 40px 0 24px; gap: 36px; }
  .hero-title { font-size: 34px; }
  .hero-visual { min-height: 380px; }
  .mock-trip-card { width: 210px; }
  .mock-1 { width: 230px; left: 4%; }
  .mock-2 { width: 170px; right: 2%; }
  .mock-3 { width: 170px; right: 8%; }
  .chip-ai { left: 30%; }
  .chip-weather { right: 0; }
  .chip-budget { left: 26%; }
}
@media (max-width: 720px) {
  .section { padding: 40px 0; }
  .section-title { font-size: 26px; }
  .final-cta { padding-top: 48px; }
}
</style>