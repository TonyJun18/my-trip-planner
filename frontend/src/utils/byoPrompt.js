/**
 * BYO-AI 草稿回填（task-byo-ai-import-kit，2026-11-14）
 *
 * - buildByoPrompt(locale)：生成可复制的 prompt，让用户去自己的 AI（Claude/ChatGPT/
 *   Grok…）生成「行程草稿」，格式固定为每行「地点名｜类型｜建议时长｜备注」。
 * - parseByoDraft(text)：容错解析 AI 输出——支持 pipe / 编号列表 / 普通 bullet；
 *   散文（无结构）降级返回 null，调用方走 note import。
 *
 * 安全红线：本模块只产出「候选数据」，绝不自动落库；落库前必须人工勾选。
 */
export const BYO_PROMPT_VERSION = '1'

/** 类型映射：AI 可能给中文/英文类型词，归一为后端 stop_type 契约值 */
const TYPE_MAP = {
  attraction: 'attraction', 景点: 'attraction', 景点区: 'attraction', 名胜: 'attraction',
  see: 'attraction', sight: 'attraction', sightseeing: 'attraction', landmark: 'attraction',
  food: 'food', 美食: 'food', 餐饮: 'food', 餐厅: 'food', 饭店: 'food', 小吃: 'food',
  restaurant: 'food', cafe: 'food', 咖啡: 'food',
  hotel: 'hotel', 酒店: 'hotel', 住宿: 'hotel', 民宿: 'hotel', 旅馆: 'hotel',
  stay: 'hotel', accommodation: 'hotel', lodging: 'hotel',
}
const TYPE_KEYS = Object.keys(TYPE_MAP).join('|')

/** 单元格可能含空格/括号注记，如「西湖（免费）｜景点｜2h」→ 名称取主名 */
function cleanName(raw) {
  const s = String(raw || '').trim()
  // 去掉常见注记括号（全半角）
  return s.replace(/[（(][^（）()]*[）)]/g, '').trim()
}

/**
 * 解析一行 AI 草稿行，返回 { name, stop_type, estimated_duration_minutes, description }
 * 或 null（该行不构成候选）。首列必须像地点名（≤40 字、非句子主语）。
 */
export function parseByoLine(line) {
  if (!line || typeof line !== 'string') return null
  const s = line.trim()
  if (!s || s.length > 200) return null

  // 剥掉行首编号 / bullet： "1. 西湖｜景点｜2h" / "- 东京塔 | 景点"
  const body = s.replace(/^(\d+[.)、]?\s*|[•·\-*]\s*)/, '')
  const typeMatch = body.match(new RegExp(`(?:\\||｜|,|，|\\s{2,}).{0,6}?(${TYPE_KEYS})`, 'i'))
  const type = typeMatch ? TYPE_MAP[typeMatch[1].toLowerCase()] || 'attraction' : 'attraction'
  if (typeMatch) {
    // 去掉类型段，剩余首列是名称
    const parts = body.split(typeMatch[1]).map((x) => x.trim())
    // 取类型词前最后一段为名称候选（含前后分隔符）
    const namePart = body.slice(0, typeMatch.index).trim()
    const name = cleanName(namePart)
    if (!name || name.length > 40) return null
    // 时长：类型后紧跟 "2h" / "120min" / "2 小时"；备注取类型后剩余文本。
    // 先剥干净前导分隔符/占位符，再取时长，最后剥时长自身，避免「｜3h｜环湖」残留。
    const after = body.slice(typeMatch.index + typeMatch[0].length).trim()
    let rest = after.replace(/^[,，|｜\s\-–—]+/, '')
    const dur = parseDuration(rest)
    if (dur) rest = rest.replace(/^\d+(\.\d+)?\s*(h|hr|hrs|hour|hours|min|mins|minutes|小时|分钟)\b\s*[,，|｜\s]*/, '')
    const desc = rest.trim()
    return {
      name,
      stop_type: type,
      ...(dur ? { estimated_duration_minutes: dur } : {}),
      ...(desc ? { description: desc.slice(0, 120) } : {}),
    }
  }
  // 无类型分隔：仅「名称, 描述」——按 note import 的逗号启发（名称=逗号前大写部分）
  const comma = body.indexOf(',')
  const name = cleanName(comma > 0 ? body.slice(0, comma) : body)
  if (!name || name.length > 40) return null
  // 句子挡板：无逗号分隔又不像独立站名（无常见收尾词、以说明性短语开头）→ 散文降级
  const END_WORDS =
    /(寺|塔|公园|广场|博物馆|美术馆|湖|山|峰|桥|街|巷|市场|夜市|餐厅|饭店|酒店|民宿|遗址|古镇|景区|岛|湾|溪|河|海|滩|海|城|宫|殿|庙|教堂|台|门|站|机场|码头|大学|学院|中心|大厦|商场|花园|园|村|镇)$/
  const SENTENCE_START =
    /^(我们|我|这|那|在|去|到|有|很|特别|推荐|建议|今天|第二天|然后|不过|可以|一定|千万别|记得|因为|所以|之后)/

  if (comma <= 0) {
    // 纯名称行：必须有收尾词，且不能是句子开头
    if (SENTENCE_START.test(name) || !END_WORDS.test(name)) return null
    return { name, stop_type: 'attraction' }
  }
  return { name, stop_type: 'attraction' }
}

/** 解析时长片段 "2h" / "120min" / "2 小时" → 分钟数；无则 null */
export function parseDuration(frag) {
  const m = String(frag || '').match(/(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|min|mins|minutes|小时|分钟)/i)
  if (!m) return null
  const v = Number(m[1])
  if (!Number.isFinite(v) || v <= 0) return null
  return m[2].toLowerCase().startsWith('h') || m[2] === '小时' ? Math.round(v * 60) : Math.round(v)
}

/**
 * 解析整段 AI 草稿。返回数组（每项 parseByoLine 的非 null 结果）；
 * 若整段散文（无任何可解析行）返回 []（调用方决定降级）。
 * 去重：同名同类型只保留第一个。
 */
export function parseByoDraft(text) {
  if (!text || typeof text !== 'string') return []
  const seen = new Set()
  const out = []
  for (const rawLine of text.split(/\r?\n/)) {
    const parsed = parseByoLine(rawLine)
    if (!parsed) continue
    const key = `${parsed.name}::${parsed.stop_type}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(parsed)
  }
  return out
}

/** 生成可复制的 prompt；带版本号，禁止解释，要求每行格式。 */
export function buildByoPrompt(locale) {
  const zh =
    `你是一位旅行规划师。请为我的行程生成地点列表，严格遵守以下格式（版本 ${BYO_PROMPT_VERSION}）：\n` +
    `每行一个地点，用「｜」分隔四列：地点名｜类型（景点/美食/酒店）｜建议时长（如 2h 或 90min）｜备注（一句话，可空）\n` +
    `不要输出任何解释、序号、Markdown 或额外文字。例：\n` +
    `西湖｜景点｜3h｜环湖骑行，苏堤春晓\n` +
    `楼外楼｜美食｜1.5h｜西湖醋鱼、龙井虾仁\n` +
    `上海和平饭店｜酒店｜-｜外滩景观房`
  const en =
    `You are a trip planner. Generate a stop list for my itinerary in EXACTLY this format (version ${BYO_PROMPT_VERSION}):\n` +
    `one stop per line, four fields separated by "|": Name | Type (attraction/food/hotel) | Duration (e.g. 2h or 90min) | Note (one line, optional)\n` +
    `No explanations, numbering, Markdown, or extra text. Example:\n` +
    `West Lake | attraction | 3h | Lakeside cycling, Su Causeway\n` +
    `Louwailou Restaurant | food | 1.5h | West Lake vinegar fish\n` +
    `The Peace Hotel | hotel | - | Bund view room`
  return locale === 'en-US' ? en : zh
}