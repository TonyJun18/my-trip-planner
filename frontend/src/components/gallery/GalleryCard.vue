<script setup>
import { computed } from 'vue'
import { Location, User, Wallet, View, CopyDocument, Delete } from '@element-plus/icons-vue'

/**
 * 画廊卡片（task-gallery-v2）：列表与详情入口的统一卡片。
 *
 * 与 LandingPage 旧内联卡片的差别：
 * - 有封面渐变（按目的地稳定取色，同一城市每次一致）+ 天数角标
 * - 显式两个动作：「看详情」（免登录可达的 /share/:token）与「以此为蓝本创建」，
 *   上一版整卡点击直接 clone，用户不知道会被复制什么
 * - 评分热度：有评分显示 ★ 均分 + 人数 + 去过人数，无评分诚实标注（不编造）
 */
const props = defineProps({
  item: { type: Object, required: true },
  // 我的发布：把「复制」换成「撤回」
  mine: { type: Boolean, default: false },
})

defineEmits(['open', 'clone', 'unpublish'])

const HUES = [
  'linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%)',
  'linear-gradient(135deg, #f6d365 0%, #fda085 100%)',
  'linear-gradient(135deg, #a1c4fd 0%, #c2e9fb 100%)',
  'linear-gradient(135deg, #fbc2eb 0%, #a6c1ee 100%)',
  'linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%)',
  'linear-gradient(135deg, #fddb92 0%, #e6b0f4 100%)',
]

const hue = computed(() => {
  const s = String(props.item.destination || props.item.title || '')
  let h = 0
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) % 9973
  return HUES[h % HUES.length]
})
const cityChar = computed(() => (props.item.destination || props.item.title || '?').slice(0, 1))
const stars = computed(() => Math.round(props.item.rating_avg || 0))
</script>

<template>
  <article class="g-card">
    <div class="g-cover" :style="{ background: hue }">
      <span class="g-cover-char">{{ cityChar }}</span>
      <span class="g-cover-days">{{ $t('gallery.daysN', { n: item.days }) }}</span>
    </div>

    <div class="g-body">
      <h3 class="g-title" :title="item.title">{{ item.title }}</h3>

      <div class="g-meta">
        <span><el-icon><Location /></el-icon>{{ item.destination }}</span>
        <span v-if="item.travelers"><el-icon><User /></el-icon>{{ item.travelers }}</span>
        <span v-if="item.budget"><el-icon><Wallet /></el-icon>¥{{ item.budget }}</span>
      </div>

      <div v-if="item.rating_count" class="g-rating">
        <span class="g-stars">{{ '★'.repeat(stars) }}<span class="g-stars-empty">{{ '★'.repeat(Math.max(0, 5 - stars)) }}</span></span>
        <span class="g-rating-num">{{ $t('gallery.ratingMeta', { avg: Number(item.rating_avg || 0).toFixed(1), n: item.rating_count }) }}</span>
        <span v-if="item.visited_count" class="g-visited">{{ $t('gallery.visited', { n: item.visited_count }) }}</span>
      </div>
      <div v-else class="g-rating g-rating-empty">{{ $t('gallery.noRating') }}</div>

      <p v-if="item.blurb" class="g-blurb">{{ item.blurb }}</p>

      <div class="g-foot">
        <button class="g-btn g-btn-ghost" type="button" @click="$emit('open')">
          <el-icon><View /></el-icon>{{ $t('gallery.cardView') }}
        </button>
        <button v-if="mine" class="g-btn g-btn-danger" type="button" @click="$emit('unpublish')">
          <el-icon><Delete /></el-icon>{{ $t('gallery.cardUnpublish') }}
        </button>
        <button v-else class="g-btn g-btn-primary" type="button" @click="$emit('clone')">
          <el-icon><CopyDocument /></el-icon>{{ $t('gallery.cardClone') }}
        </button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.g-card {
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-card);
  transition: transform 0.2s, box-shadow 0.2s;
}
.g-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }

.g-cover {
  position: relative;
  height: 104px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.g-cover-char {
  font-size: 38px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.14);
}
.g-cover-days {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: var(--radius-full);
  background: rgba(255, 255, 255, 0.9);
  color: var(--ink-2);
}

.g-body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 8px; flex: 1; }
.g-title {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  color: var(--ink);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.g-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--muted); }
.g-meta span { display: inline-flex; align-items: center; gap: 3px; }
.g-meta .el-icon { font-size: 12px; }

.g-rating { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12px; }
.g-stars { color: #f5a623; letter-spacing: 1px; }
.g-stars-empty { color: #ddd; }
.g-rating-num { color: var(--ink-2); }
.g-visited { color: var(--faint); }
.g-rating-empty { color: var(--faint); }

.g-blurb {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--ink-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.g-foot { margin-top: auto; display: flex; flex-direction: column; gap: 6px; padding-top: 4px; }
.g-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 100%;
  min-height: 32px;
  padding: 0 10px;
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  border-radius: var(--radius-full);
  border: 1px solid var(--line);
  background: none;
  color: var(--ink-2);
  cursor: pointer;
  transition: color 0.18s, border-color 0.18s, background 0.18s;
}
.g-btn-ghost:hover { color: var(--brand); border-color: var(--brand); }
.g-btn-primary {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}
.g-btn-primary:hover { filter: brightness(1.05); }
.g-btn-danger { color: var(--danger); border-color: rgba(239, 68, 68, 0.35); }
.g-btn-danger:hover { background: rgba(239, 68, 68, 0.06); }
.g-btn:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
</style>
