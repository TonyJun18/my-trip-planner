<script setup>
// PWA 安装引导（task-mobile-install）
// beforeinstallprompt 非侵入提示：仅登录用户、可关闭、本地标记（dismissed 后不再打扰）
import { onMounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from 'vue-i18n'

const auth = useAuthStore()
const { t } = useI18n()

const PROMPT_KEY = 'pwa_install_prompt_dismissed'
const visible = ref(false)
let deferredPrompt = null

function isStandalone() {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true
  )
}

function dismiss() {
  visible.value = false
  try {
    localStorage.setItem(PROMPT_KEY, '1')
  } catch {
    /* localStorage 不可用时仅本次不提示，不阻塞 */
  }
  if (deferredPrompt) {
    deferredPrompt = null
  }
}

async function install() {
  if (!deferredPrompt) return
  deferredPrompt.prompt()
  try {
    await deferredPrompt.userChoice
  } catch {
    /* 用户忽略或浏览器不支持，静默处理 */
  }
  deferredPrompt = null
  visible.value = false
  try {
    localStorage.setItem(PROMPT_KEY, '1')
  } catch {
    /* ignore */
  }
}

onMounted(() => {
  // Safari/iOS：standalone 时不再提示（已安装到主屏幕）
  if (isStandalone()) return
  try {
    if (localStorage.getItem(PROMPT_KEY)) return
  } catch {
    /* ignore */
  }

  const onBeforeInstallPrompt = (e) => {
    e.preventDefault()
    // 已关闭过（本地标记）→ 不再提示
    try {
      if (localStorage.getItem(PROMPT_KEY)) return
    } catch {
      /* ignore */
    }
    deferredPrompt = e
    // 仅登录用户展示
    if (auth.isLoggedIn) visible.value = true
  }
  window.addEventListener('beforeinstallprompt', onBeforeInstallPrompt)

  // iOS Safari 没有 beforeinstallprompt：登录用户首次访问 6s 后展示一次（可关闭）
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent)
  if (isIOS && !window.matchMedia('(display-mode: standalone)').matches) {
    setTimeout(() => {
      try {
        if (!localStorage.getItem(PROMPT_KEY) && auth.isLoggedIn) visible.value = true
      } catch {
        /* ignore */
      }
    }, 6000)
  }
})
</script>

<template>
  <Transition name="install-fade">
    <div v-if="visible" class="install-prompt" role="dialog" aria-label="install">
      <div class="install-body">
        <div class="install-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 3v10m0 0 4-4m-4 4-4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            <rect x="4" y="14" width="16" height="6" rx="2" stroke="currentColor" stroke-width="1.8" />
          </svg>
        </div>
        <div class="install-text">
          <div class="install-title">{{ t('install.title') }}</div>
          <div class="install-desc">{{ t('install.desc') }}</div>
        </div>
        <div class="install-actions">
          <button class="link-btn" @click="dismiss">{{ t('install.later') }}</button>
          <button class="install-btn" @click="install">{{ t('install.install') }}</button>
        </div>
        <button class="install-close" aria-label="close" @click="dismiss">✕</button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.install-prompt {
  position: fixed;
  left: 50%;
  bottom: 76px;
  transform: translateX(-50%);
  z-index: 1500;
  width: min(420px, calc(100vw - 32px));
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.16);
  padding: 14px 40px 14px 14px;
}
.install-body {
  display: flex;
  align-items: center;
  gap: 12px;
}
.install-icon {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--brand-soft);
  color: var(--brand);
  display: flex;
  align-items: center;
  justify-content: center;
}
.install-text { flex: 1; min-width: 0; }
.install-title { font-size: 14px; font-weight: 600; color: var(--ink); }
.install-desc { font-size: 12px; color: var(--muted); margin-top: 2px; line-height: 1.45; }
.install-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.link-btn {
  background: none; border: none; cursor: pointer;
  font-size: 13px; color: var(--muted); padding: 6px 8px;
}
.install-btn {
  background: var(--brand); color: #fff; border: none; cursor: pointer;
  font-size: 13px; font-weight: 500; padding: 8px 16px;
  border-radius: var(--radius-full);
}
.install-close {
  position: absolute; top: 8px; right: 10px;
  background: none; border: none; cursor: pointer;
  font-size: 13px; color: var(--faint); padding: 4px;
}
.install-fade-enter-active, .install-fade-leave-active { transition: opacity 0.25s, transform 0.25s; }
.install-fade-enter-from, .install-fade-leave-to { opacity: 0; transform: translateX(-50%) translateY(8px); }
@media (max-width: 720px) {
  .install-prompt { bottom: 68px; }
  .install-desc { display: none; }
  .install-actions { gap: 4px; }
  .install-btn { padding: 8px 12px; }
}
</style>