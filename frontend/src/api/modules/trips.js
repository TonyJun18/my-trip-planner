import http from '../http'

// ── trips CRUD ────────────────────────────────────────────
export const listTrips = (params = {}) => http.get('/trips', { params }).then((r) => r.data)
export const getTrip = (id) => http.get(`/trips/${id}`).then((r) => r.data)
export const createTrip = (data) => http.post('/trips', data).then((r) => r.data)
export const updateTrip = (id, data) => http.patch(`/trips/${id}`, data).then((r) => r.data)
export const deleteTrip = (id) => http.delete(`/trips/${id}`)

// ── days / stops ──────────────────────────────────────────
export const addDay = (tripId, data) => http.post(`/trips/${tripId}/days`, data).then((r) => r.data)
export const generateDays = (tripId, start, end) =>
  http.post(`/trips/${tripId}/days/generate`, null, { params: { start, end } }).then((r) => r.data)
export const addStop = (dayId, data) => http.post(`/trips/days/${dayId}/stops`, data).then((r) => r.data)
export const updateStop = (dayId, stopId, data) => http.patch(`/trips/days/${dayId}/stops/${stopId}`, data).then((r) => r.data)
export const reorderStops = (dayId, order) => http.put(`/trips/days/${dayId}/stops/order`, { order }).then((r) => r.data)
export const deleteDay = (dayId) => http.delete(`/trips/days/${dayId}`)
export const deleteStop = (dayId, stopId) => http.delete(`/trips/days/${dayId}/stops/${stopId}`)

// ── budget / plan ─────────────────────────────────────────
export const getBudget = (tripId) => http.get(`/trips/${tripId}/budget`).then((r) => r.data)
export const getTripPlan = (tripId) => http.get(`/trips/${tripId}/plan`).then((r) => r.data)