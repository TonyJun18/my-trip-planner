<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

// 刷新后用 /auth/me 校验本地 token 并恢复用户信息；token 失效时 store 会自动登出
onMounted(() => {
  auth.fetchMe()
})

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="app-shell">
    <el-header class="app-header">
      <div class="brand" @click="router.push('/')">
        <span class="brand-logo">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 2C8.5 6.5 6 9.8 6 13.2 6 16.9 8.7 19.5 12 19.5s6-2.6 6-6.3C18 9.8 15.5 6.5 12 2z" fill="currentColor" />
            <circle cx="12" cy="13" r="2.4" fill="#fff" />
            <path d="M4 21h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          </svg>
        </span>
        <span class="brand-text">随行</span>
        <span class="brand-sub">AI 旅行规划</span>
      </div>
      <div class="nav">
        <template v-if="auth.isLoggedIn">
          <button class="nav-link" :class="{ active: $route.path === '/' }" @click="router.push('/')">
            我的行程
          </button>
          <button class="btn-primary" @click="router.push('/plan')">
            <el-icon style="margin-right: 6px"><MagicStick /></el-icon>AI 规划行程
          </button>
          <el-dropdown>
            <span class="user-chip">
              <span class="avatar">{{ (auth.displayName || '旅')[0].toUpperCase() }}</span>
              <span class="user-name">{{ auth.displayName }}</span>
              <el-icon class="chevron"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled class="user-meta">
                  <div>{{ auth.user?.display_name || '旅行者' }}</div>
                  <div class="user-contact">{{ auth.user?.email || auth.user?.phone || '-' }}</div>
                </el-dropdown-item>
                <el-dropdown-item divided @click="logout">
                  <el-icon style="margin-right: 6px"><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
        <template v-else>
          <button class="btn-primary" @click="router.push('/login')">登录 / 注册</button>
        </template>
      </div>
    </el-header>

    <el-main class="app-main">
      <router-view />
    </el-main>

    <footer class="app-footer">
      <div class="footer-inner">
        <span>随行 · AI 旅行规划助手</span>
        <span class="footer-dot">·</span>
        <span>为你的每一次出发，准备好一切</span>
      </div>
    </footer>
  </el-container>
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
  .app-main { padding: 20px 16px 40px; }
  .user-name { display: none; }
}
</style>