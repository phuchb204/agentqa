import { describe, expect, it } from "vitest";

import { formatCost, formatUsage, verdictLabel } from "./money";

describe("money và verdict formatting", () => {
  it("unknown money khác zero", () => {
    expect(formatCost("unknown", null, null)).toBe("Không có dữ liệu chi phí");
    expect(formatCost("complete", "0", "USD")).toBe("0 USD");
    expect(formatCost("partial", "1.5", "USD")).toBe("1.5 USD (partial)");
  });

  it("usage unknown hiển thị rõ missingness", () => {
    expect(
      formatUsage({ state: "unknown", input_tokens: 0, output_tokens: 0, unknown_calls: 0 }),
    ).toBe("Không có dữ liệu usage");
    expect(
      formatUsage({ state: "partial", input_tokens: 10, output_tokens: 5, unknown_calls: 1 }),
    ).toContain("1 call unknown");
  });

  it("verdict active là chưa có kết luận", () => {
    expect(verdictLabel(null, false)).toBe("Chưa có kết luận");
    expect(verdictLabel("passed", true)).toBe("Đạt");
    expect(verdictLabel("inconclusive", true)).toBe("Chưa đủ căn cứ (inconclusive)");
  });
});
