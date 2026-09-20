<script setup>
/**
 * 酒店推荐卡片区（公共组件）
 *
 * 数据源：后端 plan.hotels 候选列表（HotelAgent 采集的高德 POI，结构见
 * backend/app/agent/agents.py:_normalize_hotels）。
 * 字段：name / type:"hotel" / lat / lng / estimated_cost / description / address / source / source_url / rating
 *
 * 能力：
 *  - 展示酒店卡（名称/地址/价格/描述/来源链接）
 *  - 「已安排」标记：把已入选行程 stops 的酒店名与候选名做归一化匹配
 *  - 「安排进日程」：把候选酒店一键作为 stop_type=hotel 站点加入某一天（复用 addStop API）
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api'

const props = defineProps({
  // 酒店候选列表（plan.hotels）
  hotels: { type: Array, default: () => [] },
  // 行程站点（含 stop_type 的 day.stops），用于「已安排」判定
  days: { type: Array, default: () => [] },
  // 是否允许「安排进日程」（PlanWizard 结果页需要先保存成行程才能安排）
  actionable: { type: Boolean, default: false },
})

const emit = defineEmits(['arranged'])

// ── 名称归一化（信息源不同：LLM 写入 stop.name vs 高德 POI 候选名） ──
function normName(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/酒店$/, '')
    .replace(/hotel$/i, '')
    .replace(/[（(].*?[)）]/g, '')
    .trim()
}

const arrangedHotelNames = computed(() => {
  const names = new Set()
  for (const day of props.days || []) {
    for (const stop of day.stops || []) {
      if (stop.type === 'hotel' || stop.stop_type === 'hotel') {
        names.add(normName(stop.name))
      }
    }
  }
  return names
})

function isArranged(h) {
  return arrangedHotelNames.value.has(normName(h.name)) || arrangedHotelNames.value.has(normName(h.address))
}

function hotelPriceText(h) {
  const cost = Number(h.estimated_cost)
  if (cost > 0) return `¥${cost} 起`
  return '价格以实际询价为准'
}

// ── 安排进日程 ──
// dayId 由父组件通过 slot 提供（详情页：trip.days[].id；向导页：无 trip，隐藏）
const dayOptions = computed(() => (props.days || []).map((d) => ({ id: d.id, label: `Day ${d.day_number}${d.date ? ' · ' + d.date : ''}` })))

const pickingHotel = ref(null)
const pickingDayId = ref('')
const picking = ref(false)
const dialogVisible = computed(() => pickingHotel.value != null)

async function startPick(h) {
  if (!dayOptions.value.length) {
    ElMessage.warning('请先添加日程，再安排酒店')
    return
  }
  pickingHotel.value = h
  pickingDayId.value = dayOptions.value[0].id
}

async function confirmArrange() {
  if (!pickingHotel.value || !pickingDayId.value) return
  picking.value = true
  try {
    await api.addStop(pickingDayId.value, {
      name: pickingHotel.value.name,
      stop_type: 'hotel',
      lat: pickingHotel.value.lat ?? null,
      lng: pickingHotel.value.lng ?? null,
      description: pickingHotel.value.description || '',
      estimated_cost: pickingHotel.value.estimated_cost || null,
    })
    ElMessage.success(`已将「${pickingHotel.value.name}」安排进日程`)
    pickingHotel.value = null
    emit('arranged')
  } catch (e) {
    // api 层已弹错误，这里不重复弹
  } finally {
    picking.value = false
  }
}</script>

<template>
  <div v-if="hotels.length" class="hotel-section">
    <div class="card-head">
      <span class="card-title">🏨 住宿推荐</span>
      <span class="map-hint">由 AI 酒店专家筛选 · 共 {{ hotels.length }} 家</span>
    </div>
    <div class="hotel-grid">
      <div v-for="(h, idx) in hotels" :key="idx" class="hotel-card" :class="{ arranged: isArranged(h) }">
        <div class="hotel-top">
          <span class="hotel-name">{{ h.name }}</span>
          <el-tag v-if="isArranged(h)" size="small" type="success" round>已安排</el-tag>
        </div>
        <div class="hotel-meta">
          <span v-if="h.address" class="hotel-addr"><el-icon><Location /></el-icon>{{ h.address }}</span>
          <span class="hotel-price">{{ hotelPriceText(h) }}</span>
        </div>
        <div v-if="h.description" class="hotel-desc">{{ h.description }}</div>
        <div class="hotel-actions">
          <el-button v-if="h.source_url" link type="primary" tag="a" :href="h.source_url" target="_blank" rel="noopener">
            查看详情 <el-icon style="margin-left: 2px"><TopRight /></el-icon>
          </el-button>
          <el-button v-if="actionable && !isArranged(h)" link type="success" @click="startPick(h)">
            安排进日程
          </el-button>
        </div>
      </div>
    </div>

    <!-- 安排到哪一天 -->
    <el-dialog v-model="dialogVisible" title="安排进日程" width="420px">
      <el-form label-width="60px">
        <el-form-item label="酒店">
          <span>{{ pickingHotel?.name }}</span>
        </el-form-item>
        <el-form-item label="日期">
          <el-select v-model="pickingDayId" style="width: 100%">
            <el-option v-for="d in dayOptions" :key="d.id" :label="d.label" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pickingHotel = null">取消</el-button>
        <el-button type="primary" :loading="picking" @click="confirmArrange">确认安排</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.hotel-section {
  background: #fff; border: 1px solid var(--line); border-radius: var(--radius-lg);
  padding: 18px; margin-bottom: 28px; box-shadow: var(--shadow-card);
}
.hotel-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.hotel-card {
  border: 1px solid var(--line); border-radius: var(--radius-md);
  padding: 12px 14px; background: #fafafa;
  transition: box-shadow .2s, border-color .2s;
}
.hotel-card:hover { box-shadow: var(--shadow-card); border-color: var(--brand-soft); }
.hotel-card.arranged { border-color: var(--success); background: rgba(16,185,129,.05); }
.hotel-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.hotel-name { font-size: 14px; font-weight: 600; color: var(--ink); }
.hotel-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 6px; font-size: 12.5px; color: var(--muted); flex-wrap: wrap; }
.hotel-addr { display: inline-flex; align-items: center; gap: 3px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hotel-addr .el-icon { font-size: 13px; color: var(--faint); flex-shrink: 0; }
.hotel-price { font-weight: 600; color: var(--ink-2); flex-shrink: 0; }
.hotel-desc { margin-top: 6px; font-size: 12.5px; color: var(--ink-2); line-height: 1.5; }
.hotel-actions { margin-top: 6px; display: flex; justify-content: flex-end; gap: 8px; }
</style>