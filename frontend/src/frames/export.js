/**
 * 成品图导出（frame-marketplace）。
 *
 * 只做两件事：PNG 下载 + 配文复制到剪贴板。无任何上传、无任何社媒 API。
 */
/** 导出画布为 PNG 并触发下载 */
export function downloadCanvas(canvas, filename = "frame-card.png") {
  canvas.toBlob((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, "image/png");
}

/** 配文复制到剪贴板（富文本降级纯文本） */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // 降级：隐藏 textarea + execCommand
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

/** 组装「配文 + 话题」纯文本（小红书：正文 + 话题标签行） */
export function composeShareText(copy) {
  if (!copy) return "";
  const body = copy.body || "";
  const topics = (copy.topics || []).map((t) => `#${t}`).join(" ");
  const title = copy.channel === "xhs" && copy.title ? `${copy.title}\n\n` : "";
  return `${title}${body}${topics ? `\n\n${topics}` : ""}`;
}
