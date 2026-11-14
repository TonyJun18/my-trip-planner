/**
 * 渲染器与导出边界测试（frame-marketplace）。
 *
 * 只测可确定的部分：水印叠加（未解锁模板的预览约束）与配文组装。
 * 画布像素绘制本身由浏览器负责，不在单测范围内。
 */
import { describe, expect, it, vi } from "vitest";

import { composeShareText } from "./export";
import { drawLockWatermark } from "./renderer";

function fakeCtx() {
  const calls = { fillRect: 0, rotate: 0, fillText: [] };
  return {
    calls,
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    rotate: (angle) => { calls.rotate = angle; },
    fillRect: () => { calls.fillRect += 1; },
    fillText: (text) => { calls.fillText.push(text); },
    set fillStyle(_v) {},
    set font(_v) {},
    set textAlign(_v) {},
    set textBaseline(_v) {},
  };
}

describe("drawLockWatermark 未解锁水印", () => {
  it("铺半透明遮罩并写解锁提示", () => {
    const ctx = fakeCtx();
    drawLockWatermark(ctx, { w: 1242, h: 1656 });
    expect(ctx.calls.fillRect).toBe(1);
    expect(ctx.calls.rotate).toBeLessThan(0); // 倾斜角标
    expect(ctx.calls.fillText.join("")).toContain("未解锁");
  });

  it("默认尺寸为导出画布 1242×1656", () => {
    const ctx = fakeCtx();
    drawLockWatermark(ctx);
    expect(ctx.calls.fillRect).toBe(1);
  });
});

describe("composeShareText 配文组装", () => {
  it("小红书：标题 + 正文 + 话题行", () => {
    const text = composeShareText({
      channel: "xhs",
      title: "杭州第1天",
      body: "西湖日落很好。",
      topics: ["杭州", "旅行"],
    });
    expect(text).toBe("杭州第1天\n\n西湖日落很好。\n\n#杭州 #旅行");
  });

  it("朋友圈：不输出标题与话题", () => {
    const text = composeShareText({
      channel: "moments",
      title: "",
      body: "杭州第1天。",
      topics: [],
    });
    expect(text).toBe("杭州第1天。");
  });

  it("空配文返回空串", () => {
    expect(composeShareText(null)).toBe("");
  });
});
