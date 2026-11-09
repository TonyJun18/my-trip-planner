/** 扩展弹窗：配置 + 手动触发一次任务轮询 */
const $ = (id) => document.getElementById(id);

function setStatus(text, kind) {
  const el = $('status');
  el.textContent = text;
  el.className = kind || '';
}

async function load() {
  const cfg = await chrome.storage.local.get({
    apiBase: 'http://localhost:8090/api/v1',
    token: '',
    autoOpen: true,
  });
  $('apiBase').value = cfg.apiBase;
  $('token').value = cfg.token;
  $('autoOpen').checked = !!cfg.autoOpen;
}

async function save() {
  const apiBase = $('apiBase').value.trim().replace(/\/+$/, '');
  const token = $('token').value.trim();
  if (!apiBase.startsWith('http')) {
    setStatus('服务地址必须以 http(s):// 开头', 'err');
    return false;
  }
  await chrome.storage.local.set({ apiBase, token, autoOpen: $('autoOpen').checked });
  setStatus('已保存', 'ok');
  return true;
}

$('save').addEventListener('click', save);

$('check').addEventListener('click', async () => {
  if (!(await save())) return;
  setStatus('检查中…');
  try {
    const resp = await chrome.runtime.sendMessage({ type: 'XHS_POLL_NOW' });
    if (!resp || !resp.ok) throw new Error(resp ? resp.error : '后台无响应');
    const opened = resp.data?.opened || 0;
    setStatus(opened ? `已打开发布页（${opened} 条任务）` : '暂无待发布任务', 'ok');
  } catch (err) {
    setStatus(String(err.message || err), 'err');
  }
});

load();
