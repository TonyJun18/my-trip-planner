/**
 * 行程评分 / 信任信号（task-trip-rating-signal，前端首次接线）。
 *
 * 画廊卡片展示的是聚合热度（列表接口已带 rating_count / rating_avg / visited_count）；
 * 这里是「打分入口」——分享详情页（画廊来源）让登录用户给这条行程打分 + 标记去过。
 * 后端 upsert 幂等：同 user+trip 唯一，POST 首次 / PUT 改分，重复提交不报错。
 */
import http from '../http'

/** 单行程评分详情：{ trip_id, count, avg, visited_count, user_rating, user_visited }（免登录可读） */
export const getTripRating = (tripId) =>
  http.get(`/trips/${tripId}/rating`).then((r) => r.data)

/** 首次评分（已存在时后端按 upsert 处理，语义等同改分） */
export const submitTripRating = (tripId, data) =>
  http.post(`/trips/${tripId}/rating`, data).then((r) => r.data)

/** 更新我的评分（幂等） */
export const updateTripRating = (tripId, data) =>
  http.put(`/trips/${tripId}/rating`, data).then((r) => r.data)

/** 删除我的评分（幂等） */
export const deleteTripRating = (tripId) =>
  http.delete(`/trips/${tripId}/rating`).then((r) => r.data)
