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
                  <span>{{ m.content || (isPending && i === messages.length - 1 ? '…' : '') }}</span>
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
                <span>{{ streamingText || $t('chat.thinking') }}</span>
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
import { onBeforeUnmount, onMounted, ref, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Delete, Plus, Tools } from '@element-plus/icons-vue'
import {
  createChatSession,
  deleteChatSession,
  listChatSessions,
  listChatMessages,
  sendChatMessage,
  subscribeChatSession,
} from '@/api'

const { t } = useI18n()

const sessions = ref([])
const activeSessionId = ref(null)
const messages = ref([])
const draft = ref('')
const isPending = ref(false)
const streamingText = ref('')
const loadingSessions = ref(false)
const msgBox = ref(null)

let wsClose = null

onMounted(async () => {
  await loadSessions()
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
    scrollToBottom()
  }
}

function handleWsEvent(msg) {
  if (msg.type === 'assistant_delta') {
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
</style>