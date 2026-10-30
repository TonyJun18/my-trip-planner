<script setup>
import { computed } from 'vue'
import {
  ArrowLeft, ArrowDown, Location, Calendar, User, Wallet, Briefcase, Promotion,
  EditPen, ChatDotRound, Share, Check, Compass, Download,
} from '@element-plus/icons-vue'
import TripDetailMoreMenu from './TripDetailMoreMenu.vue'

/**
 * 行程详情页头部（合并旧 TopBar + Hero）。
 *
 * 设计意图（解决「页面开头 200px 都是按钮和徽标」）：
 * 1. 一行体系：返回 / 封面 / 标题 + 状态 chip / 主操作 ≤3 / 更多
 * 2. 状态**只保留一个控件**：旧版「徽标 + 下拉框」并排是同一信息的两种控件，此处合并为可点击 chip
 * 3. 元信息从 6 个 pill 降为一行带分隔符的文本流（视觉噪音 -60%，信息量不变）
 * 4. sticky：长滚动时标题与主操作常驻（行中用户随时能打卡）
 * 5. 主操作按时机换血，硬约束 ≤3（PRD §4）
 */
const props = defineProps({
  trip: { type: Object, required: true },
  phase: { type: String, default: 'planning' }, // planning / prep / live / finished
  statusMap: { type: Object, required: true },
  statusOptions: { type: Array, required: true },
  statusUpdating: { type: Boolean, default: false },
  tripTypeDisplay: { type: Function, default: null },
  sharing: { type: Boolean, default: false },
  exporting: { type: Boolean, default: false },
  isFavorite: { type: Boolean, default: false },
  favoriting: { type: Boolean, default: false },
  hasSharedToken: { type: Boolean, default: false },
  editToken: { type: String, default: '' },
})

const emit = defineEmits(['back', 'action', 'more', 'status-change'])

const ICONS = {
  edit: EditPen,
  askAi: ChatDotRound,
  share: Share,
  checkin: Check,
  track: Compass,
  export: Download,
}

// 主操作三件套（按时机换血；顺序 = 视觉优先级，最后一个为主按钮）
const ACTIONS = {
  planning: [{ key: 'edit' }, { key: 'askAi' }, { key: 'share', primary: true }],
  prep: [{ key: 'edit' }, { key: 'askAi' }, { key: 'share', primary: true }],
  live: [{ key: 'track' }, { key: 'share' }, { key: 'checkin', primary: true }],
  finished: [{ key: 'edit' }, { key: 'export' }, { key: 'share', primary: true }],
}

const LABELS = {
  edit: 'tripDetail.editBasic',
  askAi: 'tripDetail.askAi',
  share: 'tripDetail.shareTrip',
  checkin: 'tripDetail.actionCheckin',
  track: 'tripDetail.actionTrack',
  export: 'tripDetail.exportPdf',
}

const actions = computed(() =>
  (ACTIONS[props.phase] || ACTIONS.planning).map((a) => ({
    ...a,
    label: LABELS[a.key],
    icon: ICONS[a.key],
  })),
)

const statusInfo = computed(() => props.statusMap[props.trip.status] || props.statusMap.draft || {})

const showAdjust = computed(() => props.phase !== 'planning')

function changeStatus(value) {
  if (value === props.trip.status) return
  props.trip.status = value
  emit('status-change', value)
}
</script>

<template>
  <header class="trip-header">
    <div class="th-row">
      <button class="th-back" type="button" :aria-label="$t('tripDetail.backToTrips')" :title="$t('tripDetail.backToTrips')" @click="emit('back')">
        <el-icon><ArrowLeft /></el-icon>
      </button>

      <div class="th-cover" aria-hidden="true">{{ (trip.destination || '?')[0] }}</div>

      <div class="th-id">
        <div class="th-title-row">
          <h1 class="th-title">{{ trip.title }}</h1>
          <el-dropdown trigger="click" :disabled="statusUpdating" @command="changeStatus">
            <button class="th-status" :class="statusInfo.type || 'info'" type="button">
              <span class="th-status-dot" />
              {{ statusInfo.label }}
              <el-icon class="th-status-caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="opt in statusOptions"
                  :key="opt.value"
                  :command="opt.value"
                  :class="{ 'is-current': opt.value === trip.status }"
                >{{ opt.label }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <div class="th-meta">
          <span class="th-meta-item"><el-icon><Location /></el-icon>{{ trip.destination }}</span>
          <span class="th-meta-sep">·</span>
          <span class="th-meta-item"><el-icon><Calendar /></el-icon>{{ trip.start_date }} → {{ trip.end_date }}</span>
          <span class="th-meta-sep">·</span>
          <span class="th-meta-item"><el-icon><User /></el-icon>{{ trip.travelers }} {{ $t('common.peopleUnit') }}</span>
          <template v-if="trip.departure">
            <span class="th-meta-sep">·</span>
            <span class="th-meta-item"><el-icon><Promotion /></el-icon>{{ $t('tripDetail.fromDeparture', { dep: trip.departure }) }}</span>
          </template>
          <template v-if="trip.budget != null">
            <span class="th-meta-sep">·</span>
            <span class="th-meta-item"><el-icon><Wallet /></el-icon>¥{{ trip.budget }}</span>
          </template>
          <template v-if="trip.trip_type">
            <span class="th-meta-sep">·</span>
            <span class="th-meta-item"><el-icon><Briefcase /></el-icon>{{ tripTypeDisplay ? tripTypeDisplay(trip.trip_type) : trip.trip_type }}</span>
          </template>
        </div>
      </div>

      <div class="th-actions">
        <el-button
          v-for="a in actions"
          :key="a.key"
          class="th-action"
          :type="a.primary ? 'primary' : 'default'"
          :plain="a.key === 'askAi'"
          :loading="(a.key === 'share' && sharing) || (a.key === 'export' && exporting)"
          @click="emit('action', a.key)"
        >
          <el-icon class="th-action-icon"><component :is="a.icon" /></el-icon>
          <span class="th-action-label">{{ $t(a.label) }}</span>
        </el-button>
        <TripDetailMoreMenu
          :is-favorite="isFavorite"
          :favoriting="favoriting"
          :has-shared-token="hasSharedToken"
          :edit-token="editToken"
          :show-adjust="showAdjust"
          @command="(cmd) => emit('more', cmd)"
        />
      </div>
    </div>
  </header>
</template>

<style scoped>
.trip-header {
  /* sticky 依赖「最近滚动祖先」不截断滚动：App.vue 已把 el-main 的 overflow 改回 visible，
     否则在 el-main 内部 sticky 只会被静态推下去、压住后续内容（旧版实测退化的原因）。
     移动端头部折成两行（约 130px），常驻会吃掉近 1/6 屏幕 → 只在 ≥721px 吸附。 */
  position: relative;
  z-index: 5;
  margin-bottom: 16px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: saturate(180%) blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(0, 0, 0, 0.04));
  transition: box-shadow 0.2s;
}
.trip-header:hover { box-shadow: var(--shadow-card); }

@media (min-width: 721px) {
  .trip-header {
    position: sticky;
    top: 64px; /* 顶部导航高度 */
    z-index: 20; /* 低于导航(1000)，高于卡片 */
  }
}

.th-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.th-back {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  border-radius: var(--radius-full);
  color: var(--ink-2);
  cursor: pointer;
  transition: background 0.18s, color 0.18s;
}
.th-back:hover { background: var(--fill); color: var(--ink); }

.th-cover {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 55%, #a1c4fd 100%);
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(0, 0, 0, 0.06));
}

.th-id { flex: 1; min-width: 0; }

.th-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.th-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.th-status {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  font: inherit;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.5;
  border-radius: var(--radius-full);
  border: 1px solid var(--line);
  background: var(--fill);
  color: var(--muted);
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s;
}
.th-status:hover { border-color: var(--brand); background: var(--brand-soft); }
.th-status:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.th-status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.th-status-caret { font-size: 10px; opacity: 0.7; }
.th-status.success { color: var(--success); background: rgba(13, 138, 95, 0.08); border-color: rgba(13, 138, 95, 0.18); }
.th-status.warning { color: var(--warning); background: rgba(194, 65, 12, 0.08); border-color: rgba(194, 65, 12, 0.18); }
.th-status.info { color: var(--muted); }

.th-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0 4px;
  margin-top: 3px;
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.6;
}
.th-meta-item { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.th-meta-item .el-icon { font-size: 12px; color: var(--faint); }
.th-meta-sep { color: var(--line); }

.th-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.th-actions :deep(.el-button) {
  margin-left: 0;
  border-radius: var(--radius-full);
  height: 34px;
  padding: 0 14px;
  font-size: 13px;
}
.th-action-icon { margin-right: 4px; }

/* 窄屏：标题行 + 操作行两段式，操作横向可滚（不换行挤压） */
@media (max-width: 720px) {
  .trip-header { padding: 8px 10px; }
  .th-row { flex-wrap: wrap; align-items: flex-start; }
  .th-back { height: 34px; }
  .th-cover { width: 34px; height: 34px; font-size: 15px; }
  .th-title { font-size: 15.5px; }
  .th-meta { font-size: 12px; }
  .th-actions {
    width: 100%;
    justify-content: flex-end;
    overflow-x: auto;
    padding-bottom: 2px;
    -webkit-overflow-scrolling: touch;
  }
  .th-actions :deep(.el-button) { height: 38px; flex-shrink: 0; }
  .th-action-label { display: none; }
  .th-action-icon { margin-right: 0; font-size: 16px; }
  .th-actions :deep(.el-button:last-child) .th-action-icon { margin-right: 0; }
}

@media print {
  .trip-header { position: static; box-shadow: none; border: none; backdrop-filter: none; }
  .th-actions, .th-back { display: none !important; }
}
</style>
