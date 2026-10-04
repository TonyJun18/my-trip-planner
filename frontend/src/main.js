import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'leaflet/dist/leaflet.css'
import './styles/theme.css'
import App from './App.vue'
import router from './router'
import i18n from './i18n'

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(i18n)
// El 组件 locale 由 App.vue 的 el-config-provider 响应式提供（随语言切换联动）
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')

// PWA：Service Worker 注册（离线缓存行程详情；生产构建生效，开发环境跳过避免干扰热更新）
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then((reg) => {
      // 新版本就绪提示（task-pwa-cache-deep）：updatefound → 新 SW 安装完成 → 引导刷新
      // 避免「用户正在看旧版本、服务端已发布新版本」的无声滞后。
      let refreshing = false
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (refreshing) return
        refreshing = true
        window.location.reload()
      })

      reg.addEventListener('updatefound', () => {
        const newWorker = reg.installing
        if (!newWorker) return
        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            // 已存在旧 SW 控制（即非首次安装）：提示用户刷新以启用新版本
            import('element-plus').then(({ ElMessageBox }) => {
              ElMessageBox.confirm(
                i18n.global.t('pwa.updateHint'),
                i18n.global.t('pwa.updateTitle'),
                {
                  confirmButtonText: i18n.global.t('pwa.updateNow'),
                  cancelButtonText: i18n.global.t('common.cancel'),
                  type: 'info',
                }
              )
                .then(() => {
                  if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                    newWorker.postMessage('SKIP_WAITING')
                  }
                })
                .catch(() => {}) // 取消：下次访问再提示
            })
          }
        })
      })
    }).catch((err) => {
      console.warn('[pwa] Service Worker 注册失败:', err)
    })
  })
}