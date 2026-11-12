/**
 * 模板注册表（frame-marketplace）。
 *
 * 模板本体 = 渲染器可执行配置（与后端 frame_templates.layout_config 对齐）。
 * 这里只兜底内置免费模板；付费模板配置以目录 API（/frames/catalog）下发为准，
 * renderer 按 slug 查找：目录优先，注册表兜底（离线/降级时仍可渲染免费模板）。
 */

export const FREE_TEMPLATES = {
  "minimal-day": {
    slug: "minimal-day",
    name: "极简日志",
    tier: "free",
    theme: "minimal",
    layout_config: {
      photo_slots: 3,
      slot_style: "square",
      route_style: "dashed",
      palette: { bg: "#FAFAF7", accent: "#333333", muted: "#8A8A82" },
      font: "sans",
      decor: [],
    },
  },
  "journal-day": {
    slug: "journal-day",
    name: "手账日常",
    tier: "free",
    theme: "journal",
    layout_config: {
      photo_slots: 4,
      slot_style: "polaroid",
      route_style: "dashed",
      palette: { bg: "#FFF9EF", accent: "#6B4F35", muted: "#B49B7C" },
      font: "serif",
      decor: ["tape"],
    },
  },
};

const FONT_STACKS = {
  sans: '-apple-system, "PingFang SC", "Helvetica Neue", sans-serif',
  serif: 'Georgia, "Songti SC", "STSong", serif',
  rounded: '"Yuanti SC", "PingFang SC", "Comic Sans MS", sans-serif',
};

/**
 * 解析模板配置：目录配置优先，注册表兜底，未知 slug 用极简默认。
 * @param {string} slug
 * @param {{slug?: string, layout_config?: object}|null} [catalogTemplate] 目录下发的模板条目
 */
export function resolveTemplate(slug, catalogTemplate) {
  if (catalogTemplate && catalogTemplate.layout_config) {
    return { slug: catalogTemplate.slug || slug, ...catalogTemplate, layout_config: catalogTemplate.layout_config };
  }
  if (FREE_TEMPLATES[slug]) return FREE_TEMPLATES[slug];
  return {
    slug,
    name: "",
    tier: "free",
    theme: "minimal",
    layout_config: {
      photo_slots: 3,
      slot_style: "square",
      route_style: "dashed",
      palette: { bg: "#FAFAF7", accent: "#333333", muted: "#8A8A82" },
      font: "sans",
      decor: [],
    },
  };
}

/** 字体族字符串（renderer 用） */
export function fontStack(key) {
  return FONT_STACKS[key] || FONT_STACKS.sans;
}
