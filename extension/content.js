/**
 * 随行 · 小红书发布助手 —— 页面脚本（仅在 creator.xiaohongshu.com 注入）
 *
 * 设计原则：**扩展里不写死任何小红书 CSS**。选择器全部来自服务端
 * `/xhs/agent/selectors` 的 `web` 字段（普通 DOM 版），小红书改版时后端改一处，
 * 扩展下次领任务自动生效，不用重新发布扩展。
 *
 * 行为：填好标题/正文/话题/图片 → 停手 → 由用户自己点「发布」 → 监听结果回写。
 * 绝不替用户点发布（发布动作必须由账号所有人在自己浏览器里完成）。
 */
(() => {
  if (window.__suixingXhsHelper) return;
  window.__suixingXhsHelper = true;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const isVisible = (el) => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));

  function collect(desc) {
    // ⚠️ 必须穿透 shadow root：小红书的图片上传 input 在 shadow DOM 里，
    //    普通 querySelectorAll 找不到（Playwright 会自动穿透，所以这个坑在
    //    rpa 通道里不会暴露，只有浏览器扩展会踩）。
    const all = deepElements();
    let nodes = [];
    if (desc.css) {
      try {
        nodes = all.filter((el) => el.matches && el.matches(desc.css));
      } catch {
        return [];
      }
      if (desc.text) nodes = nodes.filter((el) => (el.textContent || '').includes(desc.text));
      return nodes;
    }
    if (desc.text) {
      return all.filter(
        (el) => el.children.length === 0 && (el.textContent || '').trim() === desc.text,
      );
    }
    return [];
  }

  let _deepCache = { at: 0, nodes: [] };
  function deepElements() {
    // 200ms 内复用同一份遍历结果（轮询时避免反复全树遍历）
    if (Date.now() - _deepCache.at < 200) return _deepCache.nodes;
    const acc = [];
    const walk = (root) => {
      if (!root || !root.querySelectorAll) return;
      for (const el of root.querySelectorAll('*')) {
        acc.push(el);
        if (el.shadowRoot) walk(el.shadowRoot);
      }
    };
    walk(document);
    _deepCache = { at: Date.now(), nodes: acc };
    return acc;
  }

  async function findFirst(descs, { visible = true, timeout = 8000 } = {}) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      for (const desc of descs || []) {
        for (const el of collect(desc)) {
          if (visible && !isVisible(el)) continue;
          return el;
        }
      }
      await sleep(250);
    }
    return null;
  }

  function click(el) {
    el.scrollIntoView({ block: 'center' });
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    el.click();
  }

  function setNativeValue(el, value) {
    const proto = Object.getPrototypeOf(el);
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function base64ToFile(item, index) {
    const binary = atob(item.base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const ext = (item.mime || 'image/png').includes('jpeg') ? 'jpg' : 'png';
    return new File([bytes], `cover-${index + 1}.${ext}`, { type: item.mime || 'image/png' });
  }

  async function closeOverlays(descs) {
    for (let i = 0; i < 2; i += 1) {
      const el = await findFirst(descs, { timeout: 800 });
      if (!el) return;
      try {
        click(el);
      } catch {
        /* ignore */
      }
      await sleep(400);
    }
  }

  async function fill(task, selectors) {
    const web = selectors.web || {};
    if (location.href.includes('/login')) {
      return { state: 'failed', reason: 'login_required', message: '小红书未登录，请先扫码登录' };
    }

    // 0) 引导浮层（上传后会再弹一次，填完再收一遍）
    await closeOverlays(web.overlay_close);

    // 1) 切到「上传图文」
    const tab = await findFirst(web.image_tab, { timeout: 5000 });
    if (tab) {
      click(tab);
      await sleep(1200);
    }

    // 2) 图片：走 background 取回（background 有 host 权限，绕开页面 CORS）
    const images = task.images || [];
    if (images.length) {
      const resp = await chrome.runtime.sendMessage({ type: 'XHS_FETCH_IMAGES', urls: images });
      if (!resp || !resp.ok) throw new Error(resp ? resp.error : '取图失败');
      const input = await findFirst(web.file_input, { visible: false, timeout: 10000 });
      if (!input) throw new Error('找不到图片上传控件');
      const dt = new DataTransfer();
      (resp.data || []).forEach((item, i) => dt.items.add(base64ToFile(item, i)));
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      await sleep(2500);
      await closeOverlays(web.overlay_close);
    }

    // 3) 标题
    const titleInput = await findFirst(web.title, { timeout: 15000 });
    if (!titleInput) throw new Error('找不到标题输入框');
    titleInput.focus();
    setNativeValue(titleInput, task.title || '');

    // 4) 正文 + 话题：一次性写入（分段写入会与编辑器渲染竞态，导致正文错位）
    const editor = await findFirst(web.editor, { timeout: 15000 });
    if (!editor) throw new Error('找不到正文编辑器');
    const topics = (task.topics || []).map((t) => `#${String(t).replace(/^#/, '')}`).join(' ');
    const text = topics ? `${task.body}\n\n${topics}` : task.body;
    editor.focus();
    document.execCommand('insertText', false, text);
    await sleep(900);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await sleep(400);
    await closeOverlays(web.overlay_close);

    return { state: 'filled' };
  }

  let watching = false;
  function watchPublish(task, selectors) {
    if (watching) return;
    watching = true;
    const started = Date.now();
    const timer = setInterval(async () => {
      const url = location.href;
      const done =
        url.includes('note-manager') ||
        url.includes('/publish/success') ||
        (selectors.web?.success_marker || []).some((d) =>
          collect(d).some((el) => isVisible(el)),
        );
      if (done) {
        clearInterval(timer);
        watching = false;
        await chrome.runtime.sendMessage({
          type: 'XHS_REPORT',
          taskId: task.task_id,
          payload: { state: 'published', note_url: url },
        });
        return;
      }
      if (Date.now() - started > 10 * 60 * 1000) {
        clearInterval(timer);
        watching = false;
      }
    }, 2000);
  }

  async function run(task, selectors) {
    try {
      const result = await fill(task, selectors);
      await chrome.runtime.sendMessage({
        type: 'XHS_REPORT',
        taskId: task.task_id,
        payload: result,
      });
      if (result.state === 'filled') watchPublish(task, selectors);
      return result;
    } catch (err) {
      const message = String(err && err.message ? err.message : err);
      await chrome.runtime.sendMessage({
        type: 'XHS_REPORT',
        taskId: task.task_id,
        payload: { state: 'failed', reason: 'fill_failed', message },
      });
      return { state: 'failed', reason: 'fill_failed', message };
    }
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type !== 'XHS_FILL') return undefined;
    run(msg.task, msg.selectors).then((r) => sendResponse({ ok: true, result: r }));
    return true;
  });

  // 页面刷新/直接打开发布页时，向后台要一次任务（比纯定时投递稳）
  (async () => {
    try {
      if (!location.href.includes('/publish')) return;
      const resp = await chrome.runtime.sendMessage({ type: 'XHS_GET_TASK' });
      if (resp && resp.ok && resp.data) {
        await run(resp.data.task, resp.data.selectors);
      }
    } catch {
      /* 后台未就绪时忽略 */
    }
  })();
})();
