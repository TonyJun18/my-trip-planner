/**
 * 行程事件流（task-trip-event-notify · 主动通知最小版）
 *
 * - 轮询后端事件流（30s，页面可见时才轮询），展示修订/打卡/跳过/顺延/评论/投票；
 * - 未读红点：localStorage `events:{tripId}:readAt` 记录上次已读时间，新事件计数；
 * - PWA Notification：已授权时，页面在后台（document.hidden）收到新事件 → 系统通知；
 * - 零新依赖：纯轮询 + Notification API（不引 WS，复用后端既有事件端点）。
 *
 * 两种模式：owner（tripId）/ 分享页（shareToken 免登录）。
 */
<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import * as api from '@/api'

const props = defineProps({
  tripId: { type: String, default: '' },
  shareToken: { type: String, default: '' },
})

const { t } = useI18n()

const items = ref([])
const expanded = ref(false)
const lastReadAt = ref(0)
const notifySupported = ref(false)
const notifyGranted = ref(false)
let timer = null

const storageKey = computed(() => `events:${props.tripId || props.shareToken || 'anon'}:readAt`)

const unread = computed(() =>
  items.value.filter((e) => new Date(e.created_at || 0).getTime() > lastReadAt.value).length
)

const eventLabel = (type) => {
  const key = `events.type.${type}`
  const label = t(key)
  return label === key ? type : label
}

const eventText = (ev) => {
  const p = ev.payload || {}
  switch (ev.event_type) {
    case 'check':
      return p.checked === false
        ? t('events.desc.uncheck', { name: p.name || '' })
        : t('events.desc.check', { name: p.name || '' })
    case 'skip':
      return t('events.desc.skip', { name: p.name || '' })
    case 'delay':
      return t('events.desc.delay', { days: p.days_shifted || 1 })
    case 'revise':
      return t('events.desc.revise', { summary: p.summary || p.message || '' })
    case 'comment':
      return t('events.desc.comment', { content: p.content || '' })
    case 'vote':
      return t('events.desc.vote', { value: p.value === 'up' ? '👍' : '👎' })
    default:
      return ''
  }
}

const timeText = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function load() {
  try {
    const data = props.shareToken
      ? await api.getSharedTripEvents(props.shareToken, { limit: 20 })
      : await api.getTripEvents(props.tripId, { limit: 20 })
    const fresh = data.items || []
    // 后台时给新事件发系统通知（已授权才发）
    if (notifyGranted.value && document.hidden && fresh.length) {
      const newest = new Date(fresh[0].created_at || 0).getTime()
      if (newest > lastReadAt.value) {
        try {
          new Notification(t('events.notifyTitle'), {
            body: `${eventLabel(fresh[0].event_type)}：${eventText(fresh[0]) || ''}`,
            tag: `trip-${props.tripId || props.shareToken}`,
          })
        } catch { /* 通知失败静默 */ }
      }
    }
    items.value = fresh
  } catch {
    // 事件流失败静默（不打扰主流程）
  }
}

function markRead() {
  lastReadAt.value = Date.now()
  try {
    localStorage.setItem(storageKey.value, String(lastReadAt.value))
  } catch { /* 存储失败静默 */ }
}

async function enableNotify() {
  if (!('Notification' in window)) return
  const perm = await Notification.requestPermission()
  notifyGranted.value = perm === 'granted'
}

function toggle() {
  expanded.value = !expanded.value
  if (expanded.value) markRead()
}

onMounted(() => {
  try {
    lastReadAt.value = Number(localStorage.getItem(storageKey.value) || 0)
  } catch { lastReadAt.value = 0 }
  notifySupported.value = 'Notification' in window
  notifyGranted.value = notifySupported.value && Notification.permission === 'granted'
  load()
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') load()
  }, 30000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

watch(() => props.tripId, () => { try { lastReadAt.value = Number(localStorage.getItem(storageKey.value) || 0) } catch { lastReadAt.value = 0 } load() })
</script>

<template>
  <div class="events-card">
    <div class="events-head" @click="toggle">
      <span class="events-title">
        {{ t('events.title') }}
        <span v-if="unread" class="events-dot">{{ unread }}</span>
      </span>
      <span class="events-toggle">{{ expanded ? t('events.collapse') : t('events.expand') }}</span>
    </div>

    <div v-if="notifySupported && !notifyGranted" class="events-notify">
      <el-button size="small" text type="primary" @click="enableNotify">
        {{ t('events.enableNotify') }}
      </el-button>
    </div>

    <ul v-if="expanded && items.length" class="events-list">
      <li v-for="ev in items" :key="ev.id" class="events-item">
        <span class="events-type">{{ eventLabel(ev.event_type) }}</span>
        <span class="events-text">{{ eventText(ev) }}</span>
        <span class="events-time">{{ timeText(ev.created_at) }}</span>
      </li>
    </ul>
    <div v-else-if="expanded" class="events-empty">{{ t('events.empty') }}</div>
  </div>
</template>

<style scoped>
.events-card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  padding: 12px 14px;
  margin: 12px 0;
}
.events-head { display: flex; align-items: center; justify-content: space-between; cursor: pointer; }
.events-title { font-size: 14px; font-weight: 600; color: #1f2937; display: inline-flex; align-items: center; gap: 6px; }
.events-dot {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 18px; height: 18px; padding: 0 5px;
  background: #ff385c; color: #fff; font-size: 11px; border-radius: 999px;
}
.events-toggle { font-size: 12px; color: #9ca3af; }
.events-notify { margin-top: 8px; }
.events-list { margin: 10px 0 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; max-height: 240px; overflow-y: auto; }
.events-item { display: flex; align-items: baseline; gap: 8px; font-size: 13px; color: #374151; }
.events-type {
  flex-shrink: 0; font-size: 11px; color: #2563eb; background: #eff6ff;
  border-radius: 4px; padding: 0 6px;
}
.events-text { flex: 1; min-width: 0; }
.events-time { flex-shrink: 0; font-size: 11px; color: #9ca3af; }
.events-empty { margin-top: 10px; font-size: 13px; color: #9ca3af; }
</style>