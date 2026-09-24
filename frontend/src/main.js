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