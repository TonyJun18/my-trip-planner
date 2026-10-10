// PWA 安装引导（task-mobile-install）
// 非侵入策略：
// - 仅登录用户可见（由调用方控制）
// - 可关闭，关闭后本地标记不再打扰（localStorage）
// - 已运行于 standalone（桌面安装 / iOS 添加到主屏幕）不显示
// - iOS Safari 无 beforeinstallprompt 事件，靠 apple-touch-icon 引导手动添加到主屏幕
import { ref, computed } from 'vue'

const LS_DISMISS_KEY = 'pwa_install_dismissed'

export function useInstallPrompt() {
  const deferredPrompt = ref(null)
  const dismissed = ref(false)

  // 本地标记延迟到模块可用时再读（SSR 无关，纯浏览器环境，直接读亦可）
  if (typeof window !== 'undefined') {
    dismissed.value = localStorage.getItem(LS_DISMISS_KEY) === '1'
  }

  const isStandalone = computed(() => {
    if (typeof window === 'undefined') return false
    // Android/Desktop Chrome 安装后：display-mode: standalone
    // iOS Safari 添加到主屏幕后：navigator.standalone === true
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true
    )
  })

  function onBeforeInstallPrompt(e) {
    // 拦截默认浏览器安装条，改由我们的自定义引导触发（避免双提示）
    e.preventDefault()
    deferredPrompt.value = e
  }

  function onAppInstalled() {
    deferredPrompt.value = null
  }

  function bind() {
    if (typeof window === 'undefined') return
    window.addEventListener('beforeinstallprompt', onBeforeInstallPrompt)
    window.addEventListener('appinstalled', onAppInstalled)
  }

  function unbind() {
    if (typeof window === 'undefined') return
    window.removeEventListener('beforeinstallprompt', onBeforeInstallPrompt)
    window.removeEventListener('appinstalled', onAppInstalled)
  }

  /** 浏览器已触发可安装事件（Chrome/Edge 等支持 beforeinstallprompt 的现代浏览器） */
  const canPrompt = computed(() => !!deferredPrompt.value)

  /** 是否应当展示安装引导（由调用方叠加登录态） */
  const shouldShow = computed(() => !dismissed.value && !isStandalone.value && canPrompt.value)

  /** 触发浏览器原生安装流程 */
  async function install() {
    if (!deferredPrompt.value) return false
    const prompt = deferredPrompt.value
    deferredPrompt.value = null
    try {
      await prompt.prompt()
      await prompt.userChoice
      return true
    } catch {
      // 用户取消或浏览器拒绝，静默退回（不打扰）
      return false
    }
  }

  /** 用户关闭引导：本地标记，本机不再展示 */
  function dismiss() {
    dismissed.value = true
    if (typeof window !== 'undefined') {
      localStorage.setItem(LS_DISMISS_KEY, '1')
    }
  }

  return { isStandalone, canPrompt, shouldShow, bind, unbind, install, dismiss }
}