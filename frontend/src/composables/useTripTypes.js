import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * 站点类型展示映射（从原 TripDetailView 抽出，供 LiveToday / DayCard 等共享）。
 * typeLabel 依赖 i18n，作为 composable 返回，避免重复定义三份。
 */
export function useTripTypes() {
  const { t } = useI18n()

  const typeLabel = computed(() => ({
    attraction: t('common.typeAttraction'),
    food: t('common.typeFood'),
    hotel: t('common.typeHotel'),
    transport: t('common.typeTransport'),
  }))

  const typeColor = { attraction: 'var(--brand)', food: '#c2410c', hotel: '#0d8a5f', transport: '#5b6ee1' }
  const typeEmoji = { attraction: '🏞️', food: '🍜', hotel: '🏨', transport: '🚄' }

  return { typeLabel, typeColor, typeEmoji }
}