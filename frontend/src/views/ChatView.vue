<template>
  <div class="chat-page">
    <div class="chat-layout">
      <!-- 会话列表 -->
      <aside class="chat-sidebar">
        <div class="sidebar-head">
          <h2>{{ $t('chat.title') }}</h2>
          <el-button type="primary" size="small" round @click="createNewSession">
            <el-icon><Plus /></el-icon>&nbsp;{{ $t('chat.newSession') }}
          </el-button>
        </div>
        <div v-if="loadingSessions" class="sidebar-empty">{{ $t('common.loading') }}</div>
        <div v-else-if="sessions.length === 0" class="sidebar-empty">
          {{ $t('chat.noSessions') }}
        </div>
        <ul v-else class="session-list">
          <li
            v-for="s in sessions"
            :key="s.id"
            class="session-item"
            :class="{ active: s.id === activeSessionId }"
            @click="openSession(s.id)"
          >
            <div class="session-title">{{ s.title || $t('chat.untitled') }}</div>
            <div class="session-meta">{{ formatTime(s.updated_at) }}</div>
            <el-button
              class="session-del"
              size="small"
              text
              type="danger"
              :icon="Delete"
              @click.stop="removeSession(s.id)"
            />
          </li>
        </ul>
      </aside>

      <!-- 聊天窗口 -->
      <main class="chat-main">
        <div v-if="!activeSessionId" class="chat-empty">
          <el-icon :size="48"><ChatDotRound /></el-icon>
          <p>{{ $t('chat.startHint') }}</p>
          <el-button type="primary" round @click="createNewSession">{{ $t('chat.newSession') }}</el-button>
        </div>

        <template v-else>
          <div ref="msgBox" class="msg-list">
            <div v-for="(m, i) in messages" :key="m.id || i" class="msg-row" :class="m.role">
              <!-- 用户消息 -->
              <template v-if="m.role === 'user'">
                <div class="bubble user">{{ m.content }}</div>
              </template>

              <!-- assistant 消息 -->
              <template v-else-if="m.role === 'assistant'">
                <div class="bubble assistant">
                  <el-icon class="bot-icon"><ChatDotRound /></el-icon>
                  <div class="assistant-body">
                    <!-- 思考过程（可折叠） -->
                    <div v-if="m.reasoning" class="reasoning-block">
                      <div class="reasoning-head" @click="toggleReasoning(m)">
                        <el-icon :size="12"><ArrowDownBold :class="{ rotate: showReasoning[m.id] }" /></el-icon>
                        <span>{{ $t('chat.thinkingTitle') }}</span>
                        <el-icon class="reasoning-toggle"><CaretBottom /></el-icon>
                      </div>
                      <div v-show="showReasoning[m.id]" class="reasoning-body">{{ m.reasoning }}</div>
                    </div>
                    <div v-if="m.content" class="md-body" v-html="renderMarkdown(m.content)"></div>
                    <span v-else-if="isPending && i === messages.length - 1" class="pending-text">{{ $t('chat.thinking') }}</span>
                  </div>
                </div>
              </template>

              <!-- 行程修改预览卡片（edit_trip 两阶段 HITL） -->
              <template v-else-if="m.role === 'tool' && isEditPreview(m)">
                <div class="edit-preview-card">
                  <div class="edit-preview-head">
                    <el-icon><Tools /></el-icon>
                    <span>{{ $t('chat.editPreviewTitle') }}</span>
                  </div>
                  <ul class="edit-preview-actions">
                    <li v-for="(a, ai) in editPreviewActions(m)" :key="ai">
                      <span class="op-badge" :class="a.op">{{ a.op_label }}</span>
                      <span class="target">{{ a.target_name }}</span>
                      <span v-if="a.day_number" class="day">D{{ a.day_number }}</span>
                      <span v-if="a.fields && a.fields.name" class="field">→ {{ a.fields.name }}</span>
                    </li>
                  </ul>
                  <div v-if="editPreviewBudget(m)" class="edit-preview-budget">
                    {{ $t('chat.editPreviewBudget') }}：¥{{ editPreviewBudget(m) }}
                  </div>
                  <div class="edit-preview-btns">
                    <el-button size="small" type="primary" :loading="isPending" @click="confirmEdit(m)">
                      {{ $t('chat.confirmEdit') }}
                    </el-button>
                    <el-button size="small" :loading="isPending" @click="cancelEdit(m)">
                      {{ $t('chat.cancelEdit') }}
                    </el-button>
                  </div>
                </div>
              </template>

              <!-- 工具调用（折叠展示） -->
              <template v-else-if="m.role === 'tool'">
                <div class="tool-call">
                  <el-icon><Tools /></el-icon>
                  <span v-if="m.tool_call?.name">{{ $t('chat.toolCalled') }}：{{ m.tool_call.name }}</span>
                  <span v-else>{{ $t('chat.toolRan') }}</span>
                  <span v-if="m.error" class="tool-error">（{{ $t('chat.toolError') }}）</span>
                </div>
              </template>
            </div>
            <!-- 流式占位 / 思考中 -->
            <div v-if="isPending" class="msg-row assistant">
              <div class="bubble assistant thinking">
                <el-icon class="bot-icon"><ChatDotRound /></el-icon>
                <div class="assistant-body">
                  <div v-if="streamingReasoning" class="reasoning-block streaming">
                    <div class="reasoning-head">
                      <el-icon :size="12"><ArrowDownBold class="rotate" /></el-icon>
                      <span>{{ $t('chat.thinkingTitle') }}</span>
                    </div>
                    <div class="reasoning-body">{{ streamingReasoning }}</div>
                  </div>
                  <span v-if="streamingText">{{ streamingText }}</span>
                  <span v-else>{{ $t('chat.thinking') }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 输入区 -->
          <div class="chat-input">
            <el-input
              v-model="draft"
              type="textarea"
              :rows="2"
              :placeholder="$t('chat.inputPlaceholder')"
              :disabled="isPending"
              @keydown.enter.exact.prevent="send"
            />
            <el-button
              type="primary"
              :loading="isPending"
              :disabled="!draft.trim()"
              @click="send"
            >{{ $t('chat.send') }}</el-button>
          </div>
        </template>
      </main>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDownBold, CaretBottom, ChatDotRound, Delete, Plus, Tools } from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  createChatSession,
  deleteChatSession,
  listChatSessions,
  listChatMessages,
  sendChatMessage,
  subscribeChatSession,
} from '@/api'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const sessions = ref([])
const activeSessionId = ref(null)
const messages = ref([])
const draft = ref('')
const isPending = ref(false)
const streamingText = ref('')
const streamingReasoning = ref('')
const loadingSessions = ref(false)
const msgBox = ref(null)
const showReasoning = reactive({}) // message.id -> true/false（思考过程折叠）

let wsClose = null

onMounted(async () => {
  await loadSessions()
  // 从详情页「问 AI」跳转过来：自动打开 query.session 指向的会话
  const sessionId = route.query.session
  if (sessionId) {
    await openSession(String(sessionId))
    // 清掉 query，避免手动切会话后刷新页面又跳回旧会话
    await router.replace({ query: {} })
  }
})

onBeforeUnmount(() => {
  wsClose?.()
})

async function loadSessions() {
  loadingSessions.value = true
  try {
    const data = await listChatSessions()
    sessions.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  } finally {
    loadingSessions.value = false
  }
}

async function createNewSession() {
  try {
    const s = await createChatSession()
    sessions.value.unshift(s)
    await openSession(s.id)
  } catch {
    /* 拦截器已提示 */
  }
}

async function openSession(id) {
  if (activeSessionId.value === id) return
  wsClose?.()
  activeSessionId.value = id
  messages.value = []
  streamingText.value = ''
  streamingReasoning.value = ''
  try {
    const data = await listChatMessages(id)
    messages.value = data.items || []
    // 订阅实时事件
    wsClose = subscribeChatSession(id, {
      onEvent: handleWsEvent,
      onClose: () => { wsClose = null },
    })
    scrollToBottom()
  } catch {
    /* 拦截器已提示 */
  }
}

async function removeSession(id) {
  try {
    await ElMessageBox.confirm(t('chat.confirmDelete'), t('common.confirm'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteChatSession(id)
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (activeSessionId.value === id) {
      wsClose?.()
      activeSessionId.value = null
      messages.value = []
    }
  } catch {
    /* 拦截器已提示 */
  }
}

async function send() {
  const text = draft.value.trim()
  if (!text || isPending.value || !activeSessionId.value) return
  draft.value = ''
  // 本地乐观追加用户消息（后端持久化后再刷新）
  messages.value.push({ role: 'user', content: text, id: `local-${Date.now()}` })
  scrollToBottom()
  isPending.value = true
  streamingText.value = ''
  streamingReasoning.value = ''
  try {
    await sendChatMessage(activeSessionId.value, text)
    // WS 事件已实时更新；兜底：REST 刷新一次（防 WS 断开丢事件）
    const data = await listChatMessages(activeSessionId.value)
    messages.value = data.items || []
  } catch {
    /* 拦截器已提示；WS/REST 兜底由订阅负责 */
  } finally {
    isPending.value = false
    streamingText.value = ''
    streamingReasoning.value = ''
    scrollToBottom()
  }
}

function handleWsEvent(msg) {
  if (msg.type === 'reasoning_start') {
    // 思考过程：流式占位展示（整段透传，不做增量拼接）
    streamingReasoning.value = msg.reasoning || ''
    scrollToBottom()
  } else if (msg.type === 'assistant_delta') {
    streamingText.value = (streamingText.value || '') + (msg.delta || '')
    scrollToBottom()
  } else if (msg.type === 'tool_start') {
    streamingText.value = `${t('chat.toolCalled')}：${msg.tool_name || ''}…`
    scrollToBottom()
  } else if (msg.type === 'tool_end') {
    // 工具结束：短暂显示后由 REST 刷新覆盖
    streamingText.value = msg.is_error ? t('chat.toolError') : t('chat.toolDone')
    scrollToBottom()
  } else if (msg.type === 'assistant_done') {
    streamingText.value = ''
    streamingReasoning.value = ''
    scrollToBottom()
  }
}

// ── markdown 渲染（assistant 消息正文） ───────────────────────
marked.setOptions({ breaks: true, gfm: true })

function renderMarkdown(text) {
  if (!text) return ''
  try {
    return DOMPurify.sanitize(marked.parse(text))
  } catch {
    // 渲染失败兜底：纯文本（防恶意/畸形 markdown 拖垮气泡）
    return DOMPurify.sanitize(text)
  }
}

function toggleReasoning(m) {
  if (showReasoning[m.id]) showReasoning[m.id] = false
  else showReasoning[m.id] = true
}

// ── 行程修改预览卡片（edit_trip 两阶段 HITL） ──────────────
function parseEditPreview(m) {
  if (!m || m.role !== 'tool' || m.tool_call?.name !== 'edit_trip') return null
  if (!m.content || m.error) return null
  try {
    const data = JSON.parse(m.content)
    return data && data.status === 'preview' ? data : null
  } catch {
    return null
  }
}
function isEditPreview(m) {
  return parseEditPreview(m) !== null
}
function editPreviewActions(m) {
  const data = parseEditPreview(m)
  return (data && data.changed) || []
}
function editPreviewBudget(m) {
  const data = parseEditPreview(m)
  const total = data?.budget_delta?.total_estimated
  return typeof total === 'number' ? total.toFixed(0) : ''
}
async function confirmEdit(m) {
  if (!activeSessionId.value || isPending.value) return
  isPending.value = true
  streamingText.value = ''
  streamingReasoning.value = ''
  try {
    await sendChatMessage(activeSessionId.value, '确认应用上述行程修改')
    const data = await listChatMessages(activeSessionId.value)
    messages.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  } finally {
    isPending.value = false
    streamingText.value = ''
    streamingReasoning.value = ''
    scrollToBottom()
  }
}
async function cancelEdit(m) {
  if (!activeSessionId.value || isPending.value) return
  isPending.value = true
  streamingText.value = ''
  streamingReasoning.value = ''
  try {
    await sendChatMessage(activeSessionId.value, '取消刚才的行程修改建议')
    const data = await listChatMessages(activeSessionId.value)
    messages.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  } finally {
    isPending.value = false
    streamingText.value = ''
    streamingReasoning.value = ''
    scrollToBottom()
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
  })
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const pad = (n) => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (sameDay) return hm
  return `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}
</script>

<style scoped>
.chat-page {
  height: calc(100vh - 60px);
  padding: 16px;
  box-sizing: border-box;
}
.chat-layout {
  display: flex;
  height: 100%;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  overflow: hidden;
  background: var(--el-bg-color);
}
.chat-sidebar {
  width: 260px;
  border-right: 1px solid var(--el-border-color);
  display: flex;
  flex-direction: column;
  background: var(--el-fill-color-light);
}
.sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid var(--el-border-color);
}
.sidebar-head h2 { margin: 0; font-size: 16px; }
.sidebar-empty {
  padding: 24px 12px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.session-list {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}
.session-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  position: relative;
}
.session-item:hover { background: var(--el-fill-color); }
.session-item.active { background: var(--el-color-primary-light-9); }
.session-title {
  flex: 1;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-meta {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
.session-del {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
.session-item:hover .session-del { opacity: 1; }

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--el-text-color-secondary);
}
.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.msg-row {
  display: flex;
  margin-bottom: 12px;
}
.msg-row.user { justify-content: flex-end; }
.msg-row.assistant { justify-content: flex-start; }
.bubble {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble.user {
  background: var(--el-color-primary);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.bubble.assistant {
  background: var(--el-fill-color-light);
  border-bottom-left-radius: 4px;
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.bot-icon { margin-top: 2px; color: var(--el-color-primary); }
.bubble.assistant.thinking { color: var(--el-text-color-secondary); font-style: italic; }

/* ── assistant 消息体（markdown + 思考过程） ─────────────── */
.assistant-body {
  flex: 1;
  min-width: 0;
  white-space: normal;
  word-break: break-word;
}
.pending-text {
  font-style: italic;
  color: var(--el-text-color-secondary);
}
/* 思考过程折叠块 */
.reasoning-block {
  margin-bottom: 8px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.reasoning-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  font-style: normal;
}
.reasoning-head .rotate {
  transform: rotate(90deg);
  transition: transform 0.15s;
}
.reasoning-toggle { margin-left: auto; }
.reasoning-body {
  padding: 6px 12px 10px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow-y: auto;
  border-top: 1px dashed var(--el-border-color);
  font-style: normal;
}
.reasoning-block.streaming .reasoning-body {
  border-top: none;
}
/* markdown 正文渲染（v-html 内容需 :deep 命中） */
.md-body {
  white-space: normal;
  line-height: 1.65;
}
.md-body :deep(p) {
  margin: 0 0 8px;
}
.md-body :deep(p:last-child) {
  margin-bottom: 0;
}
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 12px 0 6px;
  font-size: 1.1em;
  font-weight: 600;
}
.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 4px 0 8px;
  padding-left: 20px;
}
.md-body :deep(li) {
  margin: 2px 0;
}
.md-body :deep(code) {
  background: var(--el-fill-color-darker);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12.5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.md-body :deep(pre) {
  background: var(--el-fill-color-darker);
  border-radius: 8px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 6px 0 10px;
}
.md-body :deep(pre code) {
  background: none;
  padding: 0;
  font-size: 12.5px;
}
.md-body :deep(table) {
  border-collapse: collapse;
  margin: 6px 0 10px;
  max-width: 100%;
  display: block;
  overflow-x: auto;
}
.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid var(--el-border-color);
  padding: 4px 10px;
  font-size: 13px;
}
.md-body :deep(blockquote) {
  margin: 6px 0 10px;
  padding: 4px 12px;
  border-left: 3px solid var(--el-color-primary-light-5);
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
  border-radius: 0 6px 6px 0;
}
.md-body :deep(a) {
  color: var(--el-color-primary);
  text-decoration: underline;
}
.md-body :deep(img) {
  max-width: 100%;
  border-radius: 6px;
}
.md-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--el-border-color);
  margin: 10px 0;
}
.tool-call {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 4px 10px;
  margin-bottom: 12px;
  max-width: 75%;
}
.tool-error { color: var(--el-color-danger); }
.chat-input {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--el-border-color);
  align-items: flex-end;
}
.chat-input .el-textarea { flex: 1; }

/* 行程修改预览卡片（edit_trip 两阶段 HITL） */
.edit-preview-card {
  max-width: 75%;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
  font-size: 13px;
}
.edit-preview-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--el-text-color-primary);
}
.edit-preview-actions {
  list-style: none;
  margin: 0 0 8px;
  padding: 0;
}
.edit-preview-actions li {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  font-size: 13px;
}
.op-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  flex-shrink: 0;
}
.op-badge.remove {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
}
.op-badge.add {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
}
.target { font-weight: 500; }
.day { color: var(--el-text-color-secondary); font-size: 12px; }
.field { color: var(--el-color-primary); }
.edit-preview-budget {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 10px;
}
.edit-preview-btns {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>