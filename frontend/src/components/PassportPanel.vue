<template>
  <div class="passport-panel">
    <div class="passport-header">
      <span class="passport-title">🏅 {{ t('passport.panelTitle') }}</span>
      <el-tag v-if="phase" size="small" :type="phaseTag" effect="light">{{ phaseLabel }}</el-tag>
      <span v-if="badgeCount > 0" class="passport-count">{{ badgeCount }}/{{ badgeKeys.length }}</span>
    </div>

    <div v-if="badgeKeys.length === 0" class="passport-empty">
      {{ t('passport.empty') }}
    </div>

    <div v-else class="passport-badges">
      <div
        v-for="key in badgeKeys"
        :key="key"
        class="passport-badge"
        :class="{ locked: !earnedBadges[key] }"
        :title="earnedBadges[key] ? earnedBadges[key].label : badgeLabel(key)"
      >
        <div class="badge-icon">{{ badgeIcon(key) }}</div>
        <div class="badge-name">{{ earnedBadges[key]?.label || badgeLabel(key) }}</div>
        <div v-if="earnedBadges[key]?.earned_at" class="badge-time">{{ formatDate(earnedBadges[key].earned_at) }}</div>
        <div v-else class="badge-lock">🔒</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getPassport } from '../api'

const props = defineProps({
  tripId: { type: String, required: true },
})

const { t } = useI18n()
const passport = ref(null)
const loading = ref(false)

// 已获得徽章 map：key -> badge
const earnedBadges = computed(() => {
  const p = passport.value
  if (!p || !p.badges) return {}
  const map = {}
  for (const b of p.badges) {
    if (b && b.key) map[b.key] = b
  }
  return map
})
const badgeKeys = computed(() => passport.value?.badge_keys || [])
const badgeCount = computed(() => passport.value?.badge_count || 0)
const phase = computed(() => passport.value?.phase || '')
const phaseLabel = computed(() => {
  const map = {
    upcoming: t('passport.phase.upcoming'),
    live: t('passport.phase.live'),
    finished: t('passport.phase.finished'),
  }
  return map[phase.value] || phase.value
})
const phaseTag = computed(() => {
  const map = { live: 'success', finished: 'info', upcoming: 'warning' }
  return map[phase.value] || 'info'
})

function badgeIcon(key) {
  const map = {
    first_checkin: '✅',
    full_day: '🌟',
    money_saver: '💰',
    train_goer: '🚄',
    hotel_stayer: '🏨',
    early_bird: '📅',
    night_owl: '🌙',
    foodie: '🍜',
    all_days_done: '🏆',
    group_voter: '👥',
  }
  return map[key] || '🏅'
}

function badgeLabel(key) {
  // 后端 BADGE_LABELS 有中文，但前端 i18n 兜底用 key 显示
  const fallback = {
    first_checkin: t('passport.badges.first_checkin'),
    full_day: t('passport.badges.full_day'),
    money_saver: t('passport.badges.money_saver'),
    train_goer: t('passport.badges.train_goer'),
    hotel_stayer: t('passport.badges.hotel_stayer'),
    early_bird: t('passport.badges.early_bird'),
    night_owl: t('passport.badges.night_owl'),
    foodie: t('passport.badges.foodie'),
    all_days_done: t('passport.badges.all_days_done'),
    group_voter: t('passport.badges.group_voter'),
  }
  return fallback[key] || key
}

function formatDate(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString()
  } catch {
    return ''
  }
}

async function load() {
  loading.value = true
  try {
    passport.value = await getPassport(props.tripId)
  } catch (e) {
    // 静默：护照是激励层，失败不影响详情页
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.passport-panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px;
}
.passport-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.passport-title {
  font-weight: 600;
  font-size: 15px;
}
.passport-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.passport-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  padding: 10px 0;
}
.passport-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.passport-badge {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 84px;
  padding: 8px 6px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.passport-badge.locked {
  opacity: 0.5;
}
.badge-icon {
  font-size: 26px;
  line-height: 1;
}
.badge-name {
  font-size: 12px;
  color: var(--el-text-color-primary);
  text-align: center;
}
.badge-time {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.badge-lock {
  font-size: 11px;
}
</style>