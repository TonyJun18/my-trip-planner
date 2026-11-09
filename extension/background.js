/**
 * 随行 · 小红书发布助手 —— 后台服务（MV3 service worker）
 *
 * 职责边界（这是"服务器零凭证"的关键）：
 * 1. 用**用户自己的** JWT 轮询服务端的待发布任务（服务端只存标题/正文/图片）；
 * 2. 打开发布页并把任务交给 content 脚本填写；
 * 3. 把结果（filled / published / failed）回写服务端；
 * 4. 代 content 脚本抓图片（background 有 host 权限，不受页面 CORS 限制）。
 *
 * 这里**没有**任何小红书账号凭证：登录态始终是用户浏览器自己的 cookie。
 */

const DEFAULT_API_BASE = 'http://localhost:8090/api/v1';
const POLL_ALARM = 'xhs-agent-poll';

async function getConfig() {
  const cfg = await chrome.storage.local.get({
    apiBase: DEFAULT_API_BASE,
    token: '',
    autoOpen: true,
    agentName: 'chrome-extension',
  });
  cfg.apiBase = (cfg.apiBase || '').replace(/\/+$/, '');
  return cfg;
}

async function api(path, { method = 'GET', body } = {}) {
  const { apiBase, token } = await getConfig();
  if (!token) throw new Error('未配置访问令牌（在扩展弹窗里粘贴一次）');
  const resp = await fetch(`${apiBase}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = '';
    try {
      const data = await resp.json();
      detail = data?.error?.message || JSON.stringify(data);
    } catch {
      detail = await resp.text();
    }
    throw new Error(`${resp.status} ${detail}`);
  }
  return resp.json();
}

async function pollOnce() {
  const { autoOpen } = await getConfig();
  const { items } = await api('/xhs/agent/tasks?state=pending&limit=5');
  if (!items || items.length === 0) return { opened: 0 };
  let opened = 0;
  for (const task of items) {
    if (!autoOpen) break;
    await dispatchTask(task);
    opened += 1;
    break; // 一次只开一条，避免一次弹多个标签页
  }
  return { opened };
}

async function dispatchTask(task) {
  const claim = await api(`/xhs/agent/tasks/${task.task_id}/claim`, {
    method: 'POST',
    body: { agent: (await getConfig()).agentName },
  });
  const selectors = claim.selectors;
  const tab = await chrome.tabs.create({ url: selectors.publish_url, active: true });
  await chrome.storage.session.set({ [`task:${tab.id}`]: { task: claim.task, selectors } });
  // 等页面 ready 后再投递；content 脚本自己也会在 ready 时向后台要任务
  setTimeout(() => {
    chrome.tabs.sendMessage(tab.id, { type: 'XHS_FILL', task: claim.task, selectors }).catch(() => {});
  }, 2500);
  return tab;
}

/** content 脚本在页面就绪时来要任务（比纯 setTimeout 稳） */
async function currentTaskForTab(tabId) {
  const key = `task:${tabId}`;
  const data = await chrome.storage.session.get(key);
  return data[key] || null;
}

async function report(taskId, payload) {
  return api(`/xhs/agent/tasks/${taskId}/result`, { method: 'POST', body: payload });
}

async function fetchImages(urls) {
  const { apiBase, token } = await getConfig();
  const out = [];
  for (const item of urls) {
    const url = item.url.startsWith('http') ? item.url : `${apiBase.replace(/\/api\/v1$/, '')}${item.url}`;
    const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) throw new Error(`取图失败 ${resp.status}: ${url}`);
    const buf = await resp.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
    out.push({
      asset_id: item.asset_id,
      mime: resp.headers.get('content-type') || 'image/png',
      base64: btoa(binary),
    });
  }
  return out;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === 'XHS_GET_TASK') {
        sendResponse({ ok: true, data: await currentTaskForTab(msg.tabId ?? sender.tab?.id) });
      } else if (msg.type === 'XHS_FETCH_IMAGES') {
        sendResponse({ ok: true, data: await fetchImages(msg.urls) });
      } else if (msg.type === 'XHS_REPORT') {
        sendResponse({ ok: true, data: await report(msg.taskId, msg.payload) });
      } else if (msg.type === 'XHS_POLL_NOW') {
        sendResponse({ ok: true, data: await pollOnce() });
      } else {
        sendResponse({ ok: false, error: `unknown message ${msg.type}` });
      }
    } catch (err) {
      sendResponse({ ok: false, error: String(err && err.message ? err.message : err) });
    }
  })();
  return true; // 异步响应
});

chrome.alarms.create(POLL_ALARM, { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === POLL_ALARM) pollOnce().catch(() => {});
});
chrome.runtime.onInstalled.addListener(() => {
  pollOnce().catch(() => {});
});
