<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps({
  // [{lat, lng, name, type, description}]
  markers: { type: Array, default: () => [] },
  height: { type: String, default: '480px' },
})

const mapEl = ref(null)
let map = null
let markerLayer = null
let polyline = null

const typeColors = { attraction: '#ff385c', food: '#c2410c', hotel: '#0d8a5f' }
const typeLabel = { attraction: '景点', food: '餐饮', hotel: '住宿' }

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

  valid.forEach((m, i) => {
    const t = m.stop_type || m.type || 'attraction'
    const icon = makeIcon(t, i + 1)
    const label = typeLabel[t] || t
    const popup = L.popup().setContent(
      `<b>${i + 1}. ${m.name}</b><br/><span style="color:#6a6a6a">${label}</span>` +
        (m.description ? `<br/><small style="color:#929292">${m.description}</small>` : ''),
    )
    L.marker([m.lat, m.lng], { icon }).addTo(markerLayer).bindPopup(popup)
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
</style>