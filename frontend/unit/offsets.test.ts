import { expect, test } from "@playwright/test";

import { spanFromUtf16, utf16Index } from "../lib/offsets";

test("a page anchor's code-point offset maps to its UTF-16 index", () => {
  // 😀 is two UTF-16 units: code point 2 (the "p" of "page") is UTF-16 index 3.
  const text = "😀\npage two";
  expect(utf16Index(text, 0)).toBe(0);
  expect(utf16Index(text, 2)).toBe(3);
  expect(text.slice(utf16Index(text, 2))).toBe("page two");
  expect(utf16Index(text, 10)).toBe(text.length);
  expect(utf16Index(text, 99)).toBe(text.length);
  expect(() => utf16Index(text, -1)).toThrow(RangeError);
});

// The API binds an Assertion to code-point offsets into the parsed text (Python string
// indices), while the browser's Selection/Range offsets count UTF-16 code units. The
// expected offsets below are counted by hand from each constructed string.

test("ASCII text: UTF-16 and code-point offsets coincide", () => {
  expect(spanFromUtf16("Net revenue was up", 4, 11)).toEqual({
    quote: "revenue",
    span_start: 4,
    span_end: 11,
  });
});

test("BMP punctuation before the span counts one character each (not UTF-8 bytes)", () => {
  // “ and ” are one UTF-16 unit and one code point each (but three UTF-8 bytes each).
  const text = "“Lumentum” said";
  expect(spanFromUtf16(text, 11, 15)).toEqual({ quote: "said", span_start: 11, span_end: 15 });
});

test("an astral character before the span shifts the code-point offsets by one", () => {
  // 😀 (U+1F600) is two UTF-16 units but one code point.
  const text = "😀 revenue";
  expect(spanFromUtf16(text, 3, 10)).toEqual({ quote: "revenue", span_start: 2, span_end: 9 });
});

test("several astral characters before the span", () => {
  // 𝐀 and 𝐁 (U+1D400, U+1D401) are two UTF-16 units each.
  const text = "𝐀𝐁 x";
  expect(spanFromUtf16(text, 5, 6)).toEqual({ quote: "x", span_start: 3, span_end: 4 });
});

test("an astral character inside the span counts once", () => {
  expect(spanFromUtf16("a😀b", 0, 4)).toEqual({ quote: "a😀b", span_start: 0, span_end: 3 });
});

test("a boundary inside a surrogate pair widens to the whole character", () => {
  // Starting between 😀's two halves widens back; ending between them widens forward.
  expect(spanFromUtf16("a😀b", 2, 4)).toEqual({ quote: "😀b", span_start: 1, span_end: 3 });
  expect(spanFromUtf16("a😀b", 0, 2)).toEqual({ quote: "a😀", span_start: 0, span_end: 2 });
});

test("whitespace is counted as it is, never normalized", () => {
  expect(spanFromUtf16("a\tb\n  c", 6, 7)).toEqual({ quote: "c", span_start: 6, span_end: 7 });
  expect(spanFromUtf16("a\tb\n  c", 1, 5)).toEqual({ quote: "\tb\n ", span_start: 1, span_end: 5 });
});

test("the quote is the code-point slice at the offsets", () => {
  const text = "“Q4” 😀 net revenue — 𝐀 $1.01 billion";
  const start = text.indexOf("net");
  const span = spanFromUtf16(text, start, text.length);
  expect(span).not.toBeNull();
  // Array.from splits by code point, as Python's str indexing does.
  expect(Array.from(text).slice(span!.span_start, span!.span_end).join("")).toBe(span!.quote);
  expect(span!.quote).toBe("net revenue — 𝐀 $1.01 billion");
  expect(span).toMatchObject({ span_start: 7, span_end: 36 });
});

test("an empty selection is no span", () => {
  expect(spanFromUtf16("abc", 1, 1)).toBeNull();
});

test("offsets outside the text are refused", () => {
  expect(() => spanFromUtf16("abc", 0, 4)).toThrow(RangeError);
  expect(() => spanFromUtf16("abc", -1, 2)).toThrow(RangeError);
  expect(() => spanFromUtf16("abc", 2, 1)).toThrow(RangeError);
});
