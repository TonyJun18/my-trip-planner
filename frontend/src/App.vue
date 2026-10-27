<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from 'vue-i18n'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import LangSwitcher from '@/components/LangSwitcher.vue'
import { useInstallPrompt } from '@/composables/useInstallPrompt'
import { registerSW } from '@/utils/pwa'

const router = useRouter()
const auth = useAuthStore()
const { t, locale } = useI18n()
const install = useInstallPrompt()

// PWA 更新提示：新版本 SW 就绪 → 非侵入提示引导刷新（task-pwa-cache-deep）
const showUpdatePrompt = ref(false)
let unregisterSW = () => {}

// Element Plus locale 与 vue-i18n 语言联动（el-config-provider 响应式）
const elLocale = computed(() => (locale.value === 'en-US' ? en : zhCn))

// 安装引导仅对登录用户展示（非侵入、可关闭、本地标记）
const showInstallPrompt = computed(() => auth.isLoggedIn && install.shouldShow.value)

// 刷新后用 /auth/me 校验本地 token 并恢复用户信息；token 失效时 store 会自动登出
onMounted(() => {
  auth.fetchMe()
  install.bind()
  // PWA 更新监听：新版本就绪时提示（updatefound + controllerchange 双通道，防时序丢失）
  unregisterSW = registerSW(() => {
    showUpdatePrompt.value = true
  })
})
onBeforeUnmount(() => {
  install.unbind()
  unregisterSW()
})

// 刷新到最新版本（SW 已跳过等待并接管，location.reload 即加载新资源）
function reloadForUpdate() {
  showUpdatePrompt.value = false
  window.location.reload()
}

function logout() {
  auth.logout()
  router.push('/login')
}

// 品牌点击：登录态进我的行程，未登录态回 Landing（产品门面）
function goHome() {
  router.push(auth.isLoggedIn ? '/trips' : '/')
}
</script>

<template>
  <el-config-provider :locale="elLocale">
    <el-container class="app-shell">
      <el-header class="app-header">
        <div class="brand" @click="goHome">
          <span class="brand-logo">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 2C8.5 6.5 6 9.8 6 13.2 6 16.9 8.7 19.5 12 19.5s6-2.6 6-6.3C18 9.8 15.5 6.5 12 2z" fill="currentColor" />
              <circle cx="12" cy="13" r="2.4" fill="#fff" />
              <path d="M4 21h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            </svg>
          </span>
          <span class="brand-text">{{ t('app.brand') }}</span>
          <span class="brand-sub">{{ t('app.brandSub') }}</span>
        </div>
        <div class="nav">
          <template v-if="auth.isLoggedIn">
            <button class="nav-link" :class="{ active: $route.path === '/trips' }" @click="router.push('/trips')">
              {{ t('app.myTrips') }}
            </button>
            <button class="nav-link" :class="{ active: $route.query.view === 'gallery' }" @click="router.push('/?view=gallery')">
              {{ t('app.galleryNav') }}
            </button>
            <button class="btn-primary" @click="router.push('/plan')">
              <el-icon style="margin-right: 6px"><MagicStick /></el-icon>{{ t('app.planTrip') }}
            </button>
            <el-dropdown>
              <span class="user-chip">
                <span class="avatar">{{ (auth.displayName || t('app.traveler'))[0].toUpperCase() }}</span>
                <span class="user-name">{{ auth.displayName || t('app.traveler') }}</span>
                <el-icon class="chevron"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item disabled class="user-meta">
                    <div>{{ auth.user?.display_name || t('app.traveler') }}</div>
                    <div class="user-contact">{{ auth.user?.email || auth.user?.phone || '-' }}</div>
                  </el-dropdown-item>
                  <el-dropdown-item divided @click="logout">
                    <el-icon style="margin-right: 6px"><SwitchButton /></el-icon>{{ t('app.logout') }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
          <template v-else>
            <a class="nav-link" href="#how">{{ t('app.features') }}</a>
            <a class="nav-link" href="#inspiration">{{ t('app.inspiration') }}</a>
            <button class="btn-primary" @click="router.push('/login')">{{ t('app.loginRegister') }}</button>
          </template>
          <LangSwitcher />
        </div>
      </el-header>

      <el-main class="app-main">
        <router-view />
      </el-main>

      <footer class="app-footer">
        <div class="footer-inner">
          <span>{{ t('app.brand') }} · {{ t('app.brandSub') }}</span>
          <span class="footer-dot">·</span>
          <span>{{ t('app.tagline') }}</span>
        </div>
      </footer>

      <!-- 移动端底部 Tab（仅登录态，≤720px 显示） -->
      <nav v-if="auth.isLoggedIn" class="mobile-tabbar" aria-label="mobile-nav">
        <button
          class="tab-item"
          :class="{ active: $route.path === '/trips' }"
          @click="router.push('/trips')"
        >
          <el-icon :size="22"><Van /></el-icon>
          <span class="tab-label">{{ t('app.myTrips') }}</span>
        </button>
        <button
          class="tab-item"
          :class="{ active: $route.path === '/plan' }"
          @click="router.push('/plan')"
        >
          <el-icon :size="22"><MagicStick /></el-icon>
          <span class="tab-label">{{ t('app.planTrip') }}</span>
        </button>
      </nav>

      <!-- PWA 更新提示（task-pwa-cache-deep）：新版本已就绪 → 引导刷新 -->
      <div v-if="showUpdatePrompt" class="update-prompt" role="alert" aria-label="update prompt">
        <span class="up-icon"><el-icon :size="18"><RefreshRight /></el-icon></span>
        <div class="up-body">
          <div class="up-title">{{ t('common.updatePromptTitle') }}</div>
          <div class="up-desc">{{ t('common.updatePromptDesc') }}</div>
        </div>
        <button class="up-action" @click="reloadForUpdate">{{ t('common.updateAction') }}</button>
        <button class="up-dismiss" aria-label="dismiss" @click="showUpdatePrompt = false">
          <el-icon :size="14"><Close /></el-icon>
        </button>
      </div>

      <!-- PWA 安装引导（仅登录用户、可关闭、本地标记不再打扰） -->
      <div v-if="showInstallPrompt" class="install-prompt" role="dialog" aria-label="install prompt">
        <span class="ip-icon"><el-icon :size="18"><Download /></el-icon></span>
        <div class="ip-body">
          <div class="ip-title">{{ t('common.installPromptTitle') }}</div>
          <div class="ip-desc">{{ t('common.installPromptDesc') }}</div>
        </div>
        <button class="ip-action" @click="install.install()">{{ t('common.installAction') }}</button>
        <button class="ip-dismiss" aria-label="dismiss" @click="install.dismiss()">
          <el-icon :size="14"><Close /></el-icon>
        </button>
      </div>
    </el-container>
  </el-config-provider>
</template>

<style scoped>
.app-shell { min-height: 100vh; display: flex; flex-direction: column; }

/* ── 顶栏 ── */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: saturate(180%) blur(12px);
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  z-index: 1000;
  height: 64px;
  padding: 0 28px;
}
.brand { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.brand-logo { color: var(--brand); display: flex; }
.brand-text {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
}
.brand-sub {
  font-size: 12px;
  color: var(--muted);
  margin-left: 2px;
  margin-top: 3px;
}

.nav { display: flex; align-items: center; gap: 14px; }
.nav-link {
  background: none; border: none; cursor: pointer;
  font-size: 14px; font-weight: 500; color: var(--ink-2);
  padding: 8px 12px; border-radius: var(--radius-full);
  transition: background 0.2s, color 0.2s;
}
.nav-link:hover { background: var(--fill); }
.nav-link.active { background: var(--brand-soft); color: var(--brand); }

.btn-primary {
  display: inline-flex; align-items: center;
  background: var(--brand); color: #fff;
  border: none; cursor: pointer;
  font-size: 14px; font-weight: 500;
  padding: 10px 18px;
  border-radius: var(--radius-full);
  box-shadow: 0 2px 10px rgba(255, 56, 92, 0.28);
  transition: background 0.2s, transform 0.15s, box-shadow 0.2s;
}
.btn-primary:hover { background: var(--brand-dark); box-shadow: 0 4px 16px rgba(255, 56, 92, 0.38); transform: translateY(-1px); }

.user-chip {
  display: flex; align-items: center; gap: 8px;
  cursor: pointer; padding: 4px 6px 4px 4px;
  border-radius: var(--radius-full);
  border: 1px solid var(--line);
  background: #fff;
  transition: box-shadow 0.2s;
}
.user-chip:hover { box-shadow: var(--shadow-card); }
.avatar {
  width: 30px; height: 30px; border-radius: 50%;
  background: linear-gradient(135deg, var(--brand), #ff8a5c);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-weight: 600; font-size: 14px;
}
.user-name { font-size: 13px; color: var(--ink-2); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chevron { font-size: 12px; color: var(--faint); }
.user-meta { display: flex; flex-direction: column; gap: 2px; }
.user-contact { font-size: 12px; color: var(--faint); }

/* ── 主内容 ── */
.app-main {
  flex: 1;
  padding: 32px 28px 48px;
  max-width: 1240px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

/* ── 页脚 ── */
.app-footer {
  border-top: 1px solid var(--line);
  background: #fff;
  padding: 20px 28px;
}
.footer-inner {
  max-width: 1240px; margin: 0 auto;
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--faint);
}
.footer-dot { opacity: 0.5; }

/* ── 响应式 ── */
@media (max-width: 720px) {
  .app-header { padding: 0 16px; height: 56px; }
  .brand-sub { display: none; }
  .app-main { padding: 20px 16px 56px; } /* 底部 Tab 高度 + 余量，避免内容被遮挡 */
  .user-name { display: none; }
  .app-footer { display: none; }

  /* 顶栏窄屏进一步压缩：登录态隐藏「我的行程」文字导航（Tab 已有），仅保留品牌 + 新建 + 语言 + 用户 */
  .nav .nav-link { display: none; }
  .nav .btn-primary { padding: 8px 12px; font-size: 13px; }
}

/* ── 移动端底部 Tab（≤720px）── */
.mobile-tabbar {
  display: none;
}
@media (max-width: 720px) {
  .mobile-tabbar {
    display: flex;
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1200;
    height: 56px;
    padding-bottom: env(safe-area-inset-bottom);
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: saturate(180%) blur(12px);
    border-top: 1px solid var(--line);
    box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.04);
  }
  .tab-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    background: none;
    border: none;
    cursor: pointer;
    color: var(--faint);
    font-size: 11px;
    padding: 4px 0 6px;
    transition: color 0.2s;
  }
  .tab-item.active { color: var(--brand); }
  .tab-label { line-height: 1; }
}

/* ── PWA 更新提示（task-pwa-cache-deep）：新版本就绪 → 非侵入引导刷新 ── */
.update-prompt {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  top: 80px; /* 让位顶栏（64px） */
  z-index: 1300;
  display: flex;
  align-items: center;
  gap: 12px;
  width: min(480px, calc(100vw - 24px));
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.97);
  backdrop-filter: saturate(180%) blur(12px);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.12);
  animation: update-prompt-in 0.25s ease-out;
}
@keyframes update-prompt-in {
  from { opacity: 0; transform: translateX(-50%) translateY(-8px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
.up-icon {
  flex-shrink: 0;
  width: 34px; height: 34px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand);
}
.up-body { flex: 1; min-width: 0; }
.up-title { font-size: 14px; font-weight: 600; color: var(--ink); }
.up-desc {
  font-size: 12px; color: var(--muted);
  margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.up-action {
  flex-shrink: 0;
  background: var(--brand); color: #fff;
  border: none; cursor: pointer;
  font-size: 13px; font-weight: 500;
  padding: 8px 14px;
  border-radius: var(--radius-full);
  transition: background 0.2s;
}
.up-action:hover { background: var(--brand-dark); }
.up-dismiss {
  flex-shrink: 0;
  background: none; border: none; cursor: pointer;
  color: var(--faint);
  padding: 4px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 50%;
  transition: color 0.2s, background 0.2s;
}
.up-dismiss:hover { color: var(--ink-2); background: var(--fill); }
@media (max-width: 480px) {
  .update-prompt { top: 68px; }
  .up-desc { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
}

/* ── PWA 安装引导（task-mobile-install）── */
.install-prompt {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: 72px; /* 让位底部 Tab（56px + safe-area） */
  z-index: 1300;
  display: flex;
  align-items: center;
  gap: 12px;
  width: min(480px, calc(100vw - 24px));
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.97);
  backdrop-filter: saturate(180%) blur(12px);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.12);
  animation: install-prompt-in 0.25s ease-out;
}
@keyframes install-prompt-in {
  from { opacity: 0; transform: translateX(-50%) translateY(8px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
.ip-icon {
  flex-shrink: 0;
  width: 34px; height: 34px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand);
}
.ip-body { flex: 1; min-width: 0; }
.ip-title { font-size: 14px; font-weight: 600; color: var(--ink); }
.ip-desc {
  font-size: 12px; color: var(--muted);
  margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ip-action {
  flex-shrink: 0;
  background: var(--brand); color: #fff;
  border: none; cursor: pointer;
  font-size: 13px; font-weight: 500;
  padding: 8px 14px;
  border-radius: var(--radius-full);
  transition: background 0.2s;
}
.ip-action:hover { background: var(--brand-dark); }
.ip-dismiss {
  flex-shrink: 0;
  background: none; border: none; cursor: pointer;
  color: var(--faint);
  padding: 4px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 50%;
  transition: color 0.2s, background 0.2s;
}
.ip-dismiss:hover { color: var(--ink-2); background: var(--fill); }
@media (max-width: 480px) {
  .install-prompt { bottom: 64px; }
  .ip-desc { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
}
</style>