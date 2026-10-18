import { expect, test } from "@playwright/test";

import { type Block, type Inline, memoExcerpt, ownerWords, parseInline, parseMarkdown, plainText } from "../lib/markdown";

const A = "3f2b8c1e-9d4a-4b6e-8f10-2a3b4c5d6e7f";

/** Every inline node, depth first. */
function nodes(blocks: readonly Block[]): Inline[] {
  const walk = (list: readonly Inline[]): Inline[] =>
    list.flatMap((node) => (node.kind === "text" ? [node] : [node, ...walk(node.children)]));
  return blocks.flatMap((block) =>
    block.kind === "list" ? block.items.flatMap((item) => walk(item)) : walk(block.children),
  );
}

const textOf = (blocks: readonly Block[]) =>
  blocks
    .map((block) => (block.kind === "list" ? block.items.map(plainText).join("\n") : plainText(block.children)))
    .join("\n");

test("headings, paragraphs and lists", () => {
  const blocks = parseMarkdown(
    "# Robotics\r\n\r\nTwo makers hold\nmost capacity.\r\n\r\n#### Detail ##\n\n- one\n- two\n    - deeper\n\n1. first\n2) second\n",
  );
  expect(blocks.map((block) => block.kind)).toEqual(["heading", "paragraph", "heading", "list", "list"]);
  expect(blocks[0]).toEqual({ kind: "heading", level: 3, children: [{ kind: "text", text: "Robotics" }] });
  expect(blocks[2]?.kind === "heading" && blocks[2].level).toBe(4);
  expect(plainText((blocks[1] as Extract<Block, { kind: "paragraph" }>).children)).toBe("Two makers hold most capacity.");
  const list = blocks[3] as Extract<Block, { kind: "list" }>;
  expect(list.ordered).toBe(false);
  expect(list.items.map(plainText)).toEqual(["one", "two", "deeper"]);
  expect((blocks[4] as Extract<Block, { kind: "list" }>).ordered).toBe(true);
});

test("a list item's wrapped lines continue it, indented or not", () => {
  const blocks = parseMarkdown("- [A](https://a.io): first line\n  wraps here\nand here\n- second\n\nAfter.");
  expect(blocks.map((block) => block.kind)).toEqual(["list", "paragraph"]);
  const list = blocks[0] as Extract<Block, { kind: "list" }>;
  expect(list.items.map(plainText)).toEqual(["A: first line wraps here and here", "second"]);
});

test("emphasis, strong, and unbalanced markers stay literal", () => {
  const [first] = parseMarkdown("A **bold** and *soft* and _lean_ word, 2 * 3 and **open");
  expect(first?.kind).toBe("paragraph");
  const children = (first as Extract<Block, { kind: "paragraph" }>).children;
  expect(children.map((node) => node.kind)).toEqual(["text", "strong", "text", "em", "text", "em", "text"]);
  expect(plainText(children)).toBe("A bold and soft and lean word, 2 * 3 and **open");
  // An underscore inside a word is not emphasis.
  expect(plainText(parseInline("snake_case_name stays"))).toBe("snake_case_name stays");
  expect(parseInline("snake_case_name stays").every((node) => node.kind === "text")).toBe(true);
});

test("links: http(s) leave Atlas, a chokepoint opens the board, anything else is its text", () => {
  const inline = parseInline(
    `[ok](https://example.com/a?b=1) [bad](javascript:window.__pwned=1) [rel](/system/) [A](atlas:chokepoint/${A}) [Z](atlas:chokepoint/not-a-uuid)`,
  );
  const links = inline.filter((node) => node.kind === "link");
  expect(links).toEqual([
    { kind: "link", href: "https://example.com/a?b=1", host: "example.com", children: [{ kind: "text", text: "ok" }] },
  ]);
  const chokepoints = inline.filter((node) => node.kind === "chokepoint");
  expect(chokepoints).toEqual([{ kind: "chokepoint", id: A, children: [{ kind: "text", text: "A" }] }]);
  expect(plainText(inline)).toBe("ok bad rel A Z");
  expect(JSON.stringify(inline)).not.toContain("javascript");
});

test("raw HTML stays literal text and code is dropped or read as text", () => {
  const blocks = parseMarkdown(
    [
      "<script>window.__pwned=1</script>",
      "",
      "```",
      "uv run atlas ingest --company x",
      "```",
      "",
      "Inline `thesis_ready` here.",
      "",
      "    indented code block",
      "",
      "<img src=x onerror=alert(1)>",
    ].join("\n"),
  );
  const text = textOf(blocks);
  expect(text).toContain("<script>window.__pwned=1</script>");
  expect(text).toContain("<img src=x onerror=alert(1)>");
  expect(text).not.toContain("uv run");
  expect(text).not.toContain("indented code block");
  expect(text).toContain("Inline thesis-ready here.");
  expect(nodes(blocks).every((node) => node.kind === "text")).toBe(true);
});

test("an unclosed fence drops the rest of the memo", () => {
  expect(textOf(parseMarkdown("Before.\n\n~~~\nsecret\nmore"))).toBe("Before.");
});

test("the owner-words pass: codes, step letters and ISO days in words", () => {
  expect(ownerWords("thesis_ready since the kill_criteria held", true)).toBe(
    "Thesis-ready since the falsifiers held",
  );
  expect(ownerWords("it is thesis_ready. thesis_ready again", true)).toBe("it is thesis-ready. Thesis-ready again");
  expect(ownerWords(" now thesis_ready", false)).toBe(" now thesis-ready");
  expect(ownerWords("step d is weak; step_b holds; see step (f) and Step a")).toBe(
    "Control is weak; Demand holds; see Invalidation and Constraint",
  );
  expect(ownerWords("missing step_d_primary and open_issue; unexamined; demand_vs_supply")).toBe(
    "missing a quote for control and open question; not examined; demand against supply",
  );
  expect(ownerWords("Filed 2026-03-04, read 2026-10-24.")).toBe("Filed 4 Mar 2026, read 24 Oct 2026.");
  // Ordinary words are left alone: a memo's "lead" or "early" means what it says.
  expect(ownerWords("a lead time, an early candidate, the primary source")).toBe(
    "a lead time, an early candidate, the primary source",
  );
  expect(ownerWords("the stepladder")).toBe("the stepladder");
});

test("a UUID is removed and the gap it leaves collapsed", () => {
  expect(ownerWords(`Fact ${A} shows it`)).toBe("Fact shows it");
  expect(ownerWords(`The run (${A}) closed`)).toBe("The run closed");
  expect(ownerWords(`See [${A}], then go`)).toBe("See, then go");
  expect(ownerWords(`Ends with ${A}.`)).toBe("Ends with.");
  expect(ownerWords(`${A.toUpperCase()} leads`)).toBe(" leads");
  const memo = textOf(parseMarkdown(`Fact ${A} shows it.`));
  expect(memo).toBe("Fact shows it.");
  expect(memo).not.toMatch(/ {2}/);
});

test("the excerpt: the first paragraph, else the first list, else nothing", () => {
  expect(memoExcerpt("# Robotics\n\nTwo makers, **step d**, hold it.\n\nMore.")).toBe("Two makers, Control, hold it.");
  expect(memoExcerpt("## Discoveries\n\n- One\n- Two")).toBe("One · Two");
  expect(memoExcerpt("# Only\n## Headings")).toBe("");
  expect(memoExcerpt("")).toBe("");
});

test("hostile input parses quickly: a 50 KB memo of markers in under 50 ms", () => {
  const hostile = [
    "*".repeat(10_000),
    "[".repeat(8_000),
    "_a".repeat(5_000),
    "`".repeat(5_000),
    "](".repeat(5_000),
    "**x ".repeat(3_000),
  ].join("");
  expect(hostile.length).toBeGreaterThan(50_000);
  parseMarkdown("warm up **a** [b](https://c)");
  const start = performance.now();
  const blocks = parseMarkdown(hostile);
  const elapsed = performance.now() - start;
  expect(blocks.length).toBeGreaterThan(0);
  expect(elapsed).toBeLessThan(50);
  const lines = Array.from({ length: 2_000 }, (_, index) => `- item ${index} **b** [l](https://x.io/${index}) step d`).join(
    "\n",
  );
  const begin = performance.now();
  parseMarkdown(lines);
  expect(performance.now() - begin).toBeLessThan(50);
});
