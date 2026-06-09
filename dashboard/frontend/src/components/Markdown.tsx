import { ReactNode } from "react";
import { Typography } from "antd";

const { Text } = Typography;

/**
 * Minimal, dependency-free Markdown renderer for assistant messages.
 * Builds React nodes directly (never dangerouslySetInnerHTML), so it is safe
 * against HTML/script injection from model output. Supports: fenced code blocks,
 * inline code, bold, italic, headings, bullet/numbered lists and links.
 */

function renderInline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  // Tokenize on inline code, bold, italic and links in a single pass.
  const re =
    /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const tok = m[0];
    const k = `${keyBase}-i${i++}`;
    if (tok.startsWith("`")) {
      nodes.push(
        <Text key={k} code style={{ fontSize: 12 }}>
          {tok.slice(1, -1)}
        </Text>,
      );
    } else if (tok.startsWith("**")) {
      nodes.push(<strong key={k}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("*")) {
      nodes.push(<em key={k}>{tok.slice(1, -1)}</em>);
    } else {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok);
      if (mm) {
        nodes.push(
          <a key={k} href={mm[2]} target="_blank" rel="noreferrer">
            {mm[1]}
          </a>,
        );
      } else {
        nodes.push(tok);
      }
    }
    last = m.index + tok.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function CodeBlock({ code }: { code: string }) {
  return (
    <pre
      style={{
        margin: "6px 0",
        background: "#0b1220",
        border: "1px solid #1f3257",
        borderRadius: 6,
        padding: 10,
        fontSize: 12,
        color: "#7dd3fc",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        overflow: "auto",
        maxHeight: 320,
      }}
    >
      {code}
    </pre>
  );
}

export function Markdown({ content }: { content: string }) {
  const blocks: ReactNode[] = [];
  const lines = content.split("\n");
  let i = 0;
  let key = 0;
  let listBuf: { ordered: boolean; items: string[] } | null = null;

  const flushList = () => {
    if (!listBuf) return;
    const items = listBuf.items;
    const ordered = listBuf.ordered;
    blocks.push(
      ordered ? (
        <ol key={`b${key++}`} style={{ margin: "4px 0", paddingLeft: 20 }}>
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it, `l${key}-${idx}`)}</li>
          ))}
        </ol>
      ) : (
        <ul key={`b${key++}`} style={{ margin: "4px 0", paddingLeft: 20 }}>
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it, `l${key}-${idx}`)}</li>
          ))}
        </ul>
      ),
    );
    listBuf = null;
  };

  while (i < lines.length) {
    const line = lines[i];

    // fenced code block
    if (line.trimStart().startsWith("```")) {
      flushList();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing fence
      blocks.push(<CodeBlock key={`b${key++}`} code={codeLines.join("\n")} />);
      continue;
    }

    // headings
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      flushList();
      const level = h[1].length;
      const size = [16, 15, 14, 13][level - 1] || 13;
      blocks.push(
        <div
          key={`b${key++}`}
          style={{ fontWeight: 600, fontSize: size, margin: "8px 0 2px" }}
        >
          {renderInline(h[2], `h${key}`)}
        </div>,
      );
      i++;
      continue;
    }

    // list items
    const ul = /^\s*[-*]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (ul || ol) {
      const ordered = !!ol;
      const item = (ul ? ul[1] : (ol as RegExpExecArray)[1]) || "";
      if (!listBuf || listBuf.ordered !== ordered) {
        flushList();
        listBuf = { ordered, items: [] };
      }
      listBuf.items.push(item);
      i++;
      continue;
    }

    // blank line
    if (line.trim() === "") {
      flushList();
      i++;
      continue;
    }

    // paragraph (merge consecutive non-special lines)
    flushList();
    const paraLines: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trimStart().startsWith("```") &&
      !/^(#{1,4})\s+/.test(lines[i]) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push(
      <div key={`b${key++}`} style={{ margin: "2px 0", whiteSpace: "pre-wrap" }}>
        {renderInline(paraLines.join("\n"), `p${key}`)}
      </div>,
    );
  }
  flushList();

  return <div style={{ color: "#e2e8f0" }}>{blocks}</div>;
}
