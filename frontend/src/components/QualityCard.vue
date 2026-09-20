<script setup>
import { computed } from 'vue'

const props = defineProps({
  quality: { type: Object, default: null },
})

const q = computed(() => props.quality || {})
const hasQuality = computed(() => q.value.score != null)
const score = computed(() => q.value.score ?? 0)
const passed = computed(() => !!q.value.passed)
const finalized = computed(() => !!q.value.finalized)

const scoreColor = computed(() => {
  if (score.value >= 80) return 'var(--success)'
  if (score.value >= 60) return '#d97706'
  return '#dc2626'
})

const sevLabel = { critical: '必须改', warning: '建议改', info: '提示' }
const sevColor = { critical: '#dc2626', warning: '#d97706', info: 'var(--faint)' }
const catLabel = { schedule: '日程', budget: '预算', geography: '地理', logistics: '完整', info: '一般' }
</script>

<template>
  <div v-if="hasQuality" class="quality-card">
    <div class="quality-head">
      <span class="quality-title"><el-icon style="margin-right: 6px"><CircleCheck /></el-icon>行程质检报告</span>
      <span v-if="q.rounds" class="quality-meta">AI 质检专家评审 {{ q.rounds }} 轮</span>
    </div>

    <div class="quality-main">
      <!-- 评分 -->
      <div class="quality-score" :style="{ color: scoreColor }">
        <span class="score-num">{{ score }}</span>
        <span class="score-total">/100</span>
        <span class="score-badge" :style="{ background: scoreColor }">
          {{ passed ? '通过' : finalized ? '强制定稿' : '未通过' }}
        </span>
      </div>

      <div class="quality-side">
        <div v-if="q.summary" class="quality-summary">{{ q.summary }}</div>
        <div v-if="finalized" class="quality-finalized">
          已达最大评审轮数（{{ q.max_rounds }}），按当前版本定稿
        </div>

        <!-- 问题列表 -->
        <ul v-if="q.issues && q.issues.length" class="quality-issues">
          <li v-for="(iss, i) in q.issues" :key="i" class="quality-issue">
            <span class="sev-tag" :style="{ background: sevColor[iss.severity] || 'var(--faint)' }">
              {{ sevLabel[iss.severity] || iss.severity }}
            </span>
            <span v-if="iss.category" class="issue-cat">{{ catLabel[iss.category] || iss.category }}</span>
            <span class="issue-msg">{{ iss.message }}</span>
            <span v-if="iss.day_number" class="issue-day">Day {{ iss.day_number }}</span>
            <span v-if="iss.suggestion" class="issue-suggestion">→ {{ iss.suggestion }}</span>
          </li>
        </ul>
        <div v-else class="quality-clean">
          <el-icon style="margin-right: 4px; color: var(--success)"><CircleCheck /></el-icon>未发现明显问题
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.quality-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, #f6fffb, #fff 60%);
  padding: 18px 22px;
  margin-bottom: 20px;
}
.quality-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px; flex-wrap: wrap; gap: 8px;
}
.quality-title {
  font-size: 15px; font-weight: 600; color: var(--ink);
  display: inline-flex; align-items: center;
}
.quality-title .el-icon { color: var(--success); }
.quality-meta { font-size: 12px; color: var(--muted); }

.quality-main { display: flex; gap: 20px; align-items: flex-start; }
.quality-score {
  flex-shrink: 0; display: flex; flex-direction: column; align-items: center;
  width: 88px; padding: 10px 0;
}
.score-num { font-size: 34px; font-weight: 800; line-height: 1; }
.score-total { font-size: 12px; color: var(--faint); margin-top: 2px; }
.score-badge {
  margin-top: 8px; color: #fff; font-size: 11px; font-weight: 600;
  padding: 3px 10px; border-radius: var(--radius-full);
}

.quality-side { flex: 1; min-width: 0; }
.quality-summary { font-size: 13.5px; color: var(--ink-2); line-height: 1.6; }
.quality-finalized {
  margin-top: 6px; font-size: 12.5px; color: #d97706;
  background: rgba(217,119,6,.08); padding: 5px 10px; border-radius: var(--radius-sm);
  display: inline-block;
}
.quality-issues { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.quality-issue {
  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
  font-size: 13px; color: var(--ink-2); line-height: 1.5;
}
.sev-tag {
  color: #fff; font-size: 11px; font-weight: 600;
  padding: 2px 8px; border-radius: var(--radius-full); flex-shrink: 0;
}
.issue-cat { font-size: 11px; color: var(--faint); flex-shrink: 0; }
.issue-msg { flex: 1; min-width: 120px; }
.issue-day {
  font-size: 11px; color: var(--brand); background: var(--brand-soft);
  padding: 1px 7px; border-radius: var(--radius-full); flex-shrink: 0;
}
.issue-suggestion { width: 100%; font-size: 12px; color: var(--muted); padding-left: 4px; }
.quality-clean {
  font-size: 13px; color: var(--success); margin-top: 8px;
  display: inline-flex; align-items: center;
}

@media (max-width: 560px) {
  .quality-main { flex-direction: column; align-items: stretch; }
  .quality-score { width: auto; flex-direction: row; gap: 10px; align-items: baseline; padding: 0 0 6px; }
  .score-total { order: 2; }
  .score-badge { margin-top: 0; order: 3; }
}
</style>