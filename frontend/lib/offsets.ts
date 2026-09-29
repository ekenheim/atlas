// Converting a browser selection in the parsed text into an Assertion's quote span.
//
// The API binds an Assertion to `parsed_text[span_start:span_end] == quote`, with offsets
// in characters (Unicode code points) of the parsed text, as Python indexes a str. The
// browser's Selection and Range offsets count UTF-16 code units instead, so a character
// outside the Basic Multilingual Plane (an emoji, a math letter) is two DOM units but one
// API character. The parsed text is rendered verbatim as the text nodes of one element
// (no whitespace collapsing: `white-space: pre-wrap`), so a DOM offset within that element
// is a UTF-16 index into the parsed text.

/** A quote and its code-point offsets, as `POST /api/v1/assertions` takes them. */
export type Span = { quote: string; span_start: number; span_end: number };

const isHighSurrogate = (unit: number) => unit >= 0xd800 && unit <= 0xdbff;
const isLowSurrogate = (unit: number) => unit >= 0xdc00 && unit <= 0xdfff;

/** Whether UTF-16 index `index` falls between the two halves of a surrogate pair. */
function splitsPair(text: string, index: number): boolean {
  return (
    index > 0 &&
    index < text.length &&
    isHighSurrogate(text.charCodeAt(index - 1)) &&
    isLowSurrogate(text.charCodeAt(index))
  );
}

/** The number of code points in `text` before UTF-16 index `index`. */
function codePointsBefore(text: string, index: number): number {
  let count = 0;
  // A string iterates by code point, as Python indexes a str.
  for (const character of text.slice(0, index)) count += character ? 1 : 0;
  return count;
}

/**
 * The Span of `text` between UTF-16 indices `start` and `end` (a DOM selection's
 * offsets), or null when it is empty. A boundary between the halves of a surrogate pair
 * widens to take in the whole character.
 */
export function spanFromUtf16(text: string, start: number, end: number): Span | null {
  if (!(Number.isInteger(start) && Number.isInteger(end)) || start < 0 || end > text.length) {
    throw new RangeError(`[${start}, ${end}) is outside the text (${text.length} UTF-16 units)`);
  }
  if (end < start) throw new RangeError(`[${start}, ${end}) ends before it starts`);
  if (start === end) return null;
  if (splitsPair(text, start)) start--;
  if (splitsPair(text, end)) end++;
  const span_start = codePointsBefore(text, start);
  const quote = text.slice(start, end);
  return { quote, span_start, span_end: span_start + codePointsBefore(quote, quote.length) };
}

/**
 * The UTF-16 offsets, within `root`'s text, of the part of `range` inside `root`, or
 * null when the range does not overlap it. The offsets count the text nodes' data
 * exactly, whatever elements (such as highlights) the text is split across.
 */
export function utf16OffsetsIn(root: Node, range: Range): [number, number] | null {
  const document = root.ownerDocument;
  if (!document) return null;
  const whole = document.createRange();
  whole.selectNodeContents(root);
  let startSide: number;
  let endSide: number;
  try {
    startSide = whole.comparePoint(range.startContainer, range.startOffset);
    endSide = whole.comparePoint(range.endContainer, range.endOffset);
  } catch {
    return null; // the range is in another document or a detached tree
  }
  if (startSide > 0 || endSide < 0) return null;
  const offset = (node: Node, nodeOffset: number) => {
    const before = document.createRange();
    before.setStart(root, 0);
    before.setEnd(node, nodeOffset);
    return before.toString().length;
  };
  const start = startSide < 0 ? 0 : offset(range.startContainer, range.startOffset);
  const end =
    endSide > 0 ? whole.toString().length : offset(range.endContainer, range.endOffset);
  return [start, end];
}

/**
 * The UTF-16 index in `text` of code point `codePoints` (an API offset, such as a page
 * anchor's start); `text.length` when it is at or past the end.
 */
export function utf16Index(text: string, codePoints: number): number {
  if (!Number.isInteger(codePoints) || codePoints < 0) {
    throw new RangeError(`${codePoints} is not a code-point offset`);
  }
  let index = 0;
  let seen = 0;
  for (const character of text) {
    if (seen === codePoints) return index;
    index += character.length;
    seen += 1;
  }
  return text.length;
}

/**
 * The text node and offset at UTF-16 index `index` of `root`'s text, whatever elements
 * (such as highlights) the text is split across; null when `root` has less text.
 */
export function domPosition(root: Node, index: number): { node: Text; offset: number } | null {
  const document = root.ownerDocument;
  if (!document) return null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let remaining = index;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node as Text;
    if (remaining <= text.data.length) return { node: text, offset: remaining };
    remaining -= text.data.length;
  }
  return null;
}

/**
 * The Span the current selection makes in `text`, rendered as `root`'s content, or null
 * when nothing in it is selected. A selection reaching outside `root` is clipped to it.
 */
export function selectedSpan(root: Node, text: string, selection: Selection): Span | null {
  if (selection.rangeCount === 0 || selection.isCollapsed) return null;
  const offsets = utf16OffsetsIn(root, selection.getRangeAt(0));
  if (!offsets) return null;
  const [start, end] = offsets;
  if (end > text.length) return null; // the element no longer shows this text
  return spanFromUtf16(text, start, end);
}

/**
 * `text` split around the code-point span [`start`, `end`) (an Assertion's offsets): the
 * text before it, the span itself and the text after, as UTF-16 strings to render.
 */
export function splitAtSpan(text: string, start: number, end: number): [string, string, string] {
  if (end < start) throw new RangeError(`[${start}, ${end}) ends before it starts`);
  const from = utf16Index(text, start);
  const to = utf16Index(text, end);
  return [text.slice(0, from), text.slice(from, to), text.slice(to)];
}
