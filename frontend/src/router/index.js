import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/AuthView.vue'), meta: { public: true } },
  { path: '/share/:token', name: 'share', component: () => import('@/views/ShareView.vue'), meta: { public: true } },
  { path: '/', name: 'home', component: () => import('@/views/TripListView.vue') },
  { path: '/plan', name: 'plan', component: () => import('@/views/PlanWizard.vue') },
  {
    path: '/trips/:id',
    name: 'trip-detail',
    component: () => import('@/views/TripDetailView.vue'),
    props: true,
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：除 /login 外都需要登录
router.beforeEach((to) => {
  const token = localStorage.getItem('trip_planner_token')
  if (!to.meta.public && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router