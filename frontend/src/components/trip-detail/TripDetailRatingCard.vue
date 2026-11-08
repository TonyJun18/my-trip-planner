<script setup>
// 详情页评分控件（task-trip-rating-signal 的详情页入口）
//
// 后端 rating_service / API 早已就绪（upsert 幂等、avg 无量不编造），分享页评分条也已上线；
// 这里补的是「行程主人自己的」入口：行程结束后回来给这次行程打分 + 标记「我去过」，
// 评分与标记会公开显示在这条行程上（同行人 / 画廊用户的信任信号）。
//
// 显隐策略：行程结束（phase === 'finished'）才主动露出，避免没出发就打分；
// 但只要已经有人评过分或自己评过，就一直可见（评过就消失是反直觉的）。
// 组件自己拉数据（与 ShareView 评分条同构），不抬高 orchestrator 的状态复杂度。
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import * as api from '@/api'

const props = defineProps({
  tripId: { type: String, required: true },
  phase: { type: String, default: 'planning' },
})

const { t } = useI18n()

const agg = ref({ count: 0, avg: null, visited_count: 0 })
const myRating = ref(0)
const myVisited = ref(false)
const loading = ref(false)
const saving = ref(false)

const visible = computed(
  () => props.phase === 'finished' || agg.value.count > 0 || myRating.value > 0,
)

// 聚合口径：avg 为 null 时显示「还没有人评分」，绝不把 0 分当成差评（与后端诚实口径一致）
const avgText = computed(() =>
  agg.value.count ? Number(agg.value.avg || 0).toFixed(1) : '',
)

async function load() {
  if (!props.tripId) return
  loading.value = true
  try {
    const r = await api.getTripRating(props.tripId)
    agg.value = { count: r.count || 0, avg: r.avg, visited_count: r.visited_count || 0 }
    myRating.value = r.user_rating || 0
    myVisited.value = !!r.user_visited
  } catch {
    // 评分读取失败静默：它是附加值，不能影响详情页主路径
  } finally {
    loading.value = false
  }
}

watch(() => props.tripId, load, { immediate: true })

async function save() {
  // 星级是必填项（后端 rating 1-5），没选星时「去过」勾不上，这里再兜一层
  if (!props.tripId || saving.value || !myRating.value) return
  saving.value = true
  try {
    // 后端 POST 即 upsert：首次创建 / 再次改分同一条路径，不用前端区分
    await api.submitTripRating(props.tripId, { rating: myRating.value, visited: myVisited.value })
    ElMessage.success(t('tripDetail.ratingDone'))
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.error?.message || t('tripDetail.ratingFail'))
  } finally {
    saving.value = false
  }
}

async function clearRating() {
  if (saving.value || !myRating.value) return
  saving.value = true
  try {
    await api.deleteTripRating(props.tripId)
    myRating.value = 0
    myVisited.value = false
    await load()
    ElMessage.success(t('tripDetail.ratingCleared'))
  } catch (e) {
    ElMessage.error(e?.response?.data?.error?.message || t('tripDetail.ratingFail'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div v-if="visible" v-loading="loading" class="rating-card">
    <div class="rating-head">
      <div class="rating-title-wrap">
        <div class="rating-title">⭐ {{ $t('tripDetail.ratingTitle') }}</div>
        <div class="rating-hint">{{ $t('tripDetail.ratingHint') }}</div>
      </div>
      <div class="rating-agg">
        <template v-if="agg.count">
          <span class="rating-agg-main">{{ $t('tripDetail.ratingMeta', { avg: avgText, n: agg.count }) }}</span>
          <span v-if="agg.visited_count" class="rating-agg-sub">
            {{ $t('tripDetail.ratingVisitedCount', { n: agg.visited_count }) }}
          </span>
        </template>
        <span v-else class="rating-agg-empty">{{ $t('tripDetail.ratingNoRating') }}</span>
      </div>
    </div>

    <div class="rating-acts">
      <span class="rating-label">{{ $t('tripDetail.ratingMyScore') }}</span>
      <el-rate
        v-model="myRating"
        :disabled="saving"
        :aria-label="$t('tripDetail.ratingMyScore')"
        @change="save"
      />
      <el-checkbox
        v-model="myVisited"
        :disabled="saving || !myRating"
        @change="save"
      >
        {{ $t('tripDetail.ratingVisited') }}
      </el-checkbox>
      <el-button
        v-if="myRating"
        text
        size="small"
        :disabled="saving"
        @click="clearRating"
      >
        {{ $t('tripDetail.ratingClear') }}
      </el-button>
      <span v-if="!myRating" class="rating-tip">{{ $t('tripDetail.ratingPickFirst') }}</span>
    </div>
  </div>
</template>

<style scoped>
.rating-card {
  margin-top: 18px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--card);
  box-shadow: var(--shadow-sm);
}
.rating-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 12px;
}
.rating-title-wrap {
  min-width: 0;
}
.rating-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
}
.rating-hint {
  margin-top: 4px;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--muted);
}
.rating-agg {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  text-align: right;
}
.rating-agg-main {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--brand);
}
.rating-agg-sub,
.rating-agg-empty {
  font-size: 12px;
  color: var(--muted);
}
.rating-acts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
}
.rating-label {
  font-size: 12.5px;
  color: var(--muted);
}
.rating-tip {
  font-size: 12px;
  color: var(--muted);
}

@media (max-width: 640px) {
  .rating-head {
    flex-direction: column;
    gap: 8px;
  }
  .rating-agg {
    align-items: flex-start;
    text-align: left;
  }
}

/* 评分是私域操作，不进打印稿 / 导出快照 */
@media print {
  .rating-card {
    display: none !important;
  }
}
</style>
