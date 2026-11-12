/**
 * 相框布局纯函数测试（frame-marketplace，任务 5.2）。
 *
 * 覆盖：槽位均分网格（含末行居中）、坐标投影（keep-in-bounds / 北在上 / 单点居中）、
 * 文本换行（中文字符逐个断行 + 超行省略）、元信息行组装。
 */
import { describe, expect, it } from "vitest";

import { computeSlots, metaLines, projectRoute, wrapText } from "./layout";

describe("computeSlots 槽位布局", () => {
  const area = { w: 1200, h: 800 };

  it("3 槽 = 2 列布局，槽尺寸一致", () => {
    const slots = computeSlots(3, area);
    expect(slots).toHaveLength(3);
    expect(slots[0].w).toBe(slots[1].w);
    expect(slots[0].h).toBe(slots[1].h);
    // 第三块在第二行（首列）
    expect(slots[2].y).toBeGreaterThan(slots[0].y);
  });

  it("5 槽 = 3 列，末行 2 块居中", () => {
    const slots = computeSlots(5, area);
    expect(slots).toHaveLength(5);
    // 末行两块总宽 < 3 块宽，且 x 起点右移（居中）
    const lastRow = slots.slice(3);
    expect(lastRow[0].x).toBeGreaterThan(slots[0].x);
  });

  it("槽位不越出区域", () => {
    for (const n of [1, 2, 3, 4, 5, 6]) {
      for (const s of computeSlots(n, area)) {
        expect(s.x).toBeGreaterThanOrEqual(0);
        expect(s.y).toBeGreaterThanOrEqual(0);
        expect(s.x + s.w).toBeLessThanOrEqual(area.w + 1e-9);
        expect(s.y + s.h).toBeLessThanOrEqual(area.h + 1e-9);
      }
    }
  });

  it("槽位数被夹在 1-6", () => {
    expect(computeSlots(0, area)).toHaveLength(1);
    expect(computeSlots(9, area)).toHaveLength(6);
  });
});

describe("projectRoute 轨迹投影", () => {
  const area = { x: 0, y: 0, w: 400, h: 300 };

  it("空站点 → 空数组", () => {
    expect(projectRoute([], area)).toEqual([]);
  });

  it("单点居中", () => {
    const [p] = projectRoute([{ lat: 30, lng: 120, name: "西湖" }], area);
    expect(p.x).toBeCloseTo(200);
    expect(p.y).toBeCloseTo(150);
  });

  it("北在上：纬度更高 → y 更小", () => {
    const pts = projectRoute(
      [
        { lat: 30, lng: 120, name: "A" },
        { lat: 31, lng: 120, name: "B" },
      ],
      area,
    );
    expect(pts[1].y).toBeLessThan(pts[0].y);
  });

  it("东在右：经度更大 → x 更大", () => {
    const pts = projectRoute(
      [
        { lat: 30, lng: 120, name: "A" },
        { lat: 30, lng: 121, name: "B" },
      ],
      area,
    );
    expect(pts[1].x).toBeGreaterThan(pts[0].x);
  });

  it("keep-in-bounds：全部落在区域内", () => {
    const pts = projectRoute(
      [
        { lat: 30.0, lng: 120.0, name: "A" },
        { lat: 30.5, lng: 120.4, name: "B" },
        { lat: 30.2, lng: 120.2, name: "C" },
      ],
      area,
      { padding: 10 },
    );
    for (const p of pts) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(area.w);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(area.h);
    }
  });

  it("忽略无坐标站点", () => {
    const pts = projectRoute([{ lat: 30, lng: 120, name: "A" }, { name: "无坐标" }], area);
    expect(pts).toHaveLength(1);
  });
});

describe("wrapText 文本换行", () => {
  const measure = (s) => s.length * 10; // 每字符 10px

  it("按宽度断行", () => {
    const lines = wrapText("西湖雷峰塔断桥", 30, 5, measure);
    expect(lines).toEqual(["西湖雷", "峰塔断", "桥"]);
  });

  it("超行数截断加省略号", () => {
    const lines = wrapText("西湖雷峰塔断桥苏堤", 30, 2, measure);
    expect(lines).toHaveLength(2);
    expect(lines[1].endsWith("…")).toBe(true);
  });

  it("短文本单行", () => {
    expect(wrapText("短", 100, 3, measure)).toEqual(["短"]);
  });
});

describe("metaLines 元信息行", () => {
  it("齐全字段", () => {
    expect(metaLines({ date: "2026-11-12", destination: "杭州", dayNumber: 2, dayNote: "西湖暴走" })).toEqual([
      "2026-11-12",
      "杭州 · 第 2 天",
      "西湖暴走",
    ]);
  });

  it("缺字段不产空行", () => {
    expect(metaLines({})).toEqual([]);
  });
});
