import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api'

/**
 * 编辑对话框域（三合一：编辑行程 / 添加日程 / 添加或编辑站点）。
 *
 * 表单状态、打开逻辑、保存与删除动作全部收敛在此；
 * 模板的 el-dialog 只负责渲染与绑定。
 */
export function useEditDialog({ trip, afterSave } = {}) {
  const route = useRoute()
  const { t } = useI18n()

  const editType = ref(null) // 'edit-trip' | 'add-day' | 'edit-stop' | 'add-stop'
  const editDayId = ref(null)
  const editStopId = ref(null)
  const dialogVisible = ref(false)
  const stopFormRef = ref(null)

  const stopForm = ref({ name: '', stop_type: 'attraction', lat: null, lng: null, description: '', estimated_cost: null, estimated_duration_minutes: null })
  const dayForm = ref({ day_number: 1 })
  const tripForm = ref({ title: '', destination: '', departure: '', trip_type: '', travelers: 1, budget: null })

  // 出行性质选项（与 AI 规划/手动创建同款契约值：稳定中文，后端按此约束）
  const tripTypeOptions = [
    { key: 'tripTypeLeisure', value: '休闲旅游' },
    { key: 'tripTypeBusiness', value: '商务出差' },
    { key: 'tripTypeFamily', value: '亲子出游' },
    { key: 'tripTypeHoneymoon', value: '蜜月度假' },
    { key: 'tripTypeVisiting', value: '探亲访友' },
  ]

  function tripTypeDisplay(v) {
    const found = tripTypeOptions.find((o) => o.value === v)
    return found ? t('tripList.' + found.key) : v
  }

  function blankStopForm() {
    return { name: '', stop_type: 'attraction', lat: null, lng: null, description: '', estimated_cost: null, estimated_duration_minutes: null }
  }

  // 打开：编辑行程基本信息
  function openEditTrip() {
    tripForm.value = {
      title: trip.value.title,
      destination: trip.value.destination,
      departure: trip.value.departure || '',
      trip_type: trip.value.trip_type || '休闲旅游',
      travelers: trip.value.travelers,
      budget: trip.value.budget,
    }
    editType.value = 'edit-trip'
    dialogVisible.value = true
  }

  async function saveTrip() {
    const data = {}
    if (tripForm.value.title !== trip.value.title) data.title = tripForm.value.title
    if (tripForm.value.destination !== trip.value.destination) data.destination = tripForm.value.destination
    if ((tripForm.value.departure || '') !== (trip.value.departure || '')) data.departure = tripForm.value.departure || null
    if (tripForm.value.trip_type !== (trip.value.trip_type || '休闲旅游')) data.trip_type = tripForm.value.trip_type
    if (tripForm.value.travelers !== trip.value.travelers) data.travelers = tripForm.value.travelers
    if (tripForm.value.budget !== trip.value.budget) data.budget = tripForm.value.budget
    await api.updateTrip(trip.value.id, data)
    ElMessage.success(t('tripDetail.saved'))
    dialogVisible.value = false
    afterSave?.()
  }

  // 打开：添加日程
  function openAddDay() {
    const maxDay = trip.value.days.reduce((m, d) => Math.max(m, d.day_number), 0)
    dayForm.value = { day_number: maxDay + 1 }
    editType.value = 'add-day'
    dialogVisible.value = true
  }

  async function saveDay() {
    await api.addDay(trip.value.id, dayForm.value)
    ElMessage.success(t('tripDetail.dayAdded'))
    dialogVisible.value = false
    afterSave?.()
  }

  // 站点：编辑（拷入/清空 null）与添加
  function openEditStop(day, stop) {
    editDayId.value = day.id
    editStopId.value = stop.id
    stopForm.value = {
      name: stop.name,
      stop_type: stop.stop_type || 'attraction',
      lat: stop.lat ?? '',
      lng: stop.lng ?? '',
      description: stop.description ?? '',
      estimated_cost: stop.estimated_cost ?? null,
      estimated_duration_minutes: stop.estimated_duration_minutes ?? null,
    }
    editType.value = 'edit-stop'
    dialogVisible.value = true
  }

  function openAddStop(dayId) {
    editDayId.value = dayId
    editStopId.value = null
    stopForm.value = blankStopForm()
    editType.value = 'add-stop'
    dialogVisible.value = true
  }

  function _nullEmpty(payload) {
    if (payload.lat === '' || payload.lat == null) payload.lat = null
    if (payload.lng === '' || payload.lng == null) payload.lng = null
    if (payload.estimated_cost === '' || payload.estimated_cost == null) payload.estimated_cost = null
    if (payload.estimated_duration_minutes === '' || payload.estimated_duration_minutes == null) payload.estimated_duration_minutes = null
    return payload
  }

  async function saveEditStop() {
    await stopFormRef.value.validate()
    const payload = _nullEmpty({ ...stopForm.value })
    await api.updateStop(editDayId.value, editStopId.value, payload)
    ElMessage.success(t('tripDetail.stopUpdated'))
    dialogVisible.value = false
    afterSave?.()
  }

  async function saveStop() {
    await stopFormRef.value.validate()
    const payload = _nullEmpty({ ...stopForm.value })
    await api.addStop(editDayId.value, payload)
    ElMessage.success(t('tripDetail.stopAdded'))
    dialogVisible.value = false
    afterSave?.()
  }

  // 上移 / 下移（整日顺序重排）
  async function moveStop(day, stop, dir) {
    const stops = day.stops
    const idx = stops.findIndex((s) => s.id === stop.id)
    const target = idx + dir
    if (idx < 0 || target < 0 || target >= stops.length) return
    const order = stops.map((s) => s.id)
    ;[order[idx], order[target]] = [order[target], order[idx]]
    try {
      await api.reorderStops(day.id, order)
      ElMessage.success(dir < 0 ? t('tripDetail.movedUp') : t('tripDetail.movedDown'))
      afterSave?.()
    } catch {
      // api 拦截器已 toast
    }
  }

  // 删除
  async function removeStop(day, stop) {
    try {
      await ElMessageBox.confirm(t('tripDetail.deleteStopConfirm', { name: stop.name }), t('common.confirm'), { type: 'warning' })
    } catch { return }
    await api.deleteStop(day.id, stop.id)
    ElMessage.success(t('tripDetail.deleted'))
    afterSave?.()
  }

  async function removeDay(day) {
    try {
      await ElMessageBox.confirm(t('tripDetail.deleteDayConfirm', { n: day.day_number }), t('common.confirm'), { type: 'warning' })
    } catch { return }
    await api.deleteDay(day.id)
    ElMessage.success(t('tripDetail.deleted'))
    afterSave?.()
  }

  async function removeTrip() {
    try {
      await ElMessageBox.confirm(t('tripDetail.deleteTripConfirm', { title: trip.value.title }), t('common.confirm'), { type: 'warning' })
    } catch { return }
    await api.deleteTrip(trip.value.id)
    ElMessage.success(t('tripDetail.deleted'))
    afterSave?.({ deleted: true })
  }

  return {
    editType, editDayId, editStopId, dialogVisible, stopFormRef,
    stopForm, dayForm, tripForm, tripTypeOptions, tripTypeDisplay,
    openEditTrip, saveTrip, openAddDay, saveDay,
    openEditStop, openAddStop, saveEditStop, saveStop,
    moveStop, removeStop, removeDay, removeTrip,
  }
}