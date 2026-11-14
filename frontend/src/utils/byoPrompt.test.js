/**
 * BYO-AI 草稿解析测试（task-byo-ai-import-kit，2026-11-14）
 */
import { describe, it, expect } from 'vitest'
import { buildByoPrompt, BYO_PROMPT_VERSION, parseByoDraft, parseByoLine, parseDuration } from './byoPrompt.js'

describe('buildByoPrompt', () => {
  it('中文 prompt 带版本号与四列格式说明', () => {
    const p = buildByoPrompt('zh-CN')
    expect(p).toContain(`版本 ${BYO_PROMPT_VERSION}`)
    expect(p).toContain('地点名｜类型（景点/美食/酒店）｜建议时长')
    expect(p).toContain('西湖｜景点｜3h')
  })
  it('英文 prompt 带版本号与格式（不含中文）', () => {
    const p = buildByoPrompt('en-US')
    expect(p).toContain(`version ${BYO_PROMPT_VERSION}`)
    expect(p).toContain('Name | Type (attraction/food/hotel)')
    expect(p).toContain('West Lake | attraction | 3h')
    expect(p).not.toMatch(/[\u4e00-\u9fff]/)
  })
})

describe('parseDuration', () => {
  it('各种时长格式', () => {
    expect(parseDuration('2h')).toBe(120)
    expect(parseDuration('1.5h')).toBe(90)
    expect(parseDuration('90min')).toBe(90)
    expect(parseDuration('2 小时')).toBe(120)
    expect(parseDuration('45分钟')).toBe(45)
    expect(parseDuration('no duration')).toBeNull()
    expect(parseDuration('')).toBeNull()
  })
})

describe('parseByoLine', () => {
  it('pipe 格式：名称｜类型｜时长｜备注', () => {
    expect(parseByoLine('西湖｜景点｜3h｜环湖骑行')).toEqual({
      name: '西湖', stop_type: 'attraction', estimated_duration_minutes: 180, description: '环湖骑行',
    })
  })
  it('英文 pipe 格式 + 类型归一', () => {
    expect(parseByoLine('Tokyo Tower | attraction | 90min | Skytree view')).toMatchObject({
      name: 'Tokyo Tower', stop_type: 'attraction', estimated_duration_minutes: 90,
    })
  })
  it('类型映射：美食→food、酒店→hotel', () => {
    expect(parseByoLine('楼外楼｜美食｜1.5h').stop_type).toBe('food')
    expect(parseByoLine('和平饭店｜酒店｜-').stop_type).toBe('hotel')
  })
  it('编号列表行：剥掉 1. 前缀', () => {
    expect(parseByoLine('1. 西湖｜景点｜3h').name).toBe('西湖')
    expect(parseByoLine('2. Tokyo Tower | attraction | 1h').name).toBe('Tokyo Tower')
  })
  it('bullet 行', () => {
    expect(parseByoLine('- 灵隐寺｜景点｜2h').name).toBe('灵隐寺')
    expect(parseByoLine('• 西湖｜景点').name).toBe('西湖')
  })
  it('名称过长/空 → null', () => {
    expect(parseByoLine('')).toBeNull()
    expect(parseByoLine('   ')).toBeNull()
    expect(parseByoLine('a'.repeat(50) + '｜景点')).toBeNull()
  })
  it('纯说明文字行 → null（散文降级）', () => {
    expect(parseByoLine('以下是给你的行程：')).toBeNull()
  })
  it('名称带注记括号被清理', () => {
    expect(parseByoLine('西湖（免费）｜景点｜2h').name).toBe('西湖')
  })
})

describe('parseByoDraft', () => {
  const PIPE = `西湖｜景点｜3h｜环湖骑行
楼外楼｜美食｜1.5h｜西湖醋鱼
上海和平饭店｜酒店｜-｜外滩景观房`

  const NUMBERED = `1. 西湖｜景点｜3h
2. 灵隐寺｜景点｜2h
3. 楼外楼｜美食｜1.5h`

  const PROSE = `我们在杭州玩了三天，西湖特别漂亮，苏堤上骑车很舒服。灵隐寺人很多，建议早点去。午饭在楼外楼吃的西湖醋鱼，很好吃。`

  it('pipe fixture：3 行全解析，类型/时长/备注正确', () => {
    const r = parseByoDraft(PIPE)
    expect(r).toHaveLength(3)
    const byName = Object.fromEntries(r.map((x) => [x.name, x]))
    expect(byName['西湖']).toMatchObject({ stop_type: 'attraction', estimated_duration_minutes: 180, description: '环湖骑行' })
    expect(byName['楼外楼']).toMatchObject({ stop_type: 'food', estimated_duration_minutes: 90 })
    expect(byName['上海和平饭店']).toMatchObject({ stop_type: 'hotel' })
  })

  it('编号 fixture：剥前缀，3 行', () => {
    const r = parseByoDraft(NUMBERED)
    expect(r).toHaveLength(3)
    expect(r[0].name).toBe('西湖')
    expect(r[1].name).toBe('灵隐寺')
  })

  it('散文 fixture：无候选（返回空数组，调用方降级 note import）', () => {
    expect(parseByoDraft(PROSE)).toEqual([])
  })

  it('空输入 / 空白 / 超长输入', () => {
    expect(parseByoDraft('')).toEqual([])
    expect(parseByoDraft('   \n  ')).toEqual([])
    expect(parseByoDraft('x'.repeat(3000))).toEqual([])
  })

  it('去重：同名同类型只留第一个', () => {
    const r = parseByoDraft('西湖｜景点｜3h\n西湖｜景点｜2h\n西湖｜美食｜1h')
    expect(r).toHaveLength(2)
    expect(r[0].estimated_duration_minutes).toBe(180)
  })
})