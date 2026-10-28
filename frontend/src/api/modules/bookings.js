import http from '../http'

// ── 预订（task-booking-outlink：可预订建议 + 凭证回填 + 状态机） ──
export const listBookings = (tripId) => http.get(`/trips/${tripId}/bookings`).then((r) => r.data)
export const addBooking = (tripId, data) => http.post(`/trips/${tripId}/bookings`, data).then((r) => r.data)
export const updateBookingStatus = (tripId, bookingId, data) =>
  http.post(`/trips/${tripId}/bookings/${bookingId}/status`, data).then((r) => r.data)
export const deleteBooking = (tripId, bookingId) =>
  http.delete(`/trips/${tripId}/bookings/${bookingId}`)

// ── 旅程全程追踪（task-journey-timeline：投影） ──
export const getJourney = (tripId) => http.get(`/trips/${tripId}/journey`).then((r) => r.data)

// ── 旅程护照（task-journey-passport：徽章墙） ──
export const getPassport = (tripId) => http.get(`/trips/${tripId}/passport`).then((r) => r.data)
export const getSharedPassport = (token) => http.get(`/trips/share/${token}/passport`).then((r) => r.data)

// ── 旅程故事（task-trip-story：晒图高光卡） ──
export const generateStory = (tripId, channel = 'xhs') =>
  http.post(`/trips/${tripId}/story`, { channel }).then((r) => r.data)