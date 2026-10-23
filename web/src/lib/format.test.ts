import { describe, expect, it } from "vitest";

import { formatMetric, money, pct, ratio } from "./format";

describe("money", () => {
  it("compacts large values and keeps small ones whole", () => {
    expect(money(526_412, { compact: true })).toBe("$526.4K");
    expect(money(140.1, { compact: true })).toBe("$140");
    expect(money(-19_134, { compact: true })).toBe("−$19.1K");
  });
  it("renders missing or non-finite values as a dash, never as $NaN", () => {
    expect(money(null)).toBe("—");
    expect(money(Number.NaN)).toBe("—");
    expect(money(Infinity, { compact: true })).toBe("—");
  });
});

describe("pct", () => {
  it("signs deltas only when asked", () => {
    expect(pct(0.047, 1, true)).toBe("+4.7%");
    expect(pct(-0.103, 1, true)).toBe("−10.3%");
    expect(pct(0.0135, 2)).toBe("1.35%");
  });
});

describe("ratio", () => {
  it("shows ROI to one decimal by default (intervals do not support more)", () => {
    expect(ratio(1.14567)).toBe("1.1");
    expect(ratio(1.14567, 2)).toBe("1.15");
  });
});

describe("formatMetric", () => {
  it("follows the metric's declared format", () => {
    expect(formatMetric(3_400_000, "currency")).toBe("$3.4M");
    expect(formatMetric(0.0135, "percent")).toBe("1.4%");
    expect(formatMetric(6.4321, "ratio")).toBe("6.43");
  });
});
