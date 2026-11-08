import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { nextTick } from 'vue'
import * as api from '@/api'
import { exportImage, exportPdf } from '@/utils/export'

/**
 * 导出域：截图 / PDF / JSON 备份 / 打印。
 *
 * 依赖注入 ``exportEl``（模板 export-area 的 DOM ref）与 ``getTrip``（当前行程 ref
 * 的读取函数），便于主文件装配；导出文件名基于目的地。
 */
export function useExport({ exportEl, getTrip } = {}) {
  const { t } = useI18n()

  const exporting = ref(false)

  async function _guard(fn) {
    exporting.value = true
    try {
      await fn()
    } catch (e) {
      ElMessage.error(t('tripDetail.exportFail', { msg: e?.message || '' }))
    } finally {
      exporting.value = false
    }
  }

  async function doExportImage() {
    await _guard(async () => {
      const trip = getTrip()
      await nextTick()
      await exportImage(exportEl.value, `${trip.destination}-${t('tripDetail.exportImage')}`)
      ElMessage.success(t('tripDetail.imageExported'))
    })
  }

  async function doExportPdf() {
    await _guard(async () => {
      const trip = getTrip()
      await nextTick()
      await exportPdf(exportEl.value, `${trip.destination}-${t('tripDetail.exportPdf')}`)
      ElMessage.success(t('tripDetail.pdfExported'))
    })
  }

  async function doExportJson() {
    await _guard(async () => {
      const trip = getTrip()
      const blob = await api.exportTripJson(trip.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${trip.destination}-${trip.start_date}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      ElMessage.success(t('tripDetail.jsonExported'))
    })
  }

  function doPrint() {
    window.print()
  }

  /**
   * 导出 ICS 日历（task-ics-export）：落成 .ics 文件后由系统日历接管。
   * 与 JSON 导出一致：只导出当前行程，不携带任何令牌。
   */
  async function doExportIcs() {
    await _guard(async () => {
      const trip = getTrip()
      const blob = await api.exportTripIcs(trip.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${trip.destination}-${trip.start_date}.ics`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      ElMessage.success(t('tripDetail.icsExported'))
    })
  }

  return { exporting, doExportImage, doExportPdf, doExportJson, doExportIcs, doPrint }
}