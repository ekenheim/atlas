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
