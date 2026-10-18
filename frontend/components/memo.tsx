// The Watch's memo as React elements (spec §10.3.5, R9): the parsed blocks of `lib/markdown.ts`,
// never HTML. A link to the web opens in a new tab with its host beside it; a link to the board
// opens the chokepoint's page. Everything else in the memo is text.
import Link from "next/link";
import { Fragment, type ReactNode } from "react";

import { type Block, type Inline, parseMarkdown } from "../lib/markdown";
import { routes } from "../lib/routes";

function Inlines({ nodes }: { nodes: readonly Inline[] }): ReactNode {
  return nodes.map((node, index) => {
    switch (node.kind) {
      case "text":
        return <Fragment key={index}>{node.text}</Fragment>;
      case "em":
        return (
          <em key={index}>
            <Inlines nodes={node.children} />
          </em>
        );
      case "strong":
        return (
          <strong key={index}>
            <Inlines nodes={node.children} />
          </strong>
        );
      case "link":
        return (
          <Fragment key={index}>
            <a href={node.href} target="_blank" rel="noopener noreferrer nofollow">
              <Inlines nodes={node.children} />
            </a>
            {node.host ? <span className="memo-host"> ({node.host})</span> : null}
          </Fragment>
        );
      case "chokepoint":
        return (
          <Link key={index} href={routes.chokepoint(node.id)}>
            <Inlines nodes={node.children} />
          </Link>
        );
    }
  });
}

function MemoBlock({ block }: { block: Block }) {
  if (block.kind === "heading") {
    const Heading = block.level === 3 ? "h3" : "h4";
    return (
      <Heading>
        <Inlines nodes={block.children} />
      </Heading>
    );
  }
  if (block.kind === "paragraph") {
    return (
      <p>
        <Inlines nodes={block.children} />
      </p>
    );
  }
  const List = block.ordered ? "ol" : "ul";
  return (
    <List>
      {block.items.map((item, index) => (
        <li key={index}>
          <Inlines nodes={item} />
        </li>
      ))}
    </List>
  );
}

export function Memo({ source }: { source: string }) {
  const blocks = parseMarkdown(source);
  return (
    <div className="memo measure">
      {blocks.map((block, index) => (
        <MemoBlock key={index} block={block} />
      ))}
    </div>
  );
}
