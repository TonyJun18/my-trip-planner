// 行程拖拽编辑草稿（task-floattrip-borrow Story 1）
//
// 设计：
// - 拖拽/上移/下移只改本地 trip.days 内 stops 顺序（响应式），**不落库**；
// - 撤销/重做覆盖顺序变更（undo/redo 双栈，快照式恢复）；
// - 「保存」才把有变动的天提交 POST /trips/{id}/reorder-commit
//   （服务端原子落库 + DrivingGate 前置 + 预算重算），失败保留草稿可重试；
// - 未保存退出（切页/刷新）不产生任何写操作 → 草稿自然丢弃，后端无半保存。
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import * as api from '@/api'

export function useDragEdit({ getTrip, afterSave }) {
  const { t } = useI18n()

  // undo 栈：每项 {dayId, order}（该日变更前的顺序快照）
  const undoStack = ref([])
  const redoStack = ref([])
  // dirty 标记：dayId -> {original, current}（original 在首次改动时冻结）
  const dirtyDays = ref({})
  const saving = ref(false)

  const canUndo = computed(() => undoStack.value.length > 0)
  const canRedo = computed(() => redoStack.value.length > 0)
  const dirty = computed(() => Object.keys(dirtyDays.value).length > 0)

  function _day(dayId) {
    const trip = getTrip()
    if (!trip) return null
    return (trip.days || []).find((d) => d.id === dayId) || null
  }

  function _orderOf(day) {
    return (day?.stops || []).map((s) => s.id)
  }

  function _freezeOriginal(day) {
    const rec = dirtyDays.value[day.id]
    if (rec) return rec
    const rec2 = { original: [..._orderOf(day)], current: [..._orderOf(day)] }
    dirtyDays.value[day.id] = rec2
    return rec2
  }

  function _touch(day) {
    const rec = _freezeOriginal(day)
    rec.current = [..._orderOf(day)]
  }

  function _applyOrder(day, order) {
    const trip = getTrip()
    if (!trip || !day) return
    const byId = {}
    for (const s of day.stops) byId[s.id] = s
    day.stops = order.map((id) => byId[id]).filter(Boolean)
    _touch(day)
  }

  // 在变更前记录待恢复快照（同一次连续操作只记一次：最后一次撤销到最初）
  function _pushUndo(day) {
    if (undoStack.value.length && undoStack.value[undoStack.value.length - 1].dayId === day.id) {
      // 同一天连续操作：更新栈顶为首个快照（撤销一步回到最初）
      if (!undoStack.value[undoStack.value.length - 1].order.some((id) => !_orderOf(day).includes(id))) {
        // 保持简单：栈顶若仍包含当前全部 id 则更新为更早的快照
        const earliest = dirtyDays.value[day.id]?.original
        if (earliest) undoStack.value[undoStack.value.length - 1].order = earliest
        redoStack.value = []
        return
      }
    }
    undoStack.value.push({ dayId: day.id, order: [..._orderOf(day)] })
    redoStack.value = []
  }

  // ── 操作 ────────────────────────────────────────────────
  function move(day, idx, dir) {
    const stops = day?.stops || []
    const target = idx + dir
    if (idx < 0 || target < 0 || target >= stops.length) return
    _pushUndo(day)
    const order = _orderOf(day)
    ;[order[idx], order[target]] = [order[target], order[idx]]
    _applyOrder(day, order)
  }

  function moveTo(day, fromIdx, toIdx) {
    const stops = day?.stops || []
    if (fromIdx < 0 || fromIdx >= stops.length || toIdx < 0 || toIdx >= stops.length || fromIdx === toIdx) return
    _pushUndo(day)
    const order = _orderOf(day)
    const [picked] = order.splice(fromIdx, 1)
    order.splice(toIdx, 0, picked)
    _applyOrder(day, order)
  }

  function undo() {
    const snap = undoStack.value.pop()
    if (!snap) return
    const day = _day(snap.dayId)
    if (!day) return
    // 当前顺序入 redo
    redoStack.value.push({ dayId: day.id, order: [..._orderOf(day)] })
    _applyOrder(day, snap.order)
  }

  function redo() {
    const snap = redoStack.value.pop()
    if (!snap) return
    const day = _day(snap.dayId)
    if (!day) return
    undoStack.value.push({ dayId: day.id, order: [..._orderOf(day)] })
    _applyOrder(day, snap.order)
  }

  // 重置（外部加载成功后调用：清空草稿/栈）
  function reset() {
    undoStack.value = []
    redoStack.value = []
    dirtyDays.value = {}
  }

  // ── 保存：只提交有变动的天 ──────────────────────────────
  async function save() {
    const trip = getTrip()
    if (!trip) return
    const changed = []
    for (const [dayId, rec] of Object.entries(dirtyDays.value)) {
      const day = _day(dayId)
      if (!day) continue
      const cur = _orderOf(day)
      const orig = rec.original || []
      if (cur.length !== orig.length || cur.some((id, i) => id !== orig[i])) {
        changed.push({ day_id: dayId, order: cur })
      }
    }
    if (changed.length === 0) {
      reset()
      return
    }
    saving.value = true
    try {
      await api.reorderCommit(trip.id, changed)
      ElMessage.success(t('tripDetail.reorderSaved'))
      reset()
      afterSave?.()
    } catch {
      // api 拦截器已 toast；草稿保留，用户可撤销或重试
    } finally {
      saving.value = false
    }
  }

  return { canUndo, canRedo, dirty, saving, move, moveTo, undo, redo, save, reset }
}