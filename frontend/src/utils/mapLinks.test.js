/**
 * mapLinks 深链纯函数测试（task-day-map-deeplink，2026-11-14）
 */
import { describe, it, expect } from 'vitest'
import {
  MAX_MAP_STOPS,
  singleStopMapUrl,
  dayMapLinks,
  multiStopMapUrl,
  stopCoord,
} from './mapLinks.js'

const stop = (name, lat, lng) => ({ name, lat, lng })

describe('stopCoord', () => {
  it('缺失/非法坐标返回 null', () => {
    expect(stopCoord(null)).toBeNull()
    expect(stopCoord({})).toBeNull()
    expect(stopCoord({ lat: 0, lng: 0 })).toBeNull() // 0 视为缺失
    expect(stopCoord({ lat: 'abc', lng: 1 })).toBeNull()
    expect(stopCoord({ lat: NaN, lng: 1 })).toBeNull()
  })
  it('合法坐标返回数字对象', () => {
    expect(stopCoord(stop('A', 30.25, 120.15))).toEqual({ lat: 30.25, lng: 120.15 })
  })
})

describe('singleStopMapUrl', () => {
  it('缺坐标返回 null', () => {
    expect(singleStopMapUrl({ name: 'no-coord' })).toBeNull()
  })
  it('google 单点链接带坐标（URL 编码）与名称', () => {
    const url = singleStopMapUrl(stop('西湖', 30.25, 120.15))
    expect(url).toContain('google.com/maps/search/?api=1&query=30.25,120.15')
    expect(decodeURIComponent(url)).toContain('西湖')
  })
  it('苹果/高德 provider 各自产出', () => {
    const apple = singleStopMapUrl(stop('西湖', 30.25, 120.15), 'apple')
    expect(apple).toContain('maps.apple.com/?ll=30.25,120.15')
    const amap = singleStopMapUrl(stop('西湖', 30.25, 120.15), 'amap')
    expect(amap).toContain('uri.amap.com/marker?position=120.15,30.25')
  })
})

describe('multiStopMapUrl', () => {
  it('google 多站：origin/waypoints/destination 顺序正确（逗号被 URL 编码为 %2C）', () => {
    const url = multiStopMapUrl([stop('A', 1, 1), stop('B', 2, 2), stop('C', 3, 3)])
    expect(url).toContain('google.com/maps/dir/')
    expect(decodeURIComponent(url)).toContain('origin=1,1')
    expect(decodeURIComponent(url)).toContain('waypoints=2,2')
    expect(decodeURIComponent(url)).toContain('destination=3,3')
  })
  it('两站无 waypoints', () => {
    const url = multiStopMapUrl([stop('A', 1, 1), stop('B', 2, 2)])
    expect(decodeURIComponent(url)).toContain('origin=1,1')
    expect(url).not.toContain('waypoints')
    expect(decodeURIComponent(url)).toContain('destination=2,2')
  })
  it('apple 无 waypoints：只给首站单点', () => {
    const url = multiStopMapUrl([stop('A', 1, 1), stop('B', 2, 2)], 'apple')
    expect(url).toContain('maps.apple.com')
    expect(url).not.toContain('waypoints')
  })
  it('缺坐标跳过，不产生死链', () => {
    const url = multiStopMapUrl([stop('A', 1, 1), { name: 'no-coord' }, stop('C', 3, 3)])
    expect(decodeURIComponent(url)).toContain('origin=1,1')
    expect(decodeURIComponent(url)).toContain('destination=3,3')
  })
  it('全缺坐标返回 null', () => {
    expect(multiStopMapUrl([{ name: 'x' }])).toBeNull()
  })
})

describe('dayMapLinks', () => {
  it('空/全缺坐标 → 返回空', () => {
    expect(dayMapLinks([])).toEqual({ url: null, list: [] })
    expect(dayMapLinks([{ name: 'x' }])).toEqual({ url: null, list: [] })
  })
  it('单站 → url 单点链接', () => {
    const r = dayMapLinks([stop('A', 1, 1)])
    expect(r.url).toContain('google.com/maps/search/')
    expect(r.list).toEqual([])
  })
  it('≤9 站 → url 多站路线', () => {
    const stops = Array.from({ length: 9 }, (_, i) => stop(`S${i}`, i + 1, i + 1))
    const r = dayMapLinks(stops)
    expect(r.url).toContain('google.com/maps/dir/')
    expect(r.list).toEqual([])
  })
  it('>9 站 → 降级逐站列表，无 url', () => {
    const stops = Array.from({ length: 12 }, (_, i) => stop(`S${i}`, i + 1, i + 1))
    const r = dayMapLinks(stops)
    expect(r.url).toBeNull()
    expect(r.list.length).toBe(12)
    expect(r.list[0]).toContain('google.com/maps/search/')
  })
  it('>9 站中含缺坐标 → 列表剔除缺坐标', () => {
    const stops = Array.from({ length: 11 }, (_, i) => stop(`S${i}`, i + 1, i + 1))
    stops.push({ name: 'no-coord' })
    const r = dayMapLinks(stops)
    expect(r.list.length).toBe(11)
  })
  it('导出常量 MAX_MAP_STOPS=9', () => {
    expect(MAX_MAP_STOPS).toBe(9)
  })
})