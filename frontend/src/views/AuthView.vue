<script setup>
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from 'vue-i18n'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const { t } = useI18n()

const mode = ref('login')
const loading = ref(false)
const formRef = ref(null)

const form = reactive({
  account: '',
  email: '',
  phone: '',
  password: '',
  display_name: '',
})

const loginRules = {
  account: [{ required: true, message: t('auth.emailRequired'), trigger: 'blur' }],
  password: [{ required: true, message: t('auth.passwordRequired'), trigger: 'blur' }],
}
const registerRules = {
  password: [
    { required: true, message: t('auth.passwordRequired'), trigger: 'blur' },
    { min: 8, message: t('auth.passwordMin'), trigger: 'blur' },
  ],
}

async function submit() {
  await formRef.value.validate()
  loading.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(form.account, form.password)
      ElMessage.success(t('auth.loginSuccess'))
    } else {
      const payload = {
        email: form.email || null,
        phone: form.phone || null,
        password: form.password,
        display_name: form.display_name || null,
      }
      if (!payload.email && !payload.phone) {
        ElMessage.warning(t('auth.orRequired'))
        loading.value = false
        return
      }
      await auth.register(payload)
      ElMessage.success(t('auth.registerSuccess'))
    }
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } catch {
    // 错误已由拦截器提示
  } finally {
    loading.value = false
  }
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  formRef.value?.clearValidate()
}
</script>

<template>
  <div class="auth-page">
    <!-- 左侧品牌氛围 -->
    <div class="auth-visual">
      <div class="visual-content">
        <div class="visual-logo">
          <span class="logo-dot">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 2C8.5 6.5 6 9.8 6 13.2 6 16.9 8.7 19.5 12 19.5s6-2.6 6-6.3C18 9.8 15.5 6.5 12 2z" fill="currentColor" />
              <circle cx="12" cy="13" r="2.4" fill="#fff" />
              <path d="M4 21h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            </svg>
          </span>
          <span class="visual-brand">{{ t('app.brand') }}</span>
        </div>
        <h1 class="visual-title">{{ t('auth.visualTitle1') }}<br />{{ t('auth.visualTitle2') }}</h1>
        <p class="visual-sub">{{ t('auth.visualSub1') }}<br />{{ t('auth.visualSub2') }}</p>
        <div class="visual-features">
          <div class="feat"><span class="feat-icon">🧭</span> {{ t('auth.featPlan') }}</div>
          <div class="feat"><span class="feat-icon">🌤️</span> {{ t('auth.featWeather') }}</div>
          <div class="feat"><span class="feat-icon">🗺️</span> {{ t('auth.featMap') }}</div>
        </div>
      </div>
    </div>

    <!-- 右侧表单 -->
    <div class="auth-form-side">
      <el-card class="auth-card" shadow="never">
        <h2 class="auth-title">{{ mode === 'login' ? t('auth.welcomeBack') : t('auth.createAccount') }}</h2>
        <p class="auth-sub">
          {{ mode === 'login' ? t('auth.loginSub') : t('auth.registerSub') }}
        </p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="mode === 'login' ? loginRules : registerRules"
          label-position="top"
          @keyup.enter="submit"
        >
          <!-- 登录：账号 -->
          <el-form-item v-if="mode === 'login'" :label="t('auth.account')" prop="account">
            <el-input v-model="form.account" :placeholder="t('auth.accountPlaceholder')" size="large" />
          </el-form-item>

          <!-- 注册：邮箱 + 手机号 -->
          <template v-else>
            <el-form-item :label="t('auth.email')" prop="email">
              <el-input v-model="form.email" placeholder="you@example.com" size="large" />
            </el-form-item>
            <el-form-item :label="t('auth.phone')" prop="phone">
              <el-input v-model="form.phone" placeholder="13800138000" size="large" />
            </el-form-item>
            <el-form-item :label="t('auth.nickname')" prop="display_name">
              <el-input v-model="form.display_name" :placeholder="t('auth.nicknamePlaceholder')" size="large" />
            </el-form-item>
            <div class="or-divider">{{ t('auth.orRequired') }}</div>
          </template>

          <el-form-item :label="t('auth.password')" prop="password">
            <el-input v-model="form.password" type="password" show-password size="large" :placeholder="t('auth.passwordPlaceholder')" />
          </el-form-item>

          <button class="submit-btn" :disabled="loading" @click.prevent="submit">
            <el-icon v-if="loading" class="is-loading" style="margin-right: 6px"><Loading /></el-icon>
            {{ mode === 'login' ? t('auth.login') : t('auth.register') }}
          </button>
        </el-form>

        <div class="switch-line">
          {{ mode === 'login' ? t('auth.noAccount') : t('auth.hasAccount') }}
          <a class="switch-link" @click="switchMode">{{ mode === 'login' ? t('auth.goRegister') : t('auth.goLogin') }}</a>
        </div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  display: grid; grid-template-columns: 1.1fr 1fr;
  min-height: calc(100vh - 64px - 62px); /* 顶栏 + 页脚 */
  gap: 0;
}

/* ── 左：品牌视觉 ── */
.auth-visual {
  background: linear-gradient(135deg, #ff9a9e 0%, #ff6f91 40%, #a18cd1 100%);
  display: flex; align-items: center; justify-content: center;
  padding: 48px;
  border-radius: 0 var(--radius-xl) var(--radius-xl) 0;
  position: relative; overflow: hidden;
}
.auth-visual::before {
  content: ''; position: absolute; width: 300px; height: 300px;
  border-radius: 50%; background: rgba(255,255,255,0.08);
  top: -60px; right: -60px;
}
.auth-visual::after {
  content: ''; position: absolute; width: 200px; height: 200px;
  border-radius: 50%; background: rgba(255,255,255,0.06);
  bottom: -40px; left: -40px;
}
.visual-content { position: relative; z-index: 1; max-width: 400px; color: #fff; }
.visual-logo { display: flex; align-items: center; gap: 10px; margin-bottom: 32px; }
.logo-dot {
  width: 40px; height: 40px; border-radius: 50%;
  background: rgba(255,255,255,0.2); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center; color: #fff;
}
.visual-brand { font-size: 22px; font-weight: 700; letter-spacing: 0.02em; }
.visual-title { font-size: 34px; font-weight: 700; line-height: 1.3; margin: 0 0 14px; letter-spacing: -0.02em; text-shadow: 0 2px 16px rgba(0,0,0,0.1); }
.visual-sub { font-size: 15px; line-height: 1.7; opacity: 0.92; margin: 0 0 32px; }
.visual-features { display: flex; flex-direction: column; gap: 12px; }
.feat {
  display: flex; align-items: center; gap: 10px;
  background: rgba(255,255,255,0.14); backdrop-filter: blur(6px);
  border-radius: var(--radius-full); padding: 10px 18px;
  font-size: 14px; font-weight: 500; width: fit-content;
}
.feat-icon { font-size: 16px; }

/* ── 右：表单 ── */
.auth-form-side {
  display: flex; align-items: center; justify-content: center; padding: 40px 24px;
}
.auth-card {
  width: 400px; max-width: 100%;
  border-radius: var(--radius-xl);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-card);
  padding: 8px 10px;
}
.auth-title { margin: 10px 0 4px; text-align: center; font-size: 26px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); }
.auth-sub { text-align: center; color: var(--muted); font-size: 13.5px; margin: 0 0 24px; }
.or-divider { text-align: center; color: var(--faint); font-size: 12px; margin: -6px 0 14px; }

.submit-btn {
  width: 100%; padding: 13px; margin-top: 4px;
  background: var(--brand); color: #fff; border: none; cursor: pointer;
  border-radius: var(--radius-full);
  font-size: 16px; font-weight: 600;
  box-shadow: 0 4px 14px rgba(255,56,92,0.3);
  transition: all .2s;
  display: inline-flex; align-items: center; justify-content: center;
}
.submit-btn:hover:not(:disabled) { background: var(--brand-dark); transform: translateY(-1px); box-shadow: 0 6px 20px rgba(255,56,92,0.4); }
.submit-btn:disabled { opacity: .65; cursor: not-allowed; }

.switch-line { margin-top: 18px; text-align: center; font-size: 14px; color: var(--ink-2); }
.switch-link { color: var(--brand); cursor: pointer; font-weight: 500; }
.switch-link:hover { text-decoration: underline; }

/* 响应式 */
@media (max-width: 860px) {
  .auth-page { grid-template-columns: 1fr; }
  .auth-visual { display: none; }
  .auth-form-side { padding: 32px 16px; }
}
</style>