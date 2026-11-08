import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api'

/**
 * 分享 / 收藏 / 画廊 / 受邀编辑权 域。
 *
 * 所有对外分享类操作（只读链接、编辑权、生命周期 TTL/吊销、收藏、画廊发布）
 * 集中在此；详情页顶部操作区与分享设置弹窗直接绑定。
 */
export function useTripShareActions({ trip, afterChange } = {}) {
  const route = useRoute()
  const { t } = useI18n()

  // ── 分享（只读链接） ──
  const sharing = ref(false)
  const xhsNoteVisible = ref(false)
  const importVisible = ref(false)

  async function doShare() {
    sharing.value = true
    try {
      const r = await api.createShare(trip.value.id)
      const url = r.share_url
      try {
        await navigator.clipboard.writeText(url)
        ElMessage.success(t('tripDetail.shareLinkCopied'))
      } catch {
        ElMessage.success(t('tripDetail.shareLink', { url }))
      }
    } catch {
      ElMessage.error(t('tripDetail.shareFail'))
    } finally {
      sharing.value = false
    }
  }

  // ── 发布到灵感画廊 ──
  const publishingGallery = ref(false)
  async function publishGallery() {
    try {
      const { value } = await ElMessageBox.prompt(t('tripDetail.galleryBlurbPrompt'), t('tripDetail.galleryPublish'), {
        confirmButtonText: t('tripDetail.galleryPublishOk'),
        cancelButtonText: t('common.cancel'),
        inputPlaceholder: t('tripDetail.galleryBlurbPlaceholder'),
        inputValidator: (v) => (v || '').length <= 200 || t('tripDetail.galleryBlurbTooLong'),
      })
      publishingGallery.value = true
      await api.publishToGallery(trip.value.id, { blurb: value || '' })
      ElMessage.success(t('tripDetail.galleryPublished'))
    } catch (e) {
      if (e !== 'cancel') ElMessage.error(t('tripDetail.galleryPublishFail'))
    } finally {
      publishingGallery.value = false
    }
  }

  // ── 受邀编辑权 ──
  const editSharing = ref(false)
  const editRevoking = ref(false)
  async function doShareEdit() {
    editSharing.value = true
    try {
      const r = await api.createShareEdit(trip.value.id)
      const url = r.edit_url
      try {
        await navigator.clipboard.writeText(url)
        ElMessage.success(t('tripDetail.editLinkCopied'))
      } catch {
        ElMessage.success(t('tripDetail.editLink', { url }))
      }
      afterChange?.()
    } catch {
      ElMessage.error(t('tripDetail.openEditFail'))
    } finally {
      editSharing.value = false
    }
  }

  async function doRevokeShareEdit() {
    try {
      await ElMessageBox.confirm(t('tripDetail.revokeConfirmMsg'), t('tripDetail.revokeConfirmTitle'), { type: 'warning' })
    } catch { return }
    editRevoking.value = true
    try {
      await api.revokeShareEdit(trip.value.id)
      ElMessage.success(t('tripDetail.revoked'))
      afterChange?.()
    } catch {
      ElMessage.error(t('tripDetail.revokeFail'))
    } finally {
      editRevoking.value = false
    }
  }

  // ── 分享设置（生命周期：TTL / 吊销 / 审计） ──
  const shareSettingsVisible = ref(false)
  const lifecycleItems = ref([])
  const lifecycleLoading = ref(false)
  const ttlUpdating = ref(false)
  const revokingKind = ref('')

  async function openShareSettings() {
    shareSettingsVisible.value = true
    await loadShareLifecycle()
  }

  async function loadShareLifecycle() {
    lifecycleLoading.value = true
    try {
      lifecycleItems.value = await api.getShareLifecycle(trip.value.id)
    } catch {
      lifecycleItems.value = []
      ElMessage.error(t('tripDetail.shareLinkFetchFail'))
    } finally {
      lifecycleLoading.value = false
    }
  }

  const lifecycleStatus = (item) => {
    if (item.revoked_at) return 'revoked'
    if (item.expires_at && new Date(item.expires_at).getTime() <= Date.now()) return 'expired'
    return 'active'
  }

  function copyShareUrl(item) {
    const url = item.kind === 'edit' ? `${window.location.origin}/share/${item.token}?edit=1` : item.share_url
    if (!url) return
    navigator.clipboard.writeText(url).then(() => ElMessage.success(t('tripDetail.linkCopied')))
  }

  async function setTtl(kind, days) {
    ttlUpdating.value = true
    try {
      await api.setShareTokenTtl(trip.value.id, kind, days)
      ElMessage.success(t('tripDetail.shareTtlUpdated'))
      await loadShareLifecycle()
    } catch {
      ElMessage.error(t('tripDetail.shareTtlFail'))
    } finally {
      ttlUpdating.value = false
    }
  }

  async function revokeShareLink(item) {
    if (revokingKind.value) return
    try {
      await ElMessageBox.confirm(t('tripDetail.shareRevokeConfirmMsg'), t('tripDetail.shareRevokeConfirmTitle'), { type: 'warning' })
    } catch { return }
    revokingKind.value = item.kind
    try {
      await api.revokeShareToken(trip.value.id, item.kind)
      ElMessage.success(t('tripDetail.shareRevoked'))
      await loadShareLifecycle()
    } catch {
      ElMessage.error(t('tripDetail.shareRevokeFail'))
    } finally {
      revokingKind.value = ''
    }
  }

  const ttlOptions = computed(() => [
    { label: t('tripDetail.ttlPermanent'), value: 0 },
    { label: t('tripDetail.ttl1d'), value: 1 },
    { label: t('tripDetail.ttl7d'), value: 7 },
    { label: t('tripDetail.ttl30d'), value: 30 },
  ])

  // ── 访问密码（task-share-gate-eval：密码锁，与 TTL/吊销正交） ──
  // 密码只上送不回收：后端只回 has_password，前端不留存任何明文。
  const passwordUpdating = ref('') // 正在设置的 kind（'share' / 'edit'）

  async function setSharePassword(kind, password) {
    const pwd = String(password || '')
    if (pwd.length < 4) {
      ElMessage.warning(t('tripDetail.sharePasswordMin'))
      return false
    }
    passwordUpdating.value = kind
    try {
      await api.setSharePassword(trip.value.id, kind, pwd)
      ElMessage.success(t('tripDetail.sharePasswordSet'))
      await loadShareLifecycle()
      return true
    } catch {
      ElMessage.error(t('tripDetail.sharePasswordFail'))
      return false
    } finally {
      passwordUpdating.value = ''
    }
  }

  async function clearSharePassword(kind) {
    passwordUpdating.value = kind
    try {
      await api.setSharePassword(trip.value.id, kind, '')
      ElMessage.success(t('tripDetail.sharePasswordCleared'))
      await loadShareLifecycle()
      return true
    } catch {
      ElMessage.error(t('tripDetail.sharePasswordFail'))
      return false
    } finally {
      passwordUpdating.value = ''
    }
  }

  // ── 收藏（当前行程是否已收藏） ──
  const isFavorite = ref(false)
  const favoriting = ref(false)
  const hasSharedToken = computed(() => !!trip.value?.share_token)

  async function checkFavorite() {
    if (!trip.value?.id) return
    try {
      const favs = await api.listFavorites({ limit: 200 })
      isFavorite.value = favs.items?.some((f) => f.trip_id === trip.value.id) || false
    } catch {
      isFavorite.value = false
    }
  }

  async function toggleFavorite() {
    if (!trip.value?.id) return
    favoriting.value = true
    try {
      if (isFavorite.value) {
        await api.removeFavorite(trip.value.id)
        isFavorite.value = false
      } else {
        await api.addFavorite(trip.value.id)
        isFavorite.value = true
      }
    } catch {
      ElMessage.error(t('tripDetail.favoriteFail'))
    } finally {
      favoriting.value = false
    }
  }

  return {
    sharing, xhsNoteVisible, importVisible, doShare,
    publishingGallery, publishGallery,
    editSharing, editRevoking, doShareEdit, doRevokeShareEdit,
    shareSettingsVisible, lifecycleItems, lifecycleLoading, ttlUpdating, revokingKind,
    openShareSettings, loadShareLifecycle, lifecycleStatus, copyShareUrl, setTtl, revokeShareLink, ttlOptions,
    passwordUpdating, setSharePassword, clearSharePassword,
    isFavorite, favoriting, hasSharedToken, checkFavorite, toggleFavorite,
  }
}