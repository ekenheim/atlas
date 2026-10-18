// The Watch's memo, parsed into blocks the page renders as React elements (spec §10.3.5). Never
// HTML: raw HTML stays literal text, code is dropped or read as text, and only two link forms
// survive (http(s), which leaves Atlas, and `atlas:chokepoint/<uuid>`, which opens the board).
// Every text node then passes the owner-words pass, so a code, a step letter or an id the memo
// still carries does not reach the page. The parser is linear: a line at a time, and an inline
// scan whose closers are looked up in precomputed position lists, never a backtracking search.
import { evidenceDay } from "./format";
import { STEP_LABELS, type StepName } from "./argument";
import { OWNER_TOKENS } from "./status";

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "em"; children: Inline[] }
  | { kind: "strong"; children: Inline[] }
  | { kind: "link"; href: string; host: string; children: Inline[] }
  | { kind: "chokepoint"; id: string; children: Inline[] };

export type Block =
  | { kind: "heading"; level: 3 | 4; children: Inline[] }
  | { kind: "paragraph"; children: Inline[] }
  | { kind: "list"; ordered: boolean; items: Inline[][] };

// --- the owner-words pass ------------------------------------------------------------------

const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const BRACKETED_UUID = new RegExp(`[([]\\s*${UUID}\\s*[)\\]]`, "g");
const BARE_UUID = new RegExp(UUID, "g");
const ISO_DAY = /\b\d{4}-\d{2}-\d{2}\b/g;

const LETTER_STEPS: Record<string, StepName> = {
  a: "constraint",
  b: "demand_vs_supply",
  c: "relief",
  d: "control",
  e: "capture",
  f: "invalidation",
};

const TOKENS = new RegExp(
  `\\b(?:${Object.keys(OWNER_TOKENS).join("|")})\\b|\\b[Ss]tep(?: \\(([a-f])\\)| ([a-f])\\b|_([a-f])\\b)`,
  "g",
);

const capitalise = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

/**
 * A memo's text in the owner's words: each code (`thesis_ready`, `kill_criteria`, ...) by its
 * word, a step by letter ("step d", "step_d", "step (d)") by its name, an ISO day as a day, and
 * every UUID removed with the gap it leaves. `start` says the text opens a sentence, so a
 * replaced word there is capitalised.
 */
export function ownerWords(text: string, start = true): string {
  let out = text.replace(TOKENS, (match, paren?: string, spaced?: string, snake?: string, offset = 0) => {
    const letter = paren ?? spaced ?? snake;
    if (letter !== undefined) return STEP_LABELS[LETTER_STEPS[letter] ?? "constraint"];
    const word = OWNER_TOKENS[match] ?? match;
    const before = (text as string).slice(0, offset as number);
    const atStart = (start && before.trim() === "") || /[.!?]\s+$/.test(before.slice(-4));
    return atStart ? capitalise(word) : word;
  });
  if (BARE_UUID.test(out)) {
    BARE_UUID.lastIndex = 0;
    out = out
      .replace(BRACKETED_UUID, "")
      .replace(BARE_UUID, "")
      .replace(/ {2,}/g, " ")
      .replace(/ +([,.;:!?)])/g, "$1")
      .replace(/\( *\)/g, "");
  }
  return out.replace(ISO_DAY, (day) => evidenceDay(day));
}

// --- inlines -------------------------------------------------------------------------------

const HTTP = /^https?:\/\/[^\s]+$/i;
const CHOKEPOINT_LINK = new RegExp(`^atlas:chokepoint/(${UUID})$`);

/** Sorted positions of each character the inline scan looks for, built once per text. */
interface Index {
  text: string;
  open: number[];
  close: number[];
  paren: number[];
  tick: number[];
  /** Closers by delimiter: `**`, `__`, `*`, `_`. */
  closers: Record<string, number[]>;
}

const isSpace = (ch: string | undefined) => ch === undefined || /\s/.test(ch);
const isWord = (ch: string | undefined) => ch !== undefined && /[\p{L}\p{N}]/u.test(ch);

function buildIndex(text: string): Index {
  const index: Index = {
    text,
    open: [],
    close: [],
    paren: [],
    tick: [],
    closers: { "**": [], __: [], "*": [], _: [] },
  };
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === "[") index.open.push(i);
    else if (ch === "]") index.close.push(i);
    else if (ch === ")") index.paren.push(i);
    else if (ch === "`") index.tick.push(i);
    else if (ch === "*" || ch === "_") {
      const double = text[i + 1] === ch;
      const delimiter = double ? ch + ch : ch;
      const after = text[i + delimiter.length];
      const closes = !isSpace(text[i - 1]) && (ch === "*" || !isWord(after));
      if (closes) index.closers[delimiter]?.push(i);
      if (double) i += 1;
    }
  }
  return index;
}

/** The first position in `sorted` that is ≥ `from` and < `end`, or -1 (a binary search). */
function firstFrom(sorted: readonly number[], from: number, end: number): number {
  let low = 0;
  let high = sorted.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if ((sorted[mid] ?? 0) < from) low = mid + 1;
    else high = mid;
  }
  const found = sorted[low];
  return found !== undefined && found < end ? found : -1;
}

const MAX_DEPTH = 4;

function pushText(out: Inline[], text: string) {
  if (text === "") return;
  const last = out.at(-1);
  if (last?.kind === "text") last.text += text;
  else out.push({ kind: "text", text });
}

/** The inlines of `index.text` from `start` to `end`. Links are not looked for inside a link. */
function inlines(index: Index, start: number, end: number, depth: number, inLink: boolean): Inline[] {
  const text = index.text;
  const out: Inline[] = [];
  let plain = "";
  const flush = () => {
    pushText(out, plain);
    plain = "";
  };
  let i = start;
  while (i < end) {
    const ch = text[i] ?? "";
    if (ch === "\\" && i + 1 < end && /[\\`*_[\]()#+\-.!<>]/.test(text[i + 1] ?? "")) {
      plain += text[i + 1];
      i += 2;
      continue;
    }
    if (ch === "`") {
      // Inline code: its text is read as text (it passes the owner-words pass later).
      const closing = firstFrom(index.tick, i + 1, end);
      if (closing > i + 1) {
        plain += text.slice(i + 1, closing);
        i = closing + 1;
        continue;
      }
      plain += ch;
      i += 1;
      continue;
    }
    if (ch === "[" && !inLink && depth < MAX_DEPTH) {
      const close = firstFrom(index.close, i + 1, end);
      const nested = firstFrom(index.open, i + 1, end);
      if (close !== -1 && (nested === -1 || nested > close) && text[close + 1] === "(") {
        const paren = firstFrom(index.paren, close + 2, end);
        if (paren !== -1) {
          const target = text.slice(close + 2, paren).trim().split(/\s+/)[0] ?? "";
          const children = inlines(index, i + 1, close, depth + 1, true);
          flush();
          const chokepoint = CHOKEPOINT_LINK.exec(target);
          if (HTTP.test(target)) {
            out.push({ kind: "link", href: target, host: hostOf(target), children });
          } else if (chokepoint?.[1]) {
            out.push({ kind: "chokepoint", id: chokepoint[1].toLowerCase(), children });
          } else {
            // Any other target (javascript:, a relative path, an unknown scheme) is its text.
            for (const child of children) {
              if (child.kind === "text") pushText(out, child.text);
              else out.push(child);
            }
          }
          i = paren + 1;
          continue;
        }
      }
      plain += ch;
      i += 1;
      continue;
    }
    if ((ch === "*" || ch === "_") && depth < MAX_DEPTH) {
      const double = text[i + 1] === ch;
      const delimiter = double ? ch + ch : ch;
      const after = text[i + delimiter.length];
      const opens = !isSpace(after) && (ch === "*" || !isWord(text[i - 1]));
      if (opens) {
        const closing = firstFrom(index.closers[delimiter] ?? [], i + delimiter.length + 1, end);
        if (closing !== -1) {
          flush();
          const children = inlines(index, i + delimiter.length, closing, depth + 1, inLink);
          out.push({ kind: double ? "strong" : "em", children });
          i = closing + delimiter.length;
          continue;
        }
      }
      plain += delimiter;
      i += delimiter.length;
      continue;
    }
    plain += ch;
    i += 1;
  }
  flush();
  return out;
}

function hostOf(href: string): string {
  try {
    return new URL(href).host;
  } catch {
    return "";
  }
}

/** The owner-words pass over every text node, in reading order; the first opens the block's
 * sentence. */
function ownerPass(nodes: Inline[], first = { value: true }): Inline[] {
  return nodes.map((node) => {
    if (node.kind === "text") {
      const text = ownerWords(node.text, first.value);
      first.value = false;
      return { kind: "text", text };
    }
    return { ...node, children: ownerPass(node.children, first) };
  });
}

/** One block's text as inlines, in the owner's words. */
export function parseInline(text: string): Inline[] {
  return ownerPass(inlines(buildIndex(text), 0, text.length, 0, false));
}

// --- blocks --------------------------------------------------------------------------------

const LIST_ITEM = /^\s*(?:[-*+]|\d{1,9}[.)])\s+/;
const ORDERED_ITEM = /^\s*\d{1,9}[.)]\s+/;
const FENCE = /^ {0,3}(```|~~~)/;
const RULE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;

/** A heading line's level and text, or null: "## Title ##" → [2, "Title"]. */
function heading(line: string): [number, string] | null {
  const body = line.replace(/^ {0,3}/, "");
  let level = 0;
  while (body[level] === "#" && level < 7) level += 1;
  if (level === 0 || level > 6 || (body[level] !== undefined && body[level] !== " " && body[level] !== "\t")) {
    return null;
  }
  let text = body.slice(level).trim();
  let cut = text.length;
  while (cut > 0 && text[cut - 1] === "#") cut -= 1;
  if (cut < text.length && (cut === 0 || text[cut - 1] === " ")) text = text.slice(0, cut).trim();
  return [level, text];
}

/** The memo as blocks: headings (1–3 as h3, 4–6 as h4), paragraphs and one-level lists. Code
 * blocks, fenced or indented, and rules are dropped. */
export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let fence: string | null = null;

  const endParagraph = () => {
    if (paragraph.length > 0) blocks.push({ kind: "paragraph", children: parseInline(paragraph.join(" ")) });
    paragraph = [];
  };
  const endList = () => {
    if (list !== null) {
      blocks.push({ kind: "list", ordered: list.ordered, items: list.items.map(parseInline) });
    }
    list = null;
  };

  for (const raw of lines) {
    if (fence !== null) {
      if (raw.trimStart().startsWith(fence)) fence = null;
      continue;
    }
    const fenced = FENCE.exec(raw);
    if (fenced?.[1]) {
      endParagraph();
      endList();
      fence = fenced[1];
      continue;
    }
    if (raw.trim() === "") {
      endParagraph();
      endList();
      continue;
    }
    const indented = /^( {4}|\t)/.test(raw);
    if (LIST_ITEM.test(raw) && (list !== null || !indented)) {
      endParagraph();
      const ordered = ORDERED_ITEM.test(raw);
      if (list === null) list = { ordered, items: [] };
      list.items.push(raw.replace(LIST_ITEM, "").trim());
      continue;
    }
    const current: { ordered: boolean; items: string[] } | null = list;
    const head = heading(raw);
    if (current !== null && head === null && !RULE.test(raw)) {
      // A continuation of the last item, indented or not (a deeper item matched above).
      const last = current.items.length - 1;
      current.items[last] = `${current.items[last] ?? ""} ${raw.trim()}`;
      continue;
    }
    if (indented && paragraph.length === 0) continue; // an indented code block
    if (head !== null) {
      endParagraph();
      endList();
      blocks.push({ kind: "heading", level: head[0] <= 3 ? 3 : 4, children: parseInline(head[1]) });
      continue;
    }
    if (RULE.test(raw)) {
      endParagraph();
      endList();
      continue;
    }
    paragraph.push(raw.trim().replace(/^>\s?/, ""));
  }
  endParagraph();
  endList();
  return blocks;
}

// --- the excerpt ---------------------------------------------------------------------------

/** Inlines as plain text. */
export function plainText(nodes: readonly Inline[]): string {
  return nodes.map((node) => (node.kind === "text" ? node.text : plainText(node.children))).join("");
}

/** The memo's first paragraph as plain text, else its first list's items joined; a memo of
 * headings only gives "". */
export function memoExcerpt(source: string): string {
  const blocks = parseMarkdown(source);
  const paragraph = blocks.find((block) => block.kind === "paragraph");
  if (paragraph?.kind === "paragraph") return plainText(paragraph.children).trim();
  const list = blocks.find((block) => block.kind === "list");
  if (list?.kind === "list") return list.items.map((item) => plainText(item).trim()).join(" · ");
  return "";
}
