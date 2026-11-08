#!/usr/bin/env node
/**
 * i18n 静态检查（无依赖，node scripts/check-i18n.mjs）
 *
 * 防的是一类「页面显示原始 key」的静默故障：
 *  1. 同一 locale 文件里重复定义同一个 key —— JS 对象字面量后者整体覆盖前者，
 *     整个区块的文案会悄悄消失（2026-10-30 尾部追加的 `tripDetail` 覆盖掉整个
 *     tripDetail 段落，导致行程详情页所有 `tripDetail.*` 都渲染成 key）。
 *  2. zh / en 两侧 key 不对齐。
 *  3. 代码里 `t('a.b')` 引用了 locale 中不存在的 key（动态拼接 `t('a.' + x)` 跳过）。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const LOCALES = { 'zh-CN': 'src/locales/zh-CN.js', 'en-US': 'src/locales/en-US.js' }

const errors = []

// ── 1. 重复 key（按缩进还原嵌套栈） ─────────────────────────────
function checkDuplicateKeys(name, file) {
  const text = fs.readFileSync(path.join(root, file), 'utf8')
  const stack = [] // { indent, key }
  const seen = new Map() // "父路径" -> Set(key)
  text.split('\n').forEach((line, i) => {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('//')) return
    const indent = line.length - line.trimStart().length
    while (stack.length && stack[stack.length - 1].indent >= indent) stack.pop()
    const m = trimmed.match(/^['"]?([A-Za-z0-9_.-]+)['"]?\s*:(?!=)/)
    if (!m) return
    const parent = stack.map((s) => s.key).join('.')
    const bucket = seen.get(parent) ?? new Set()
    if (bucket.has(m[1])) {
      errors.push(`${name}: 重复 key "${parent ? parent + '.' : ''}${m[1]}"（第 ${i + 1} 行）`)
    }
    bucket.add(m[1])
    seen.set(parent, bucket)
    if (trimmed.includes('{')) stack.push({ indent, key: m[1] })
  })
}

// ── 2. key 集合对齐 ────────────────────────────────────────────
function flatten(obj, prefix = '', out = new Set()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object') flatten(v, key, out)
    else out.add(key)
  }
  return out
}

// ── 3. 代码引用完整性 ──────────────────────────────────────────
function collectUsedKeys(dir, out = new Map()) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'locales' || entry.name === 'node_modules') continue
      collectUsedKeys(p, out)
      continue
    }
    if (!/\.(vue|js|ts)$/.test(entry.name)) continue
    const lines = fs.readFileSync(p, 'utf8').split('\n')
    lines.forEach((line, i) => {
      for (const m of line.matchAll(/(?<![\w.$])t\(\s*['"`]([A-Za-z0-9_.-]+)['"`]\s*(\+)?/g)) {
        const [, key, concat] = m
        if (concat || key.endsWith('.')) continue // 动态拼接，无法静态校验
        if (!out.has(key)) out.set(key, `${path.relative(root, p)}:${i + 1}`)
      }
    })
  }
  return out
}

async function main() {
  const messages = {}
  for (const [name, file] of Object.entries(LOCALES)) {
    checkDuplicateKeys(name, file)
    messages[name] = flatten((await import(path.join(root, file))).default)
  }

  const [zhName, enName] = Object.keys(LOCALES)
  for (const k of messages[zhName]) if (!messages[enName].has(k)) errors.push(`仅 ${zhName} 有: ${k}`)
  for (const k of messages[enName]) if (!messages[zhName].has(k)) errors.push(`仅 ${enName} 有: ${k}`)

  for (const [key, where] of collectUsedKeys(path.join(root, 'src'))) {
    for (const name of Object.keys(LOCALES)) {
      if (!messages[name].has(key)) errors.push(`${where} 引用缺失 key: ${key}（${name}）`)
    }
  }

  if (errors.length) {
    console.error(`i18n 检查失败（${errors.length} 项）：`)
    for (const e of errors) console.error('  ✗ ' + e)
    process.exit(1)
  }
  console.log(`i18n 检查通过：${messages[zhName].size} keys × ${Object.keys(LOCALES).length} 语言，无重复 / 无缺失`)
}

main()
