<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps({
  // [{lat, lng, name, stop_type, description, day_number?, stop_id?}]
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
let polyline = null

const typeColors = { attraction: '#ff385c', food: '#c2410c', hotel: '#0d8a5f' }
const typeLabel = { attraction: '景点', food: '餐饮', hotel: '住宿' }

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

function renderMarkers(markers) {
  if (!map) return
  markerLayer?.clearLayers()
  polyline?.remove()

  const valid = markers.filter((m) => typeof m.lat === 'number' && typeof m.lng === 'number')
  if (!valid.length) return

  // 拖拽只在桌面端启用（移动端自动隐藏，满足验收「移动端隐藏拖拽」）
  const canDrag = props.draggable && !isMobileViewport()

  valid.forEach((m, i) => {
    const t = m.stop_type || m.type || 'attraction'
    const icon = makeIcon(t, i + 1)
    const label = typeLabel[t] || t
    // 用 DOM API 构建 popup（textContent），杜绝 name/description 的 HTML 注入
    // （数据可来自 LLM 输出或被受邀编辑者写入 → 存储型 XSS 面）
    const popupEl = document.createElement('div')
    const title = document.createElement('b')
    title.textContent = `${i + 1}. ${m.name}`
    popupEl.appendChild(title)
    popupEl.appendChild(document.createElement('br'))
    const typeEl = document.createElement('span')
    typeEl.style.color = '#6a6a6a'
    typeEl.textContent = label
    popupEl.appendChild(typeEl)
    if (m.description) {
      popupEl.appendChild(document.createElement('br'))
      const descEl = document.createElement('small')
      descEl.style.color = '#929292'
      descEl.textContent = m.description
      popupEl.appendChild(descEl)
    }

    const marker = L.marker([m.lat, m.lng], { icon, draggable: canDrag }).addTo(markerLayer)
    marker.bindPopup(popupEl)

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

  // 游览路线（按顺序连点成线）
  if (valid.length >= 2) {
    polyline = L.polyline(
      valid.map((m) => [m.lat, m.lng]),
      { color: '#ff385c', weight: 3, opacity: 0.55, dashArray: '6,8' },
    ).addTo(map)
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
/* 移动端：leaflet 高度收紧（inline height 由父组件 prop 控制，需 !important 覆盖），
   375px 下 420px 的桌面高度会占据整屏，压缩到 300px 提升站点列表可读性 */
@media (max-width: 720px) {
  .trip-map {
    height: 300px !important;
  }
}
</style>