// A company's mechanical bear checks in the owner's words (spec §10.6): the six checks in their
// fixed order, a short value for each row read from its own typed value, why an unknown one is
// unknown, the figures and quotes an open row shows, and what the Records hold. The API's
// `summary` is the open row's sentence; its `basis` (ISO dates, concept names, the rule's text)
// stays in the Records (H3). Pure, so each format is tested.
import type { BearCheck, BearChecks, BearCheckSource } from "./api/client";
import { humanise } from "./chokepoints";
import { evidenceDay, groupDigits, plainDay } from "./format";
import { routes } from "./routes";
import {
  BEAR_LABELS,
  BEAR_STATUS_WORDS,
  type CheckKeyName,
  UNKNOWN_REASON_WORDS,
  type Word,
} from "./status";

/** The one order of the checks; a flag is coloured, never moved (Y7). */
export const BEAR_ORDER: readonly CheckKeyName[] = [
  "dilution",
  "shelf_or_atm",
  "gaap_gross_margin",
  "customer_concentration",
  "going_concern",
  "net_cash",
];

const rank = (check: Pick<BearCheck, "key">) => {
  const at = BEAR_ORDER.indexOf(check.key);
  return at === -1 ? BEAR_ORDER.length : at;
};

/** The checks in the fixed order; a key this page does not know comes last. */
export function orderedChecks<T extends Pick<BearCheck, "key">>(checks: readonly T[]): T[] {
  return [...checks].sort((a, b) => rank(a) - rank(b));
}

const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

/** "1 flag · 4 clear · 1 unknown", zero parts dropped. */
export function bearSummary(answer: Pick<BearChecks, "checks">): string {
  const count = (status: BearCheck["status"]) => answer.checks.filter((each) => each.status === status).length;
  return [
    count("flag") > 0 ? plural(count("flag"), "flag") : null,
    count("clear") > 0 ? `${count("clear")} clear` : null,
    count("unknown") > 0 ? `${count("unknown")} unknown` : null,
  ]
    .filter((part): part is string => part !== null)
    .join(" · ");
}

/** A check's label; a key this page does not know is its slug in words, with a warning. */
export function bearLabel(check: Pick<BearCheck, "key">): string {
  const known = (BEAR_LABELS as Record<string, string | undefined>)[check.key];
  if (known !== undefined) return known;
  console.warn(`Unknown bear check: ${check.key}`);
  return humanise(check.key);
}

/** The word beside a row's value: Flag or Unknown; nothing for a clear check. */
export const bearWord = (check: Pick<BearCheck, "status">): Word | null =>
  check.status in BEAR_STATUS_WORDS ? BEAR_STATUS_WORDS[check.status] : BEAR_STATUS_WORDS.unknown;

/** Why Atlas cannot answer the check, in a few words. */
export function unknownText(check: Pick<BearCheck, "unknown_reason">): string {
  return check.unknown_reason ? UNKNOWN_REASON_WORDS[check.unknown_reason] : "not known";
}

// --- numbers -------------------------------------------------------------------------------

const SYMBOLS: Record<string, string> = { USD: "$", EUR: "€", GBP: "£", JPY: "¥" };

/** One decimal at most, the trailing ".0" dropped. */
const oneDecimal = (value: number) => String(Math.round(value * 10) / 10);

/** An amount scaled to B, M or K with its currency: "$412M", "€1.2B", "412M CHF". */
export function money(amount: number, unit: string): string {
  const size = Math.abs(amount);
  const [scaled, suffix] =
    size >= 1e9 ? [size / 1e9, "B"] : size >= 1e6 ? [size / 1e6, "M"] : size >= 1e3 ? [size / 1e3, "K"] : [size, ""];
  const figure = suffix ? `${oneDecimal(scaled)}${suffix}` : groupDigits(String(Math.round(scaled)));
  const sign = amount < 0 ? "−" : "";
  const symbol = SYMBOLS[unit];
  return symbol ? `${sign}${symbol}${figure}` : `${sign}${figure} ${unit}`;
}

const percent = (value: number) => `${oneDecimal(value)}%`;
const signed = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(Math.round(value))}%`;

// --- a row ---------------------------------------------------------------------------------

/**
 * The row's value, from the check's own value: "+12% in a year", "2 filings · S-3, 424B5 ·
 * latest 4 Mar", "41% · down 6 pts", "38% of revenue", "none in the 10-K", "net cash $412M".
 * An unknown check has none (its row says why); a flag or clear one with no value reads "—".
 */
export function bearValue(check: BearCheck, now: Date = new Date()): string {
  if (check.status === "unknown") return "";
  switch (check.key) {
    case "dilution":
      return check.value ? `${signed(check.value.growth_pct)} in a year` : "—";
    case "shelf_or_atm": {
      const filings = check.value?.filings ?? [];
      if (filings.length === 0) return "—";
      const forms = [...new Set(filings.map((each) => each.form))].join(", ");
      const latest = [...filings].sort((a, b) => b.available_at.localeCompare(a.available_at))[0];
      return `${plural(filings.length, "filing")} · ${forms} · latest ${plainDay(latest?.available_at, now)}`;
    }
    case "gaap_gross_margin": {
      if (!check.value) return "—";
      const change = check.value.change_points;
      const rounded = change === null ? null : Math.round(change);
      const move =
        rounded === null ? "" : rounded === 0 ? " · flat" : ` · ${rounded < 0 ? "down" : "up"} ${Math.abs(rounded)} pts`;
      return `${Math.round(check.value.ttm_margin_pct)}%${move}`;
    }
    case "customer_concentration": {
      const value = check.value;
      if (!value) return "—";
      if (value.current_percent !== null) {
        const biggest = value.matches.find((each) => each.current_percent === value.current_percent);
        const figure = `${oneDecimal(value.current_percent)}%`;
        return biggest?.lower_bound ? `more than ${figure}` : `${figure} of revenue`;
      }
      const threshold = value.no_customer_above.length > 0 ? Math.min(...value.no_customer_above) : null;
      return threshold === null ? "—" : `none above ${oneDecimal(threshold)}%`;
    }
    case "going_concern":
      if (!check.value) return "—";
      return check.status === "flag" ? `in the ${check.value.document.form}` : `none in the ${check.value.document.form}`;
    case "net_cash":
      if (!check.value) return "—";
      return check.value.net_cash < 0
        ? `net debt ${money(-check.value.net_cash, check.value.unit)}`
        : `net cash ${money(check.value.net_cash, check.value.unit)}`;
  }
}

export interface Figure {
  label: string;
  value: string;
  /** A filing the figure opens (`Open the filing`). */
  href?: string;
}

/** The figures an open row shows, with the page's own labels and days. */
export function bearFigures(check: BearCheck): Figure[] {
  switch (check.key) {
    case "dilution":
      return check.value
        ? [
            { label: `Shares, ${evidenceDay(check.value.shares_as_of)}`, value: groupDigits(String(check.value.shares)) },
            {
              label: `A year earlier, ${evidenceDay(check.value.year_earlier_as_of)}`,
              value: groupDigits(String(check.value.shares_year_earlier)),
            },
          ]
        : [];
    case "gaap_gross_margin":
      return check.value
        ? [
            { label: "Last four quarters", value: percent(check.value.ttm_margin_pct) },
            ...(check.value.prior_ttm_margin_pct === null
              ? []
              : [{ label: "The four a year earlier", value: percent(check.value.prior_ttm_margin_pct) }]),
            ...check.value.quarters.map((quarter) => ({
              label: evidenceDay(quarter.period_end),
              value: quarter.margin_pct === null ? "—" : percent(quarter.margin_pct),
            })),
          ]
        : [];
    case "net_cash": {
      const value = check.value;
      if (!value) return [];
      const day = evidenceDay(value.as_of_balance_sheet);
      return [
        { label: `Cash, ${day}`, value: money(value.cash, value.unit) },
        ...(value.short_term_investments === null
          ? []
          : [{ label: "Short-term investments", value: money(value.short_term_investments, value.unit) }]),
        { label: "Debt", value: money(value.debt, value.unit) },
      ];
    }
    case "shelf_or_atm":
      return (check.value?.filings ?? []).map((filing) => ({
        label: `${filing.form} · ${evidenceDay(filing.available_at)}`,
        value: "",
        href: routes.version(filing.source_version_id),
      }));
    default:
      return [];
  }
}

export interface BearQuote {
  quote: string;
  href: string;
  form: string | null;
  availableAt: string | null;
}

type Span = BearCheckSource & {
  source_version_id: string;
  char_start: number;
  char_end: number;
  quote: string;
};

const isSpan = (source: BearCheckSource): source is Span =>
  source.kind === "source_version" &&
  source.source_version_id !== null &&
  source.source_version_id !== undefined &&
  typeof source.char_start === "number" &&
  typeof source.char_end === "number" &&
  typeof source.quote === "string";

/** The sentences a check quotes, each opening its filing at the span (`routes.spanAt`). */
export function bearQuotes(check: Pick<BearCheck, "sources">): BearQuote[] {
  return check.sources.filter(isSpan).map((source) => ({
    quote: source.quote,
    href: routes.spanAt(source.source_version_id, source.char_start, source.char_end, source.parser_version ?? ""),
    form: source.form_type ?? null,
    availableAt: source.available_at ?? null,
  }));
}

/** A filing a check read with no sentence to quote (the report a clear check read whole):
 * `Open the filing`. Observations render nothing: the figures already show them. */
export function bearFilings(check: BearCheck): { href: string; form: string }[] {
  if (bearQuotes(check).length > 0) return [];
  const fromSources = check.sources
    .filter((source) => source.kind === "source_version" && source.source_version_id && !isSpan(source))
    .map((source) => ({ href: routes.version(source.source_version_id ?? ""), form: source.form_type ?? "filing" }));
  if (fromSources.length > 0) return fromSources;
  if ((check.key === "going_concern" || check.key === "customer_concentration") && check.value) {
    return [{ href: routes.version(check.value.document.source_version_id), form: check.value.document.form }];
  }
  return [];
}

/** The concept names a check rests on (the Records only). */
export function bearConcepts(check: BearCheck): string[] {
  const names = check.sources.map((source) => source.concept).filter((each): each is string => Boolean(each));
  if (check.key === "net_cash" && check.value) names.push(...check.value.debt_concepts);
  return [...new Set(names)];
}
