import { expect, test } from "@playwright/test";

import { groupDigits, period } from "../lib/format";

test("digits are grouped without going through a float", () => {
  expect(groupDigits("3014000000")).toBe("3,014,000,000");
  expect(groupDigits("-480700000")).toBe("-480,700,000");
  expect(groupDigits("12345678901234567890.25")).toBe("12,345,678,901,234,567,890.25");
  expect(groupDigits("999")).toBe("999");
  expect(groupDigits("3.29")).toBe("3.29");
  expect(groupDigits("n/a")).toBe("n/a");
});

test("a period reads as a range, an instant as its date", () => {
  expect(period("2025-06-29", "2026-06-27")).toBe("2025-06-29 – 2026-06-27");
  expect(period(null, "2026-06-27")).toBe("at 2026-06-27");
});
