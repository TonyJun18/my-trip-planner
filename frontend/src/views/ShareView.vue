<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as api from '@/api'
import TripMap from '@/components/TripMap.vue'

const route = useRoute()
const loading = ref(false)
const error = ref('')
const trip = ref(null)

// ── 受邀编辑模式：URL 带 ?edit=1（owner 生成的 edit_url）→ 用 edit_token 访问 ──
const editMode = computed(() => route.query.edit === '1')
// 行内编辑缓冲：stop_id -> { name, description }
const editingStop = ref(null)
const editBuf = ref({ name: '', description: '' })
const savingStop = ref(false)

// ── 分享页协作：评论 ──
const comments = ref([])
const commentLoading = ref(false)
const commentName = ref('')
const commentText = ref('')
const commentSubmitting = ref(false)

// ── 分享页协作：站点投票 ──
const votes = ref({}) // stop_id -> { up, down, my_value? }
const voting = ref({}) // stop_id -> true（提交中防抖）

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const markers = computed(() => {
  const list = []
  for (const day of trip.value?.days || []) {
    for (const stop of day.stops || []) {
      if (stop.lat != null && stop.lng != null) {
        list.push({ lat: stop.lat, lng: stop.lng, name: stop.name, stop_type: stop.stop_type, description: stop.description })
      }
    }
  }
  return list
})

const statusMap = {
  draft: { label: '草稿', type: 'info' },
  planning: { label: '规划中', type: 'warning' },
  confirmed: { label: '已确认', type: 'success' },
  archived: { label: '已归档', type: 'info' },
}

const typeLabel = { attraction: '景点', food: '餐饮', hotel: '住宿' }
const typeColor = { attraction: 'var(--brand)', food: '#c2410c', hotel: '#0d8a5f' }
const typeEmoji = { attraction: '🏞️', food: '🍜', hotel: '🏨' }

// ── 预算：公开分享接口（GET /trips/share/{token}）返回 budget_summary 汇总，无需本地重复计算 ──
const budget = computed(() => trip.value?.budget_summary || null)

const budgetPercent = computed(() => {
  if (!budget.value?.total_estimated || !trip.value?.budget) return null
  return Math.min(100, Math.round((budget.value.total_estimated / trip.value.budget) * 100))
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    trip.value = editMode.value
      ? await api.getEditableTrip(route.params.token)
      : await api.getSharedTrip(route.params.token)
    await Promise.all([loadComments(), loadVotes()])
  } catch (e) {
    error.value = editMode.value ? '协作编辑链接无效或已失效' : '分享链接无效或已失效'
  } finally {
    loading.value = false
  }
}

// ── 协作加载 / 提交 ──
async function loadComments() {
  commentLoading.value = true
  try {
    comments.value = await api.getSharedTripComments(route.params.token)
  } catch (e) {
    comments.value = []
  } finally {
    commentLoading.value = false
  }
}

async function loadVotes() {
  try {
    votes.value = await api.getSharedTripVotes(route.params.token)
  } catch (e) {
    votes.value = {}
  }
}

async function submitComment() {
  const content = commentText.value.trim()
  if (!content || commentSubmitting.value) return
  commentSubmitting.value = true
  try {
    const created = await api.postSharedTripComment(route.params.token, {
      author_name: commentName.value.trim() || null,
      content,
    })
    comments.value.push(created)
    commentText.value = ''
  } catch (e) {
    // 拦截器已弹出错误提示
  } finally {
    commentSubmitting.value = false
  }
}

async function castVote(stopId, value) {
  if (voting.value[stopId]) return
  voting.value[stopId] = true
  try {
    const result = await api.castSharedTripVote(route.params.token, stopId, value)
    votes.value[stopId] = result
  } catch (e) {
    // 拦截器已弹出错误提示
  } finally {
    voting.value[stopId] = false
  }
}

function voteCount(stopId, kind) {
  return votes.value?.[stopId]?.[kind] || 0
}

function myVote(stopId) {
  return votes.value?.[stopId]?.my_value || 0
}

// ── 受邀编辑（editMode）：勾选 / 行内改名备注 / 上移下移顺序 ──
async function toggleChecked(stop) {
  try {
    const updated = await api.updateInvitedStop(route.params.token, stop.id, { checked: !stop.checked })
    stop.checked = updated.checked
  } catch (e) {
    // 拦截器已 toast（如链接已收回）
  }
}
function startEditStop(stop) {
  editingStop.value = stop.id
  editBuf.value = { name: stop.name || '', description: stop.description || '' }
}
function cancelEditStop() {
  editingStop.value = null
  editBuf.value = { name: '', description: '' }
}
async function saveEditStop(stop) {
  const name = (editBuf.value.name || '').trim()
  if (!name) {
    ElMessage.warning('名称不能为空')
    return
  }
  savingStop.value = true
  try {
    const updated = await api.updateInvitedStop(route.params.token, stop.id, {
      name,
      description: (editBuf.value.description || '').trim() || null,
    })
    stop.name = updated.name
    stop.description = updated.description
    editingStop.value = null
  } catch (e) {
    // 拦截器已 toast
  } finally {
    savingStop.value = false
  }
}
async function moveStop(day, stop, dir) {
  const stops = day.stops
  const idx = stops.findIndex((s) => s.id === stop.id)
  const target = idx + dir
  if (idx < 0 || target < 0 || target >= stops.length) return
  const order = stops.map((s) => s.id)
  ;[order[idx], order[target]] = [order[target], order[idx]]
  try {
    // 用服务端返回的新顺序更新本地（避免整页重载闪烁）
    day.stops = await api.reorderInvitedStops(route.params.token, day.id, order)
  } catch (e) {
    // 拦截器已 toast（如链接已收回）
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="share-page">
    <!-- 提示条：只读 or 受邀编辑 -->
    <div class="share-banner" :class="{ edit: editMode }">
      <el-icon style="margin-right: 6px"><component :is="editMode ? 'EditPen' : 'View'" /></el-icon>
      <span v-if="!editMode">这是分享的只读行程 · 无法编辑</span>
      <span v-else>受邀编辑模式 · 你的修改会同步给行程 owner（名称 / 备注 / 勾选 / 顺序）</span>
    </div>

    <div v-if="error" class="share-error">
      <el-result icon="warning" :title="error">
        <template #extra>
          <span class="share-error-hint">如需查看请联系行程分享者重新发送链接</span>
        </template>
      </el-result>
    </div>

    <template v-else-if="trip">
      <!-- 头图 + 概览 -->
      <div class="hero-card">
        <div class="hero-cover">
          <div class="hero-city">{{ (trip.destination || '?')[0] }}</div>
          <div class="hero-overlay">
            <h1 class="hero-title">{{ trip.title }}</h1>
            <div class="hero-meta">
              <span class="hero-pill"><el-icon><Location /></el-icon>{{ trip.destination }}</span>
              <span class="hero-pill"><el-icon><Calendar /></el-icon>{{ trip.start_date }} ~ {{ trip.end_date }}</span>
              <span class="hero-pill"><el-icon><User /></el-icon>{{ trip.travelers }} 人</span>
              <span class="hero-pill" v-if="trip.budget != null"><el-icon><Wallet /></el-icon>预算 ¥{{ trip.budget }}</span>
            </div>
          </div>
          <span class="status-badge" :class="(statusMap[trip.status] || statusMap.draft).type">
            {{ (statusMap[trip.status] || statusMap.draft).label }}
          </span>
        </div>
      </div>

      <!-- 地图 + 预算 -->
      <div class="map-budget-row">
        <div class="map-card">
          <div class="card-head">
            <span class="card-title">行程地图</span>
            <span class="map-hint">按游玩顺序连线 · 点击标记查看详情</span>
          </div>
          <TripMap :markers="markers" height="420px" />
        </div>
        <div class="budget-card">
          <div class="card-head"><span class="card-title">预算明细</span></div>
          <template v-if="budget">
            <div class="budget-ring-wrap">
              <div class="budget-ring" :style="{ '--pct': budgetPercent != null ? budgetPercent : 0 }">
                <div class="budget-ring-inner">
                  <div class="ring-total">¥{{ budget.total_estimated }}</div>
                  <div class="ring-label">已估算</div>
                </div>
              </div>
              <div class="ring-caption" v-if="budgetPercent != null">
                占设定预算 {{ budgetPercent }}%
              </div>
            </div>
            <div class="budget-lines">
              <div v-for="(label, k) in { attraction: '景点', food: '餐饮', hotel: '住宿' }" :key="k" class="budget-line">
                <span class="budget-dot" :style="{ background: typeColor[k] }" />
                <span>{{ label }}</span>
                <span class="budget-line-val">¥{{ budget.by_type?.[k] || 0 }}</span>
              </div>
              <div class="budget-line total">
                <span>合计</span>
                <span class="total-val">¥{{ budget.total_estimated }}</span>
              </div>
            </div>
            <div class="budget-daily" v-if="budget.daily_average">
              <el-icon><TrendCharts /></el-icon> 日均约 ¥{{ budget.daily_average }}
            </div>
          </template>
          <el-empty v-else description="暂无预算数据" :image-size="60" />
        </div>
      </div>

      <!-- 每日行程 -->
      <div class="day-section" v-for="day in trip.days" :key="day.id">
        <div class="day-head">
          <div class="day-headline">
            <span class="day-badge">Day {{ day.day_number }}</span>
            <div>
              <div class="day-title">{{ day.date || `第 ${day.day_number} 天` }}</div>
              <div class="day-note">{{ day.note || '自由探索' }}</div>
            </div>
          </div>
        </div>

        <!-- 站点时间轴 -->
        <div class="stops-list" v-if="day.stops.length">
          <div v-for="(stop, idx) in day.stops" :key="stop.id" class="stop-item" :class="{ checked: stop.checked }">
            <div class="stop-rail">
              <span class="stop-index" :style="{ background: typeColor[stop.stop_type] || 'var(--brand)' }">{{ idx + 1 }}</span>
              <span class="rail-line" v-if="idx < day.stops.length - 1" />
            </div>
            <div class="stop-body">
              <div class="stop-head">
                <span class="stop-name">
                  <!-- 受邀编辑：勾选 + 行内编辑名称 -->
                  <el-checkbox
                    v-if="editMode"
                    :model-value="!!stop.checked"
                    @change="toggleChecked(stop)"
                    style="margin-right: 6px"
                  />
                  <template v-if="editMode && editingStop === stop.id">
                    <el-input v-model="editBuf.name" size="small" maxlength="200" class="inline-edit-name" />
                  </template>
                  <template v-else>{{ stop.name }}</template>
                </span>
                <el-tag size="small" round :style="{ color: typeColor[stop.stop_type] || 'var(--brand)', background: (typeColor[stop.stop_type] || 'var(--brand)') + '1a', border: 'none' }">
                  {{ typeEmoji[stop.stop_type] }} {{ typeLabel[stop.stop_type] || stop.stop_type }}
                </el-tag>
              </div>
              <div class="stop-meta">
                <span v-if="stop.estimated_cost != null"><el-icon><Wallet /></el-icon>¥{{ stop.estimated_cost }}</span>
                <span v-if="stop.estimated_duration_minutes"><el-icon><Clock /></el-icon>{{ stop.estimated_duration_minutes }} 分钟</span>
                <span v-if="!editMode" class="vote-group">
                  <button
                    class="vote-btn"
                    :class="{ active: myVote(stop.id) === 1 }"
                    :disabled="voting[stop.id]"
                    @click="castVote(stop.id, 1)"
                    title="想去 👍"
                  >👍 {{ voteCount(stop.id, 'up') }}</button>
                  <button
                    class="vote-btn"
                    :class="{ active: myVote(stop.id) === -1 }"
                    :disabled="voting[stop.id]"
                    @click="castVote(stop.id, -1)"
                    title="不想去 👎"
                  >👎 {{ voteCount(stop.id, 'down') }}</button>
                </span>
                <!-- 受邀编辑：行内编辑 + 上移下移 -->
                <span v-else class="edit-group">
                  <template v-if="editingStop === stop.id">
                    <el-button size="small" type="primary" text :loading="savingStop" @click="saveEditStop(stop)">保存</el-button>
                    <el-button size="small" text @click="cancelEditStop">取消</el-button>
                  </template>
                  <template v-else>
                    <el-button size="small" text @click="startEditStop(stop)">✏️ 改名/备注</el-button>
                  </template>
                  <el-button size="small" text :disabled="idx === 0" @click="moveStop(day, stop, -1)">↑</el-button>
                  <el-button size="small" text :disabled="idx >= day.stops.length - 1" @click="moveStop(day, stop, 1)">↓</el-button>
                </span>
              </div>
              <!-- 受邀编辑：行内编辑备注文本域 -->
              <div v-if="editMode && editingStop === stop.id" class="stop-desc">
                <el-input
                  v-model="editBuf.description"
                  type="textarea"
                  :rows="2"
                  maxlength="2000"
                  placeholder="备注（可选）"
                />
              </div>
              <div v-else-if="stop.description" class="stop-desc">{{ stop.description }}</div>
            </div>
          </div>
        </div>
        <el-empty v-else description="这一天还没有站点" :image-size="60" />
      </div>

      <!-- 分享页协作：评论区（免登录，凭分享链接） -->
      <div class="comments-card">
        <div class="card-head">
          <span class="card-title">协作讨论</span>
          <span class="map-hint">凭分享链接即可参与 · 无需登录</span>
        </div>

        <div v-if="comments.length" class="comment-list">
          <div v-for="c in comments" :key="c.id" class="comment-item">
            <div class="comment-avatar">{{ (c.author_name || '匿')[0] }}</div>
            <div class="comment-main">
              <div class="comment-head">
                <span class="comment-name">{{ c.author_name || '匿名访客' }}</span>
                <span class="comment-time">{{ fmtTime(c.created_at) }}</span>
              </div>
              <div class="comment-text">{{ c.content }}</div>
            </div>
          </div>
        </div>
        <el-empty v-else-if="!commentLoading" description="还没有评论，来抢沙发" :image-size="50" />

        <div class="comment-composer">
          <el-input v-model="commentName" placeholder="昵称（可选）" class="comment-name-input" maxlength="50" clearable />
          <el-input
            v-model="commentText"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            placeholder="对这个行程有什么想说的？"
          />
          <div class="comment-actions">
            <el-button type="primary" :loading="commentSubmitting" :disabled="!commentText.trim()" @click="submitComment">
              发表评论
            </el-button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.share-page { max-width: 1080px; margin: 0 auto; padding-top: 8px; }

.share-banner {
  display: flex; align-items: center;
  background: var(--brand-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 10px 16px; margin-bottom: 18px;
  font-size: 13px; color: var(--ink-2);
}
.share-banner.edit {
  background: #fff7e6;
  border-color: #f5c97b;
  color: #8a5a00;
}
/* 受邀编辑：勾选后的站点置灰 */
.stop-item.checked .stop-body { opacity: 0.62; }
.stop-item.checked .stop-name { text-decoration: line-through; }
.inline-edit-name { width: 220px; display: inline-flex; vertical-align: middle; }
.edit-group { margin-left: auto; display: inline-flex; align-items: center; gap: 2px; }

.share-error { padding: 40px 0; }
.share-error-hint { color: var(--faint); font-size: 13px; }

/* ── 头图 ── */
.hero-card { margin-bottom: 20px; }
.hero-cover {
  position: relative;
  height: 200px;
  border-radius: var(--radius-xl);
  background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 55%, #a1c4fd 100%);
  overflow: hidden;
  display: flex; align-items: center;
  box-shadow: var(--shadow-card);
}
.hero-city {
  position: absolute; right: 6%; bottom: -36px;
  font-size: 210px; font-weight: 800; color: rgba(255,255,255,0.35);
  line-height: 1; user-select: none;
}
.hero-overlay { position: relative; z-index: 1; padding: 32px 36px; }
.hero-title { margin: 0 0 14px; font-size: 30px; font-weight: 700; color: #fff; text-shadow: 0 2px 14px rgba(0,0,0,0.18); letter-spacing: -0.02em; }
.hero-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.hero-pill {
  display: inline-flex; align-items: center; gap: 5px;
  background: rgba(255,255,255,0.88); color: var(--ink-2);
  font-size: 12.5px; font-weight: 500;
  padding: 6px 12px; border-radius: var(--radius-full);
  backdrop-filter: blur(4px);
}
.status-badge {
  position: absolute; top: 16px; right: 16px; z-index: 2;
  font-size: 12px; font-weight: 600; padding: 5px 12px;
  border-radius: var(--radius-full); background: rgba(255,255,255,0.9);
}
.status-badge.success { color: var(--success); }
.status-badge.warning { color: var(--warning); }
.status-badge.info { color: var(--muted); }

/* ── 地图 + 预算 ── */
.map-budget-row { display: grid; grid-template-columns: 1.6fr 1fr; gap: 16px; margin-bottom: 28px; }
.map-card, .budget-card {
  background: #fff; border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 18px; box-shadow: var(--shadow-card);
}
.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.card-title { font-size: 15px; font-weight: 600; color: var(--ink); }
.map-hint { font-size: 12px; color: var(--faint); }

.budget-ring-wrap { text-align: center; padding: 8px 0 4px; }
.budget-ring {
  --pct: 0;
  width: 120px; height: 120px; margin: 0 auto;
  border-radius: 50%;
  background: conic-gradient(var(--brand) calc(var(--pct) * 1%), var(--fill) 0);
  display: flex; align-items: center; justify-content: center;
}
.budget-ring-inner {
  width: 88px; height: 88px; border-radius: 50%; background: #fff;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
}
.ring-total { font-size: 17px; font-weight: 700; color: var(--ink); }
.ring-label { font-size: 11px; color: var(--faint); }
.ring-caption { font-size: 12px; color: var(--muted); margin-top: 6px; }

.budget-lines { margin-top: 12px; }
.budget-line { display: flex; align-items: center; gap: 8px; padding: 7px 0; font-size: 13px; color: var(--ink-2); }
.budget-dot { width: 8px; height: 8px; border-radius: 50%; }
.budget-line-val { margin-left: auto; font-weight: 600; color: var(--ink); }
.budget-line.total { border-top: 1px solid var(--line); margin-top: 4px; padding-top: 12px; font-weight: 600; }
.total-val { margin-left: auto; font-size: 17px; font-weight: 700; color: var(--brand); }
.budget-daily { margin-top: 10px; font-size: 12.5px; color: var(--success); display: inline-flex; align-items: center; gap: 4px; }

.detail-quality { margin-top: 4px; }

/* ── 每日行程 ── */
.day-section { margin-bottom: 24px; }
.day-head { display: flex; align-items: center; justify-content: space-between; margin: 0 0 14px; gap: 12px; }
.day-headline { display: flex; align-items: center; gap: 12px; }
.day-badge {
  width: 52px; height: 52px; border-radius: var(--radius-md); flex-shrink: 0;
  background: var(--ink); color: #fff; font-weight: 700; font-size: 13px;
  display: flex; align-items: center; justify-content: center;
  letter-spacing: 0.02em;
}
.day-title { font-size: 15px; font-weight: 600; color: var(--ink); }
.day-note { font-size: 12.5px; color: var(--muted); }

.stops-list { display: flex; flex-direction: column; }
.stop-item { display: flex; gap: 14px; }
.stop-rail { display: flex; flex-direction: column; align-items: center; width: 28px; flex-shrink: 0; }
.stop-index {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  color: #fff; font-size: 13px; font-weight: 600; z-index: 1;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 0 4px #fff;
}
.rail-line { flex: 1; width: 2px; background: var(--line); margin: 4px 0; }

.stop-body {
  flex: 1; min-width: 0; background: #fff;
  border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 14px 18px; margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
  transition: box-shadow .2s;
}
.stop-body:hover { box-shadow: var(--shadow-card); }
.stop-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.stop-name { font-size: 15px; font-weight: 600; color: var(--ink); }
.stop-meta { display: flex; gap: 14px; font-size: 12.5px; color: var(--muted); margin-top: 6px; align-items: center; }
.stop-meta .el-icon { font-size: 13px; color: var(--faint); }
.stop-desc { margin-top: 6px; font-size: 13px; color: var(--ink-2); line-height: 1.55; }

/* ── 站点投票 ── */
.vote-group { margin-left: auto; display: inline-flex; gap: 6px; }
.vote-btn {
  appearance: none; border: 1px solid var(--line); background: #fff;
  border-radius: var(--radius-full); padding: 3px 10px; font-size: 12.5px;
  color: var(--ink-2); cursor: pointer; transition: all .15s;
  line-height: 1.4;
}
.vote-btn:hover:not(:disabled) { border-color: var(--brand); color: var(--brand); }
.vote-btn.active { background: var(--brand-soft); border-color: var(--brand); color: var(--brand); font-weight: 600; }
.vote-btn:disabled { opacity: .55; cursor: default; }

/* ── 分享页协作评论 ── */
.comments-card {
  background: #fff; border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 18px; box-shadow: var(--shadow-card); margin-bottom: 24px;
}
.comment-list { display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px; }
.comment-item { display: flex; gap: 10px; }
.comment-avatar {
  width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
  background: var(--brand-soft); color: var(--brand); font-size: 13px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.comment-main { flex: 1; min-width: 0; }
.comment-head { display: flex; align-items: baseline; gap: 8px; }
.comment-name { font-size: 13px; font-weight: 600; color: var(--ink); }
.comment-time { font-size: 11.5px; color: var(--faint); }
.comment-text {
  margin-top: 3px; font-size: 13.5px; color: var(--ink-2); line-height: 1.55;
  white-space: pre-wrap; word-break: break-word;
}
.comment-composer { border-top: 1px dashed var(--line); padding-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.comment-name-input { max-width: 220px; }
.comment-actions { display: flex; justify-content: flex-end; }

/* 响应式 */
@media (max-width: 860px) {
  .map-budget-row { grid-template-columns: 1fr; }
  .hero-cover { height: 160px; }
  .hero-overlay { padding: 24px; }
  .hero-title { font-size: 24px; }
}
</style>