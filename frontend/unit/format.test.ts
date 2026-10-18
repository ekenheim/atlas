import { expect, test } from "@playwright/test";

import { activity, datedTitle, due, dueState, evidenceDay, exactTime, groupDigits, period } from "../lib/format";

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

const NOW = new Date("2026-10-18T13:00:00Z");

test("an evidence date is always absolute and always has its year", () => {
  expect(evidenceDay("2026-01-14T03:30:00Z")).toBe("14 Jan 2026");
  expect(evidenceDay("2027-01-03")).toBe("3 Jan 2027");
  expect(evidenceDay("2026-10-18T23:59:59Z")).toBe("18 Oct 2026");
  expect(evidenceDay("not a date")).toBe("not a date");
  expect(evidenceDay(null)).toBe("");
});

test("activity is relative within a week, then a day without the current year", () => {
  expect(activity("2026-10-18T01:00:00Z", NOW)).toBe("today");
  expect(activity("2026-10-17T23:00:00Z", NOW)).toBe("yesterday");
  expect(activity("2026-10-15T10:00:00Z", NOW)).toBe("3 d ago");
  expect(activity("2026-10-11T10:00:00Z", NOW)).toBe("7 d ago");
  expect(activity("2026-10-10T10:00:00Z", NOW)).toBe("10 Oct");
  expect(activity("2025-12-24T10:00:00Z", NOW)).toBe("24 Dec 2025");
  expect(activity("garbage", NOW)).toBe("garbage");
});

test("a due date says when and how far, and flags an overdue one", () => {
  expect(due("2026-11-18", NOW)).toBe("18 Nov · in 31 d");
  expect(due("2026-10-18", NOW)).toBe("18 Oct · today");
  expect(due("2027-01-05", NOW)).toBe("5 Jan 2027 · in 79 d");
  expect(dueState("2026-10-16", NOW)).toEqual({ text: "overdue 2 d", overdue: true });
  expect(dueState("2026-11-18", NOW).overdue).toBe(false);
});

test("exact time is the ISO time to the minute, for the Records only", () => {
  expect(exactTime("2026-10-18T10:44:08.968347Z")).toBe("2026-10-18 10:44");
  expect(exactTime(null)).toBe("");
});

test("a title's ISO day reads as an evidence day", () => {
  expect(datedTitle("Lumentum Holdings Inc. 8-K filed 2026-08-11, EX-99.1")).toBe(
    "Lumentum Holdings Inc. 8-K filed 11 Aug 2026, EX-99.1",
  );
  expect(datedTitle("Q1 2025")).toBe("Q1 2025");
});
