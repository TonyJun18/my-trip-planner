import http from '../http'

// ── 行程内结构化事实问答（task-property-qa-eval） ─────────────────
// 后端契约：GET /trips/{trip_id}/property-qa
//   - 不带 q → 当前可答事实清单 { trip_id, title, destination, facts[], budget, warnings[], suggestions[] }
//   - 带 q   → 单问答 { question, matched_type, target, available, answer, basis, detail }
// 口径：纯规则零 LLM，只答结构化字段里真实存在的事实；basis 标注来源
// （explicit 显式字段 / rule_based 类目规则库 / none 无数据 → available=false，绝不编造）
export const getPropertyQaFacts = (tripId, locale = 'zh-CN') =>
  http.get(`/trips/${tripId}/property-qa`, { params: { locale } }).then((r) => r.data)

export const askPropertyQa = (tripId, q, locale = 'zh-CN') =>
  http.get(`/trips/${tripId}/property-qa`, { params: { q, locale } }).then((r) => r.data)
