/**
 * 相框布局纯函数（frame-marketplace）。
 *
 * 全部为纯函数：无 DOM、无 canvas、无网络 —— 便于 vitest 单测与跨模板复用。
 * renderer.js 负责把这里的几何结果画到 canvas 上。
 */

/** 导出画布固定 3:4（小红书/朋友圈首选比例） */
export const CANVAS_W = 1242;
export const CANVAS_H = 1656;

/**
 * 计算照片槽位矩形（均分网格布局）。
 * @param {number} slotCount 槽位数（1-6）
 * @param {{w: number, h: number}} area 可用区域
 * @param {{gap?: number}} [opts]
 * @returns {Array<{x: number, y: number, w: number, h: number}>}
 */
export function computeSlots(slotCount, area, opts = {}) {
  const gap = opts.gap ?? 24;
  const n = Math.max(1, Math.min(6, slotCount | 0));
  const cols = n <= 2 ? n : n <= 4 ? 2 : 3;
  const rows = Math.ceil(n / cols);
  const cellW = (area.w - gap * (cols - 1)) / cols;
  const cellH = (area.h - gap * (rows - 1)) / rows;
  const slots = [];
  for (let i = 0; i < n; i++) {
    const col = i % cols;
    const row = Math.floor(i / cols);
    // 末行不满：居中
    const inLastRow = row === rows - 1 && n % cols !== 0;
    const lastRowCount = inLastRow ? n - (rows - 1) * cols : cols;
    const offsetX = inLastRow ? ((cols - lastRowCount) * (cellW + gap)) / 2 : 0;
    slots.push({
      x: offsetX + col * (cellW + gap),
      y: row * (cellH + gap),
      w: cellW,
      h: cellH,
    });
  }
  return slots;
}

/**
 * 站点坐标 → 画布手绘轨迹投影（球面等距简化 + keep-in-bounds）。
 * 零地图瓦片：只画风格化路线，所以只需相对几何关系正确。
 * @param {Array<{lat: number, lng: number, name: string}>} stops
 * @param {{x: number, y: number, w: number, h: number}} area
 * @param {{padding?: number}} [opts]
 * @returns {Array<{x: number, y: number, name: string}>} 画布坐标（area 相对）
 */
export function projectRoute(stops, area, opts = {}) {
  const padding = opts.padding ?? 0;
  const pts = stops.filter((s) => s.lat != null && s.lng != null);
  if (pts.length === 0) return [];
  // 单点：居中
  if (pts.length === 1) {
    return [{ x: area.w / 2, y: area.h / 2, name: pts[0].name }];
  }
  const lats = pts.map((s) => s.lat);
  const lngs = pts.map((s) => s.lng);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const spanLat = Math.max(maxLat - minLat, 1e-6);
  const spanLng = Math.max(maxLng - minLng, 1e-6);
  // 经纬度纵向视觉补偿（cos(中位纬度)），避免高纬度路线被纵向压扁
  const midLat = (minLat + maxLat) / 2;
  const latScale = Math.cos((midLat * Math.PI) / 180);
  const innerW = area.w - padding * 2;
  const innerH = area.h - padding * 2;
  const drawW = spanLng;
  const drawH = spanLat * latScale;
  const scale = Math.min(innerW / drawW, innerH / drawH);
  const usedW = drawW * scale;
  const usedH = drawH * scale;
  const offX = (area.w - usedW) / 2;
  const offY = (area.h - usedH) / 2;
  return pts.map((s) => ({
    x: offX + (s.lng - minLng) * scale,
    y: offY + usedH - (s.lat - minLat) * latScale * scale, // 北在上
    name: s.name,
  }));
}

/**
 * 文本按像素宽度换行（中文按字符、英文按词）。
 * @param {string} text
 * @param {number} maxWidth
 * @param {number} maxLines 超出省略（末行加 …）
 * @param {(text: string) => number} measureText 逐段测量回调（renderer 注入 ctx.measureText）
 * @returns {string[]}
 */
export function wrapText(text, maxWidth, maxLines, measureText) {
  const out = [];
  let line = "";
  const chars = String(text ?? "");
  for (const ch of chars) {
    const candidate = line + ch;
    if (measureText(candidate) > maxWidth && line) {
      out.push(line);
      line = ch;
      if (out.length === maxLines) {
        // 超行数：末行以 … 截断
        out[out.length - 1] = out[out.length - 1].slice(0, -1) + "…";
        return out;
      }
    } else {
      line = candidate;
    }
  }
  if (line && out.length < maxLines) out.push(line);
  else if (line && out.length === maxLines && out.length) {
    out[out.length - 1] = out[out.length - 1] + "…";
  }
  return out.slice(0, maxLines);
}

/**
 * 元信息行组装（日期/城市/趣事水印）。
 * @param {{date?: string|null, destination?: string, dayNumber?: number, dayNote?: string|null}} data
 * @returns {string[]}
 */
export function metaLines(data) {
  const lines = [];
  if (data.date) lines.push(data.date);
  const place = [data.destination, data.dayNumber ? `第 ${data.dayNumber} 天` : ""]
    .filter(Boolean)
    .join(" · ");
  if (place) lines.push(place);
  if (data.dayNote) lines.push(data.dayNote);
  return lines;
}
