/**
 * 相框渲染器（frame-marketplace）。
 *
 * 消费后端数据投影（/trips/{id}/frames/{day_id}/data），把照片 + 手绘轨迹 +
 * 元信息水印绘制到 canvas。照片仅在内存（ImageBitmap），绝不上传。
 *
 * 布局/投影/换行等纯几何在 layout.js（vitest 覆盖），本模块只负责画。
 */
import { CANVAS_H, CANVAS_W, computeSlots, metaLines, projectRoute, wrapText } from "./layout";
import { fontStack, resolveTemplate } from "./templates";

/** 照片 cover 裁切绘制 */
function drawCover(ctx, bitmap, x, y, w, h) {
  const ratio = Math.max(w / bitmap.width, h / bitmap.height);
  const dw = bitmap.width * ratio;
  const dh = bitmap.height * ratio;
  ctx.drawImage(bitmap, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
}

/** 圆角矩形路径 */
function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** 槽位风格差异：square 直角 / rounded 圆角 / polaroid 白边拍立得 / film 胶片边 */
function drawSlot(ctx, style, palette, bitmap, rect) {
  const { x, y, w, h } = rect;
  ctx.save();
  if (style === "polaroid") {
    const pad = Math.round(Math.min(w, h) * 0.04);
    ctx.fillStyle = "#FFFFFF";
    ctx.shadowColor = "rgba(0,0,0,0.15)";
    ctx.shadowBlur = 8;
    ctx.fillRect(x, y, w, h + pad * 3);
    ctx.shadowBlur = 0;
    drawCover(ctx, bitmap, x + pad, y + pad, w - pad * 2, h - pad * 2);
  } else if (style === "film") {
    ctx.fillStyle = "#111111";
    ctx.fillRect(x, y, w, h);
    const hole = Math.max(3, Math.round(h * 0.02));
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    for (let hx = x + hole; hx < x + w - hole; hx += hole * 4) {
      ctx.fillRect(hx, y + hole / 2, hole * 2, hole);
      ctx.fillRect(hx, y + h - hole * 1.5, hole * 2, hole);
    }
    drawCover(ctx, bitmap, x, y + hole * 2.5, w, h - hole * 5);
  } else {
    if (style === "rounded") {
      roundRectPath(ctx, x, y, w, h, Math.min(w, h) * 0.08);
      ctx.clip();
    }
    ctx.fillStyle = palette.muted;
    ctx.fillRect(x, y, w, h);
    drawCover(ctx, bitmap, x, y, w, h);
  }
  ctx.restore();
}

/** 风格化轨迹：虚线 + 编号节点 + 地名标签（零地图瓦片） */
function drawRoute(ctx, routeStyle, palette, points, area) {
  if (!points || points.length === 0) return;
  ctx.save();
  const stroke = routeStyle === "dots" ? [2, 10] : [12, 10];
  ctx.strokeStyle = palette.accent;
  ctx.lineWidth = 3;
  ctx.setLineDash(stroke);
  if (points.length > 1) {
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
      // 手绘感：二次贝塞尔缓动
      const prev = points[i - 1];
      const cx = (prev.x + points[i].x) / 2;
      const cy = (prev.y + points[i].y) / 2 + 8;
      ctx.quadraticCurveTo(cx, cy, points[i].x, points[i].y);
    }
    ctx.stroke();
  }
  ctx.setLineDash([]);
  points.forEach((p, i) => {
    const r = 14;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fillStyle = palette.accent;
    ctx.fill();
    ctx.fillStyle = palette.bg;
    ctx.font = "bold 14px " + fontStack("sans");
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(i + 1), p.x, p.y + 1);
    if (p.name) {
      ctx.font = "16px " + fontStack("sans");
      ctx.textAlign = "left";
      ctx.fillStyle = palette.accent;
      ctx.fillText(p.name, p.x + r + 6, p.y);
    }
  });
  void area;
  ctx.restore();
}

/** 未购买模板的预览水印（全图半透明 + 角标） */
export function drawLockWatermark(ctx, { w = CANVAS_W, h = CANVAS_H } = {}) {
  ctx.save();
  ctx.fillStyle = "rgba(0, 0, 0, 0.35)";
  ctx.fillRect(0, 0, w, h);
  ctx.translate(w / 2, h / 2);
  ctx.rotate(-Math.PI / 8);
  ctx.font = "bold 96px " + fontStack("sans");
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
  ctx.fillText("未解锁 · 输入兑换码", 0, 0);
  ctx.restore();
}

/**
 * 渲染整程总结图（Phase 2）。
 * 布局：封面头图 + 按日小区块 + 全程轨迹串联 + 统计水印。
 * @param {HTMLCanvasElement} canvas
 * @param {{slug: string, layout_config?: object, locked?: boolean}} template
 * @param {{summary: object, photos: (ImageBitmap|null)[]}} data
 *   summary: /frames/summary/data 投影 {destination, start_date, end_date, stats, days}
 */
export function renderSummaryCard(canvas, template, data) {
  const cfg = resolveTemplate(template.slug, data.catalogTemplate || template).layout_config;
  const palette = cfg.palette;
  const ctx = canvas.getContext("2d");
  canvas.width = CANVAS_W;
  canvas.height = CANVAS_H;

  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  const margin = 72;
  const summary = data.summary || {};
  const days = summary.days || [];

  // 标题区
  ctx.fillStyle = palette.accent;
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.font = "bold 56px " + fontStack(cfg.font);
  ctx.fillText(summary.destination || "", margin, margin + 56);
  ctx.font = "28px " + fontStack(cfg.font);
  ctx.fillStyle = palette.muted;
  const range = [summary.start_date, summary.end_date].filter(Boolean).join(" – ");
  if (range) ctx.fillText(range, margin, margin + 100);

  // 统计水印
  const stats = summary.stats || {};
  ctx.font = "600 30px " + fontStack(cfg.font);
  ctx.fillStyle = palette.accent;
  ctx.fillText(
    `${stats.days_with_checkins || 0} 天 · ${stats.checked_stops || 0} 站`,
    CANVAS_W - margin - ctx.measureText(`${stats.days_with_checkins || 0} 天 · ${stats.checked_stops || 0} 站`).width,
    margin + 56,
  );

  // 封面头图（第一张照片）
  const coverY = margin + 140;
  const coverH = 420;
  const cover = (data.photos || [])[0];
  if (cover) {
    drawCover(ctx, cover, margin, coverY, CANVAS_W - margin * 2, coverH);
  } else {
    ctx.fillStyle = palette.muted + "33";
    ctx.fillRect(margin, coverY, CANVAS_W - margin * 2, coverH);
    ctx.fillStyle = palette.muted;
    ctx.font = "30px " + fontStack(cfg.font);
    ctx.textAlign = "center";
    ctx.fillText("＋ 选择封面照片", CANVAS_W / 2, coverY + coverH / 2);
    ctx.textAlign = "left";
  }

  // 按日小区块（每行 3 天，最多 2 行）
  const gridY = coverY + coverH + 40;
  const gridH = 360;
  const shownDays = days.slice(0, 6);
  const daySlots = computeSlots(Math.max(shownDays.length, 1), {
    w: CANVAS_W - margin * 2,
    h: gridH,
  }, { gap: 20 });
  const restPhotos = (data.photos || []).slice(1);
  shownDays.forEach((day, i) => {
    const rect = daySlots[i];
    const x = margin + rect.x;
    const y = gridY + rect.y;
    const photo = restPhotos[i];
    if (photo) {
      drawSlot(ctx, cfg.slot_style, palette, photo, { x, y, w: rect.w, h: rect.h });
    } else {
      ctx.fillStyle = palette.muted + "22";
      ctx.fillRect(x, y, rect.w, rect.h);
    }
    // 日标签
    ctx.fillStyle = palette.accent;
    ctx.font = "bold 22px " + fontStack(cfg.font);
    const labelW = ctx.measureText(`D${day.day_number}`).width + 20;
    ctx.fillRect(x, y, labelW, 34);
    ctx.fillStyle = palette.bg;
    ctx.fillText(`D${day.day_number}`, x + 10, y + 25);
  });

  // 全程轨迹串联（所有日的 checked 站点按序）
  const allStops = days.flatMap((d) => d.stops || []);
  const routeArea = { x: margin, y: gridY + gridH + 30, w: CANVAS_W - margin * 2, h: 300 };
  drawRoute(ctx, cfg.route_style, palette, projectRoute(allStops, routeArea, { padding: 30 }), routeArea);

  // 底部说明
  ctx.fillStyle = palette.muted;
  ctx.font = "22px " + fontStack(cfg.font);
  ctx.fillText("照片仅在本地浏览器处理，未上传服务器", margin, CANVAS_H - margin + 10);

  if (data.locked) drawLockWatermark(ctx);
  return canvas;
}

/**
 * 渲染单日打卡卡。
 * @param {HTMLCanvasElement} canvas
 * @param {{slug: string, layout_config?: object, locked?: boolean}} template 模板（目录条目或注册表项）
 * @param {{day: object, photos: (ImageBitmap|null)[], route: Array, catalogTemplate?: object}} data
 *   day: 投影数据 {day_number, date, destination, day_note, stops}
 *   photos: 与槽位对应的位图数组（缺省槽位画占位）
 */
export function renderDayCard(canvas, template, data) {
  const cfg = resolveTemplate(template.slug, data.catalogTemplate || template).layout_config;
  const palette = cfg.palette;
  const ctx = canvas.getContext("2d");
  canvas.width = CANVAS_W;
  canvas.height = CANVAS_H;

  // 背景
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  const margin = 72;
  const metaH = 260;
  const routeH = 320;
  const photoArea = { w: CANVAS_W - margin * 2, h: CANVAS_H - margin * 2 - metaH - routeH };

  // 照片槽位
  const slots = computeSlots(cfg.photo_slots, photoArea, { gap: 24 });
  const photos = data.photos || [];
  slots.forEach((rect, i) => {
    ctx.save();
    ctx.translate(margin, margin);
    const bitmap = photos[i] || null;
    if (bitmap) {
      drawSlot(ctx, cfg.slot_style, palette, bitmap, rect);
    } else {
      ctx.fillStyle = palette.muted + "33";
      ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
      ctx.fillStyle = palette.muted;
      ctx.font = "28px " + fontStack(cfg.font);
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("＋ 添加照片", rect.x + rect.w / 2, rect.y + rect.h / 2);
    }
    ctx.restore();
  });

  // 轨迹区（照片区下方）
  const routeArea = { x: margin, y: margin + photoArea.h + 40, w: photoArea.w, h: routeH - 60 };
  const points = projectRoute(data.route || [], routeArea, { padding: 40 });
  drawRoute(ctx, cfg.route_style, palette, points, routeArea);

  // 元信息水印（底部）
  const metaY = CANVAS_H - margin - 24;
  const lines = metaLines({
    date: data.day?.date,
    destination: data.day?.destination,
    dayNumber: data.day?.day_number,
    dayNote: data.day?.day_note,
  });
  ctx.save();
  ctx.fillStyle = palette.accent;
  let y = metaY - (lines.length - 1) * 44;
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  for (const line of lines) {
    const wrapped = wrapText(line, CANVAS_W - margin * 2, 2, (s) => ctx.measureText(s).width);
    for (const w of wrapped) {
      ctx.font = (line === lines[lines.length - 1] && data.day?.day_note ? "500 34px " : "600 28px ") + fontStack(cfg.font);
      ctx.fillText(w, margin, y);
      y += 44;
    }
  }
  // 站点列表（编号 + 名称）
  if (points.length) {
    ctx.font = "24px " + fontStack(cfg.font);
    ctx.fillStyle = palette.muted;
    const names = points.map((p, i) => `${i + 1}. ${p.name}`).join("  ");
    const oneLine = wrapText(names, CANVAS_W - margin * 2, 1, (s) => ctx.measureText(s).width);
    if (oneLine[0]) ctx.fillText(oneLine[0], margin, metaY + 26);
  }
  ctx.restore();

  // 装饰元素
  if ((cfg.decor || []).includes("tape")) {
    ctx.save();
    ctx.globalAlpha = 0.6;
    ctx.fillStyle = palette.muted;
    ctx.translate(CANVAS_W / 2, margin / 2);
    ctx.rotate(-0.06);
    ctx.fillRect(-140, -14, 280, 28);
    ctx.restore();
  }

  // 未购买水印最后叠加
  if (data.locked) drawLockWatermark(ctx);

  return canvas;
}
