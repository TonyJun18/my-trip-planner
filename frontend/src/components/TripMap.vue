<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  // [{lat, lng, name, stop_type, description, day_number?, stop_id?,
  //   estimated_cost?, details?: {rating?, address?, source?, image_url?}}]
  markers: { type: Array, default: () => [] },
  height: { type: String, default: '480px' },
  // 地图拖拽修订（task-map-drag-edit）：允许拖动 marker 改坐标。
  // 移动端（≤768px）自动隐藏拖拽（触控误触率高，且移动端视图要求隐藏拖拽）。
  draggable: { type: Boolean, default: false },
  // 拖拽结束回调：onMove({ name, lat, lng, day_number, stop_id })。
  // 父组件负责调用 /map-edit API 并刷新 markers；本组件只发出事件。
  onMove: { type: Function, default: null },
})

const mapEl = ref(null)
let map = null
let markerLayer = null
let polylines = [] // 按日连线：每天一条（task-map-pin-cards 当日路线视觉化）

const typeColors = { attraction: '#ff385c', food: '#c2410c', hotel: '#0d8a5f' }
const typeLabel = { attraction: () => t('common.typeAttraction'), food: () => t('common.typeFood'), hotel: () => t('common.typeHotel') }

// 按日连线配色：每天一种颜色，循环使用（跨天不混淆）
const DAY_LINE_COLORS = ['#ff385c', '#0d8a5f', '#2563eb', '#c2410c', '#7c3aed', '#0891b2', '#d97706']

// 移动端隐藏拖拽：拖拽需要精确点击，触控设备误触率极高。
// 与「task-trip-collab-vote」的移动端适配同策略——响应式能力，不读状态。
function isMobileViewport() {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches
}

// 自定义 divIcon（避免 Leaflet 默认 marker 图片加载失败）
function makeIcon(stopType, order) {
  const color = typeColors[stopType] || '#ff385c'
  return L.divIcon({
    className: 'trip-marker',
    html: `<div style="
      width: 30px; height: 30px; border-radius: 50%;
      background: ${color}; color: #fff; font-size: 13px; font-weight: 600;
      display: flex; align-items: center; justify-content: center;
      border: 2.5px solid #fff; box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    ">${order}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  })
}

// —— pin 信息卡（task-map-pin-cards）——
// 用 DOM API 构建（textContent），杜绝 name/description/details 的 HTML 注入
// （数据可来自 LLM 输出或被受邀编辑者写入 → 存储型 XSS 面）。
// 卡片内容：图片占位 / 标题 / 类型 / 评分 / 一句话理由 / 预算标注。
function buildPopupContent(m, i) {
  const box = document.createElement('div')
  box.className = 'trip-popup-card'

  // 图片占位：有 image_url 时加载真实图（只允许 http(s)，失败回退占位）；
  // 否则灰色占位块（保证卡片布局稳定，移动端同样可用）。
  const imgWrap = document.createElement('div')
  imgWrap.className = 'trip-popup-img'
  const url = m.details?.image_url || m.image_url
  if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
    const img = document.createElement('img')
    img.src = url
    img.alt = m.name || ''
    img.loading = 'lazy'
    img.referrerPolicy = 'no-referrer'
    img.addEventListener('error', () => {
      imgWrap.textContent = ''
      imgWrap.appendChild(makeImagePlaceholder())
    })
    imgWrap.appendChild(img)
  } else {
    imgWrap.appendChild(makeImagePlaceholder())
  }
  box.appendChild(imgWrap)

  // 标题 + 序号
  const title = document.createElement('div')
  title.className = 'trip-popup-title'
  title.textContent = `${i + 1}. ${m.name}`
  box.appendChild(title)

  // 类型 + 评分（details.rating 有值才显示）
  const meta = document.createElement('div')
  meta.className = 'trip-popup-meta'
  const stopType = m.stop_type || m.type || 'attraction'
  const typeEl = document.createElement('span')
  typeEl.className = 'trip-popup-type'
  typeEl.textContent = typeLabel[stopType] ? typeLabel[stopType]() : stopType
  meta.appendChild(typeEl)
  const rating = Number(m.details?.rating ?? m.rating)
  if (Number.isFinite(rating) && rating > 0) {
    const ratingEl = document.createElement('span')
    ratingEl.className = 'trip-popup-rating'
    ratingEl.textContent = `★ ${rating.toFixed(1)}`
    meta.appendChild(ratingEl)
  }
  box.appendChild(meta)

  // 一句话理由
  if (m.description) {
    const descEl = document.createElement('div')
    descEl.className = 'trip-popup-desc'
    descEl.textContent = m.description
    box.appendChild(descEl)
  }

  // 预算标注：estimated_cost 有值 → ¥金额；0 → 免费；null → 不渲染
  const cost = m.estimated_cost
  if (typeof cost === 'number' && Number.isFinite(cost)) {
    const costEl = document.createElement('div')
    costEl.className = 'trip-popup-cost'
    if (cost <= 0) {
      costEl.textContent = `· ${t('common.mapFree')}`
    } else {
      costEl.textContent = `· ${t('common.budget')}: ¥${cost.toFixed(0)}`
    }
    box.appendChild(costEl)
  }

  return box
}

function makeImagePlaceholder() {
  const ph = document.createElement('div')
  ph.className = 'trip-popup-img-ph'
  const icon = document.createElement('span')
  icon.textContent = '🖼'
  ph.appendChild(icon)
  const tip = document.createElement('small')
  tip.textContent = t('common.mapImagePlaceholder')
  ph.appendChild(tip)
  return ph
}

function renderMarkers(markers) {
  if (!map) return
  markerLayer?.clearLayers()
  polylines.forEach((p) => p.remove())
  polylines = []

  const valid = markers.filter((m) => typeof m.lat === 'number' && typeof m.lng === 'number')
  if (!valid.length) return

  // 拖拽只在桌面端启用（移动端自动隐藏，满足验收「移动端隐藏拖拽」）
  const canDrag = props.draggable && !isMobileViewport()

  valid.forEach((m, i) => {
    const stopType = m.stop_type || m.type || 'attraction'
    const icon = makeIcon(stopType, i + 1)

    const marker = L.marker([m.lat, m.lng], { icon, draggable: canDrag }).addTo(markerLayer)
    marker.bindPopup(buildPopupContent(m, i), { maxWidth: 260, minWidth: 200 })

    if (canDrag) {
      marker.on('dragend', (ev) => {
        const ll = ev.target.getLatLng()
        // 只发出事件，不在这里改数据；父组件决定是否调 API。
        // 若父组件拒绝（如自驾约束 400），会重新渲染 markers 把 marker 拉回原位。
        props.onMove?.({
          name: m.name,
          lat: ll.lat,
          lng: ll.lng,
          day_number: m.day_number,
          stop_id: m.stop_id,
        })
      })
    }
  })

  // 当日路线视觉化（task-map-pin-cards）：按 day_number 分组连线，每天一条；
  // 未带 day_number 的站点回退为一条「全部连线」（兼容旧调用方）。
  const groups = new Map() // day_number|null -> [{m, i}]
  for (let i = 0; i < valid.length; i++) {
    const key = valid[i].day_number ?? null
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push({ m: valid[i], i })
  }
  // 有分组的用分组色，无分组的用默认行程色
  const colorFor = (key) => {
    if (key === null) return '#ff385c'
    return DAY_LINE_COLORS[(key - 1) % DAY_LINE_COLORS.length]
  }
  for (const [key, items] of groups) {
    const pts = items.map(({ m }) => [m.lat, m.lng])
    if (pts.length < 2) continue
    polylines.push(
      L.polyline(pts, { color: colorFor(key), weight: 3, opacity: 0.55, dashArray: '6,8' }).addTo(map),
    )
  }

  // 自适应视野
  const bounds = L.latLngBounds(valid.map((m) => [m.lat, m.lng]))
  map.fitBounds(bounds.pad(0.2), { maxZoom: 15 })
}

onMounted(() => {
  map = L.map(mapEl.value, { attributionControl: false }).setView([30.245, 120.15], 9)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map)
  markerLayer = L.layerGroup().addTo(map)
  renderMarkers(props.markers)
})

watch(
  () => props.markers,
  (m) => renderMarkers(m),
  { deep: true },
)

onBeforeUnmount(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="mapEl" class="trip-map" :style="{ height }" />
</template>

<style>
.trip-map {
  width: 100%;
  border-radius: 12px;
  z-index: 0;
  border: 1px solid #ebebeb;
}
.trip-marker {
  background: transparent;
  border: none;
}
/* 拖拽光标提示（桌面端可拖） */
.trip-map .leaflet-marker-icon[draggable='true'] {
  cursor: grab;
}
.trip-map .leaflet-marker-icon[draggable='true']:active {
  cursor: grabbing;
}
/* ── pin 信息卡（task-map-pin-cards）── */
.trip-popup-card {
  padding: 2px 0;
  min-width: 180px;
}
.trip-popup-img {
  width: 100%;
  height: 84px;
  border-radius: 8px;
  overflow: hidden;
  background: #f4f4f5;
  margin-bottom: 8px;
}
.trip-popup-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.trip-popup-img-ph {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: #a8a8aa;
  font-size: 14px;
}
.trip-popup-img-ph small {
  font-size: 11px;
  color: #c2c2c5;
}
.trip-popup-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  margin-bottom: 4px;
}
.trip-popup-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.trip-popup-type {
  font-size: 12px;
  color: #6a6a6a;
  background: #f4f4f5;
  border-radius: 4px;
  padding: 1px 6px;
}
.trip-popup-rating {
  font-size: 12px;
  color: #d97706;
  font-weight: 600;
}
.trip-popup-desc {
  font-size: 12px;
  color: #929292;
  line-height: 1.5;
  margin-bottom: 4px;
}
.trip-popup-cost {
  font-size: 12px;
  color: #0d8a5f;
  font-weight: 500;
}
/* 移动端信息卡宽度适配（验收「移动端可用」） */
@media (max-width: 640px) {
  .leaflet-popup-content-wrapper {
    max-width: calc(100vw - 48px) !important;
  }
  .trip-popup-card {
    min-width: 0;
  }
}
/* 移动端地图高度压缩：height 由父组件内联传入，必须 !important 覆盖（task-mobile-views） */
@media (max-width: 640px) {
  .trip-map { height: 300px !important; }
}
</style>