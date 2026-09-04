import { describe, expect, it } from "vitest";
import { formatPercent, humanizeDuration, requirementStatusColor } from "./format";

describe("requirementStatusColor", () => {
  it("maps verified to green", () => {
    expect(requirementStatusColor("verified")).toBe("var(--success)");
  });

  it("maps failed to red", () => {
    expect(requirementStatusColor("failed")).toBe("var(--danger)");
  });

  it("maps pending and unverified to amber", () => {
    expect(requirementStatusColor("pending")).toBe("var(--warning)");
    expect(requirementStatusColor("unverified")).toBe("var(--warning)");
  });

  it("maps waived to gray", () => {
    expect(requirementStatusColor("waived")).toBe("#6b7280");
  });
});

describe("humanizeDuration", () => {
  it("returns a dash for missing or invalid values", () => {
    expect(humanizeDuration(null)).toBe("—");
    expect(humanizeDuration(undefined)).toBe("—");
    expect(humanizeDuration(-5)).toBe("—");
    expect(humanizeDuration(Number.NaN)).toBe("—");
  });

  it("formats seconds", () => {
    expect(humanizeDuration(0)).toBe("0s");
    expect(humanizeDuration(45)).toBe("45s");
  });

  it("formats minutes with remaining seconds", () => {
    expect(humanizeDuration(60)).toBe("1m");
    expect(humanizeDuration(200)).toBe("3m 20s");
  });

  it("formats hours with remaining minutes", () => {
    expect(humanizeDuration(3600)).toBe("1h");
    expect(humanizeDuration(2 * 3600 + 15 * 60)).toBe("2h 15m");
  });

  it("formats days with remaining hours", () => {
    expect(humanizeDuration(24 * 3600)).toBe("1d");
    expect(humanizeDuration(28 * 3600)).toBe("1d 4h");
  });
});

describe("formatPercent", () => {
  it("formats a 0..1 ratio as a percentage", () => {
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(1)).toBe("100%");
    expect(formatPercent(0.333)).toBe("33%");
  });

  it("returns a dash for missing values", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(undefined)).toBe("—");
  });
});
