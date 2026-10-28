<template>
  <div class="passport-panel">
    <div class="passport-header">
      <span class="passport-title">🏅 {{ t('passport.panelTitle') }}</span>
      <el-tag v-if="phase" size="small" :type="phaseTag" effect="light">{{ phaseLabel }}</el-tag>
    </div>

    <div v-if="!loading && badges.length === 0" class="passport-empty">
      {{ t('passport.empty') }}
    </div>

    <div v-else class="passport-badges">
      <div
        v-for="b in badges"
        :key="b.key"
        class="passport-badge"
        :class="{ locked: !b.earned_at }"
      >
        <div class="badge-icon">{{ badgeIcon(b.key) }}</div>
        <div class="badge-name">{{ b.label }}</div>
        <div v-if="b.earned_at" class="badge-time">{{ formatDate(b.earned_at) }}</div>
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

const badges = computed(() => {
  const p = passport.value
  if (!p || !p.badges) return []
  // 已拥有徽章显示，未拥有的不显示（徽章墙只显示集齐的）
  return p.badges
})
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
  }
  return map[key] || '🏅'
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
</style>