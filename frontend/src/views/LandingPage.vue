<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const { t } = useI18n()
const auth = useAuthStore()

// 已登录用户访问产品门面 → 直接进「我的行程」（门面面向陌生访客）
onMounted(() => {
  if (auth.isLoggedIn) router.replace('/trips')
})

// 主 CTA：已登录直接进规划，未登录带去登录并回跳 /plan
function startPlanning() {
  if (auth.isLoggedIn) router.push('/plan')
  else router.push('/login?redirect=/plan')
}

// 灵感区：示例行程（静态示意，B 阶段接后端精选接口后可替换）
const showcaseTrips = [
  { dest: '杭州', days: 3, budget: 3000, emoji: '🍃', hue: 'linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%)' },
  { dest: '成都', days: 4, budget: 4000, emoji: '🐼', hue: 'linear-gradient(135deg, #f6d365 0%, #fda085 100%)' },
  { dest: '大理', days: 5, budget: 5000, emoji: '🏔️', hue: 'linear-gradient(135deg, #a1c4fd 0%, #c2e9fb 100%)' },
  { dest: '厦门', days: 3, budget: 2500, emoji: '🌊', hue: 'linear-gradient(135deg, #fbc2eb 0%, #a6c1ee 100%)' },
  { dest: '西安', days: 4, budget: 3500, emoji: '🏛️', hue: 'linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%)' },
  { dest: '三亚', days: 5, budget: 6000, emoji: '🏝️', hue: 'linear-gradient(135deg, #fddb92 0%, #e6b0f4 100%)' },
]

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

      <!-- 产品示意面板（真实组件风格复刻，B 阶段可替换为可交互试玩） -->
      <div class="hero-visual" aria-hidden="true">
        <div class="mock-trip-card" v-for="(trip, i) in showcaseTrips.slice(0, 3)" :key="trip.dest" :class="`mock-${i + 1}`">
          <div class="mock-cover" :style="{ background: trip.hue }">
            <span class="mock-emoji">{{ trip.emoji }}</span>
            <span class="mock-dest">{{ trip.dest }}</span>
            <span class="mock-badge">{{ t('landing.statusConfirmed') }}</span>
          </div>
          <div class="mock-body">
            <div class="mock-title">{{ trip.dest }} · {{ t('landing.daysN', { n: trip.days }) }}</div>
            <div class="mock-meta">
              <span>📅 {{ t('landing.dateRangeSample') }}</span>
              <span>👥 2 {{ t('common.people') }}</span>
              <span>💰 ¥{{ trip.budget }}</span>
            </div>
            <div class="mock-dots">
              <span v-for="n in 5" :key="n" class="dot" :class="{ on: n <= trip.days }" />
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ── How it works：四卡 ── -->
    <section class="section" id="how">
      <h2 class="section-title">{{ t('landing.howTitle') }}</h2>
      <p class="section-sub">{{ t('landing.howSub') }}</p>
      <div class="feature-grid">
        <article class="feature-card" v-for="f in features" :key="f.title">
          <div class="feature-icon"><el-icon :size="22"><component :is="f.icon" /></el-icon></div>
          <h3>{{ f.title }}</h3>
          <p>{{ f.desc }}</p>
          <div class="tag-row">
            <span class="tag" v-for="tag in f.tags" :key="tag">{{ tag }}</span>
          </div>
        </article>
      </div>
    </section>

    <!-- ── 差异化 ── -->
    <section class="section section-tint">
      <h2 class="section-title">{{ t('landing.whyTitle') }}</h2>
      <div class="why-grid">
        <article class="why-card" v-for="w in whyPoints" :key="w.title">
          <div class="why-icon"><el-icon :size="20"><component :is="w.icon" /></el-icon></div>
          <h3>{{ w.title }}</h3>
          <p>{{ w.desc }}</p>
        </article>
      </div>
    </section>

    <!-- ── 演示：三步 ── -->
    <section class="section">
      <h2 class="section-title">{{ t('landing.demoTitle') }}</h2>
      <p class="section-sub">{{ t('landing.demoSub') }}</p>
      <div class="demo-steps">
        <article class="demo-step" v-for="s in demoSteps" :key="s.no">
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
    <section class="section section-tint" id="inspiration">
      <h2 class="section-title">{{ t('landing.inspTitle') }}</h2>
      <p class="section-sub">{{ t('landing.inspSub') }}</p>
      <div class="insp-grid">
        <article class="insp-card" v-for="trip in showcaseTrips" :key="trip.dest" @click="startPlanning">
          <div class="insp-cover" :style="{ background: trip.hue }">
            <span class="insp-emoji">{{ trip.emoji }}</span>
            <span class="insp-name">{{ trip.dest }}</span>
            <span class="insp-meta">{{ trip.days }} {{ t('common.days') }} · ¥{{ trip.budget }}</span>
          </div>
          <div class="insp-body">
            <span class="insp-go">{{ t('landing.inspCta') }} →</span>
          </div>
        </article>
      </div>
    </section>

    <!-- ── 最终 CTA ── -->
    <section class="final-cta">
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

/* ── Hero ── */
.hero {
  display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 48px; align-items: center;
  padding: 72px 0 56px;
}
.hero-title { font-size: 46px; line-height: 1.2; font-weight: 700; letter-spacing: -0.03em; margin: 0 0 18px; color: var(--ink); }
.hero-title .accent { color: var(--brand); }
.hero-sub { font-size: 17px; line-height: 1.75; color: var(--muted); margin: 0 0 28px; max-width: 480px; }
.hero-cta { display: flex; gap: 14px; flex-wrap: wrap; }
.btn-lg { padding: 14px 26px; font-size: 15px; }
a.btn-ghost { text-decoration: none; display: inline-flex; align-items: center; }
.hero-note { margin-top: 18px; font-size: 13px; color: var(--faint); }

/* ── Hero 产品示意 ── */
.hero-visual { position: relative; min-height: 380px; }
.mock-trip-card {
  position: absolute; width: 250px; background: var(--surface); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-hover); overflow: hidden; border: 1px solid var(--line);
}
.mock-1 { top: 0; left: 12%; transform: rotate(-4deg); z-index: 2; }
.mock-2 { top: 90px; left: 40%; transform: rotate(3deg); z-index: 3; }
.mock-3 { top: 200px; left: 8%; transform: rotate(6deg); z-index: 1; }
.mock-cover { height: 96px; display: flex; align-items: center; justify-content: center; gap: 8px; position: relative; }
.mock-emoji { font-size: 30px; }
.mock-dest { font-size: 20px; font-weight: 700; color: rgba(255,255,255,.95); text-shadow: 0 2px 10px rgba(0,0,0,.12); }
.mock-badge { position: absolute; top: 8px; right: 8px; font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: var(--radius-full); background: rgba(255,255,255,.92); color: var(--success); }
.mock-body { padding: 12px 14px; }
.mock-title { font-size: 14px; font-weight: 600; color: var(--ink); margin-bottom: 8px; }
.mock-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; color: var(--muted); margin-bottom: 10px; }
.mock-dots { display: flex; gap: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line); }
.dot.on { background: var(--brand); }

/* ── 通用分区 ── */
.section { padding: 56px 0; }
.section-tint { background: #fff; border-radius: var(--radius-xl); }
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

/* ── 差异化 ── */
.why-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; }
.why-card { padding: 20px 24px; border-left: 3px solid var(--brand); background: var(--surface); border-radius: 0 var(--radius-md) var(--radius-md) 0; }
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
.insp-cover { height: 110px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; position: relative; }
.insp-emoji { font-size: 30px; }
.insp-name { font-size: 18px; font-weight: 700; color: rgba(255,255,255,.95); text-shadow: 0 2px 8px rgba(0,0,0,.12); }
.insp-meta { font-size: 11px; color: rgba(255,255,255,.9); background: rgba(0,0,0,.18); padding: 2px 10px; border-radius: var(--radius-full); }
.insp-body { padding: 10px 14px; }
.insp-go { font-size: 13px; font-weight: 600; color: var(--brand); }

/* ── 最终 CTA ── */
.final-cta { text-align: center; padding: 64px 0 20px; }
.final-cta h2 { font-size: 32px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 10px; color: var(--ink); }
.final-cta p { font-size: 15px; color: var(--muted); margin: 0 0 26px; }
.final-note { margin-top: 16px; font-size: 13px; color: var(--faint); }

/* ── 响应式 ── */
@media (max-width: 860px) {
  .hero { grid-template-columns: 1fr; padding: 40px 0 24px; gap: 36px; }
  .hero-title { font-size: 34px; }
  .hero-visual { min-height: 300px; }
  .mock-trip-card { width: 210px; }
  .mock-1 { left: 4%; }
  .mock-2 { left: 34%; }
  .mock-3 { left: 0; }
}
@media (max-width: 720px) {
  .section { padding: 40px 0; }
  .section-title { font-size: 26px; }
  .final-cta { padding-top: 44px; }
}
</style>