import { createI18n } from 'vue-i18n'
import zhCN from '../locales/zh-CN'
import enUS from '../locales/en-US'

export const SUPPORT_LOCALES = [
  { code: 'zh-CN', label: '中文', el: 'zh-cn' },
  { code: 'en-US', label: 'English', el: 'en' },
]

const STORAGE_KEY = 'locale'

function detectLocale() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && SUPPORT_LOCALES.some((l) => l.code === saved)) return saved
    const nav = (navigator.language || 'zh-CN').toLowerCase()
    if (nav.startsWith('zh')) return 'zh-CN'
  } catch {
    // localStorage 不可用时回退默认
  }
  return 'zh-CN'
}

const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: detectLocale(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

// Element Plus locale 与 vue-i18n 语言联动（供 el-config-provider 使用）
export function elementLocale() {
  const code = i18n.global.locale.value
  const found = SUPPORT_LOCALES.find((l) => l.code === code)
  return found ? found.el : 'zh-cn'
}

export function setLocale(code) {
  if (!SUPPORT_LOCALES.some((l) => l.code === code)) return
  i18n.global.locale.value = code
  try {
    localStorage.setItem(STORAGE_KEY, code)
  } catch {
    // 忽略存储失败
  }
}

export function currentLocale() {
  return i18n.global.locale.value
}

export default i18n