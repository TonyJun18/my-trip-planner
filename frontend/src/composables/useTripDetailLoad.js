import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api'
import { readCachedJson } from '@/utils/pwa'

/**
 * 行程详情核心加载域：trip / budget / plan / 离线降级 / 行中快照 / Plan B。
 *
 * 集中管理详情页的加载状态机（在线主路径 + PWA 离线降级），
 * 以及各子域（预算 / AI 方案 / Plan B / 行中）的尽力而为加载。
 *
 * 收藏状态不在此组合（属于 useTripShareActions）；load() 通过
 * ``setCheckFavorite(fn)`` 注入收藏检查（主文件装配层接线）。
 */
export function useTripDetailLoad(opts = {}) {
  const route = useRoute()
  const { t } = useI18n()

  const trip = ref(null)
  const loading = ref(false)
  const budget = ref(null)
  const plan = ref(null)
  const offlineFallback = ref(false)

  // 行中「今日视图」
  const live = ref(null)
  const liveLoading = ref(false)
  const liveOp = ref('')

  // Plan B
  const planB = ref(null)
  const activePlan = ref('main')

  const planOptions = computed(() => [
    { label: t('tripDetail.planMain'), value: 'main' },
    { label: t('tripDetail.planB'), value: 'plan_b' },
  ])

  // 收藏检查注入点（由装配层 setCheckFavorite(share.checkFavorite)）
  let _checkFavorite = async () => {}

  function setCheckFavorite(fn) {
    _checkFavorite = fn || (async () => {})
  }

  // ── 行中操作 ──
  async function loadLive() {
    if (!trip.value?.id || offlineFallback.value) return
    liveLoading.value = true
    try {
      live.value = await api.getLiveSnapshot(trip.value.id)
    } catch {
      live.value = null
    } finally {
      liveLoading.value = false
    }
  }

  async function doCheckStop(stop, checked) {
    if (liveOp.value) return
    liveOp.value = 'check'
    try {
      live.value = await api.checkLiveStop(trip.value.id, stop.id, checked)
      _refreshJourney()
    } catch {
      // 拦截器已 toast；保持原状态等待用户重试
    } finally {
      liveOp.value = ''
    }
  }

  // 行中操作后刷新旅程追踪投影（若调用方注入了 onJourneyChange）
  function _refreshJourney() {
    if (typeof opts.onJourneyChange === 'function') {
      opts.onJourneyChange()
    }
  }

  async function doSkipStop(stop) {
    if (liveOp.value) return
    try {
      await ElMessageBox.confirm(
        t('tripDetail.liveSkipConfirmMsg', { name: stop.name }),
        t('tripDetail.liveSkipConfirmTitle'),
        { type: 'warning' }
      )
    } catch { return }
    liveOp.value = 'skip'
    try {
      live.value = await api.skipLiveStop(trip.value.id, stop.id)
      _refreshJourney()
      await load() // 同步主视图（站点被删）
    } catch {
    } finally {
      liveOp.value = ''
    }
  }

  async function doDelayTrip() {
    if (liveOp.value) return
    try {
      await ElMessageBox.confirm(
        t('tripDetail.liveDelayConfirmMsg'),
        t('tripDetail.liveDelayConfirmTitle'),
        { type: 'warning' }
      )
    } catch { return }
    liveOp.value = 'delay'
    try {
      live.value = await api.delayLiveTrip(trip.value.id)
      _refreshJourney()
      await load()
      ElMessage.success(t('tripDetail.liveDelayed'))
    } catch {
    } finally {
      liveOp.value = ''
    }
  }

  // ── 主加载 ──
  async function load() {
    loading.value = true
    try {
      try {
        trip.value = await api.getTrip(route.params.id)
        offlineFallback.value = false
      } catch (e) {
        const cached = await readCachedJson(`/api/v1/trips/${route.params.id}`)
        if (cached) {
          trip.value = cached
          offlineFallback.value = true
        } else {
          throw e
        }
      }
      if (offlineFallback.value) {
        budget.value = null
        plan.value = null
        planB.value = null
        return
      }
      budget.value = await api.getBudget(route.params.id)
      try {
        plan.value = await api.getTripPlan(route.params.id)
      } catch {
        plan.value = null
      }
      if (activePlan.value === 'main') {
        try {
          const pb = await api.getPlanB(route.params.id)
          planB.value = pb?.variant || null
        } catch {
          planB.value = null // 404/无站点 → 无备选，静默降级
        }
      }
      if (trip.value?.share_token) {
        await _checkFavorite()
      }
      await loadLive()
    } finally {
      loading.value = false
    }
  }

  // Plan B 切换：备选仅作对比预览，不改动当前行程（见 planBHint）
  // 修复：原实现只处理「切回主案」的重载，从未写入 activePlan → 点「备选方案」无反应
  function onPlanChange(p) {
    if (!p || p === activePlan.value) return
    activePlan.value = p
    if (p === 'main') load() // 切回主案：重新拉取权威数据（可能已被 AI 修订）
  }

  return {
    trip, loading, budget, plan, offlineFallback,
    live, liveLoading, liveOp,
    planB, activePlan, planOptions, onPlanChange,
    doCheckStop, doSkipStop, doDelayTrip,
    setCheckFavorite, load, loadLive,
  }
}