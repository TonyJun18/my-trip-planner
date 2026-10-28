// API 统一出口（兼容层）。
//
// 实际实现按域拆到 `./modules/*`：auth / trips / share / live / plan / planner /
// favorites / discovery / events / chat / ws。本文件把所有符号再导出，保持
// `import { xx } from '@/api'` 的既有调用方零改动。
//
// 新代码可直接 `import { xx } from '@/api/modules/trips'`，按域引用更清晰。

export * from './modules/auth'
export * from './modules/trips'
export * from './modules/share'
export * from './modules/live'
export * from './modules/plan'
export * from './modules/planner'
export * from './modules/favorites'
export * from './modules/discovery'
export * from './modules/events'
export * from './modules/chat'
export * from './modules/ws'

// 兼容旧调用方直接引用默认导出（极少）
export { default as http } from './http'