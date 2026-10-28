import http from '../http'

// ── 内容导入（五通道：笔记 / 截图 / 邮件 / 链接 / 社交粘贴；外部内容按敌意输入处理，纯规则解析零凭证） ──
// 后端契约：POST /trips/note/import {text} / screenshot/import <图片原始字节> /
// email/import {text} / link/import {url} / social/import {text} → 解析为站点候选，勾选后经 addStop 并入行程
export const importNote = (data) => http.post('/trips/note/import', data).then((r) => r.data)
export const importScreenshot = (file) =>
  http
    .post('/trips/screenshot/import', file, {
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      maxBodyLength: 20 * 1024 * 1024,
    })
    .then((r) => r.data)
export const importEmail = (data) => http.post('/trips/email/import', data).then((r) => r.data)
export const importLink = (data) => http.post('/trips/link/import', data).then((r) => r.data)
// 社交分享（task-social-collection-eval）：粘贴 caption+链接 → 地点候选；URL 只识别平台、绝不抓取
export const importSocial = (data) => http.post('/trips/social/import', data).then((r) => r.data)

// ── 灵感优先目的地推荐（task-inspiration-mode：还没想好去哪 → 按兴趣/预算/季节推荐） ──
// 后端契约：GET /trips/inspiration?interests=food,nature&budget_tier=comfort&season=&limit=5
// → { items: [{...}], counts, note }
export const getInspiration = (params = {}) => http.get('/trips/inspiration', { params }).then((r) => r.data)

// ── 灵感画廊 + 城市模板（task-gallery-featured / city-templates） ──
// GET /trips/gallery（公开精选） / GET /trips/gallery/templates（城市模板卡）
// POST /trips/gallery/{id}/clone（复制到我的账号） / POST /trips/{id}/gallery/publish
export const getGallery = (params = {}) => http.get('/trips/gallery', { params }).then((r) => r.data)
export const getCityTemplates = (params = {}) =>
  http.get('/trips/gallery/templates', { params }).then((r) => r.data)
export const cloneGalleryTrip = (sourceId) =>
  http.post(`/trips/gallery/${sourceId}/clone`).then((r) => r.data)
export const publishToGallery = (tripId, data = {}) =>
  http.post(`/trips/${tripId}/gallery/publish`, data).then((r) => r.data)
export const unpublishFromGallery = (tripId) =>
  http.delete(`/trips/${tripId}/gallery/publish`).then((r) => r.data)