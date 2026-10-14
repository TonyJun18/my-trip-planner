// 拖拽仅对 owner 开放（受邀编辑走分享页 editMode，本视图为 owner 主入口）：
// 详情页路由是登录态 owner 视角，无 isOwner 标志 → 直接允许（后端 /map-edit 只认 owner 鉴权）。
// 移动端由 TripMap 内部 isMobileViewport() 自动隐藏拖拽（验收「移动端隐藏拖拽」）。
const canMapDrag = computed(() => !offlineFallback.value)

// ── 地图拖拽修订（task-map-drag-edit）：拖动 marker 改坐标 ──────
// 后端内核（POST /trips/{id}/map-edit 最小 diff 原子应用 + DrivingGate 约束门）已在 main，
// 这里完成 TripDetailView 接线：拖拽结束 → 调 mapEditTrip → 成功刷新（marker 落到新位置 +
// 预算/自驾重算），失败（如自驾约束 400）→ 重新 load 让 marker 弹回原位 + 内联提示。
const mapDragBusy = ref(false)
const mapDragError = ref('')
async function onMapMove({ name, lat, lng, day_number }) {
  if (mapDragBusy.value || !trip.value?.id) return
  mapDragBusy.value = true
  mapDragError.value = ''
  try {
    const r = await api.mapEditTrip(trip.value.id, { name, lat, lng, day_number })
    if (r.applied) {
      ElMessage.success(t('tripDetail.mapDragMoved'))
      budget.value = null
      await load()
    } else {
      mapDragError.value = t('tripDetail.mapDragNoop')
      await load()
    }
  } catch (e) {
    // DrivingGate 拒绝 → 内联展示后端 detail.issues（避免抬手即被全局 toast 淹没）；
    // 其余错误走拦截器 toast。无论如何重新 load，让 marker 弹回原位（组件只发事件不改数据）。
    const detail = e?.response?.data?.error?.detail
    const issues = Array.isArray(detail?.issues) ? detail.issues : []
    mapDragError.value = issues.length
      ? t('tripDetail.mapDragRejected', { msg: issues[0] })
      : t('tripDetail.mapDragFail')
    await load()
  } finally {
    mapDragBusy.value = false
            <el-alert
              v-if="mapDragError"
              class="map-drag-error"
              type="warning"
              :closable="false"
              show-icon
              :title="mapDragError"
            />
            <TripMap
              :markers="markers"
              height="420px"
              :draggable="canMapDrag"
              :on-move="onMapMove"
            />
