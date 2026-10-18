// Display helpers for values exactly as the API sent them (decimal strings, never floats).

/** A decimal string with its integer digits grouped in threes: "3014000000.5" → "3,014,000,000.5". */
export function groupDigits(value: string): string {
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(value);
  if (!match) return value;
  const [, sign = "", whole = "", fraction = ""] = match;
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}`;
}

/** A period as "start – end", or "at end" for an instant (e.g. debt at a balance date). */
export function period(start: string | null | undefined, end: string): string {
  return start ? `${start} – ${end}` : `at ${end}`;
}

// --- dates (Y6): evidence is dated absolutely, activity relatively, what is due with both ---

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

type Ymd = { year: number; month: number; day: number };

/** The UTC calendar date of an ISO date or time, or null when it is neither. */
function ymd(iso: string | null | undefined): Ymd | null {
  const match = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
}

function dayNumber(date: Ymd): number {
  return Math.floor(Date.UTC(date.year, date.month - 1, date.day) / 86_400_000);
}

function today(now: Date): Ymd {
  return { year: now.getUTCFullYear(), month: now.getUTCMonth() + 1, day: now.getUTCDate() };
}

function dayMonth(date: Ymd): string {
  return `${date.day} ${MONTHS[date.month - 1] ?? date.month}`;
}

/** An evidence date, always with its year: "14 Jan 2026". Anything else comes back as given. */
export function evidenceDay(iso: string | null | undefined): string {
  const date = ymd(iso);
  return date ? `${dayMonth(date)} ${date.year}` : (iso ?? "");
}

/** A date without its year when it falls in the current one, else with it. */
function shortDay(date: Ymd, now: Date): string {
  return date.year === now.getUTCFullYear() ? dayMonth(date) : `${dayMonth(date)} ${date.year}`;
}

/** A day for a line that says when something was published or reported: "18 Oct", with the
 * year when it is not the current one. */
export function plainDay(iso: string | null | undefined, now: Date = new Date()): string {
  const date = ymd(iso);
  return date ? shortDay(date, now) : (iso ?? "");
}

/** When something happened: "today", "yesterday", "3 d ago" within seven days, else the day
 * (the year only when it is not the current one). */
export function activity(iso: string | null | undefined, now: Date = new Date()): string {
  const date = ymd(iso);
  if (!date) return iso ?? "";
  const ago = dayNumber(today(now)) - dayNumber(date);
  if (ago === 0) return "today";
  if (ago === 1) return "yesterday";
  if (ago > 1 && ago <= 7) return `${ago} d ago`;
  return shortDay(date, now);
}

export type Due = { text: string; overdue: boolean };

/** A due date with how far off it is: "18 Nov · in 31 d", "18 Nov · today", or "overdue 2 d". */
export function dueState(iso: string | null | undefined, now: Date = new Date()): Due {
  const date = ymd(iso);
  if (!date) return { text: iso ?? "", overdue: false };
  const away = dayNumber(date) - dayNumber(today(now));
  if (away < 0) return { text: `overdue ${-away} d`, overdue: true };
  const when = shortDay(date, now);
  return { text: away === 0 ? `${when} · today` : `${when} · in ${away} d`, overdue: false };
}

export function due(iso: string | null | undefined, now: Date = new Date()): string {
  return dueState(iso, now).text;
}

/** A time as the Records show it: the ISO time to the minute. */
export function exactTime(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "";
}

/** The calendar date as an ISO day, "2026-11-18" (for comparing and grouping). */
export function isoDay(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "";
}

/** A title as the surface shows it: an ISO day it carries ("8-K filed 2026-08-11") reads as an
 * evidence day ("8-K filed 11 Aug 2026"). The Records keep the title as stored. */
export function datedTitle(title: string): string {
  return title.replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (day) => evidenceDay(day));
}
