import { Fragment, type ReactNode } from "react";

export function MarkdownContent({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const nodes: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.trimStart().startsWith("```")) {
      const language = line.trim().slice(3).trim();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trimStart().startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      index += index < lines.length ? 1 : 0;
      nodes.push(<pre className="markdown-code-block" key={`code-${index}`}><code data-language={language || undefined}>{code.join("\n")}</code></pre>);
      continue;
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = inlineMarkdown(heading[2], `heading-${index}`);
      if (level === 1) nodes.push(<h1 key={`h-${index}`}>{content}</h1>);
      if (level === 2) nodes.push(<h2 key={`h-${index}`}>{content}</h2>);
      if (level === 3) nodes.push(<h3 key={`h-${index}`}>{content}</h3>);
      if (level === 4) nodes.push(<h4 key={`h-${index}`}>{content}</h4>);
      index += 1;
      continue;
    }

    if (/^[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^[-*+]\s+/, ""));
        index += 1;
      }
      nodes.push(<ul key={`ul-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inlineMarkdown(item, `ul-${index}-${itemIndex}`)}</li>)}</ul>);
      continue;
    }

    if (/^\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+[.)]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\d+[.)]\s+/, ""));
        index += 1;
      }
      nodes.push(<ol key={`ol-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inlineMarkdown(item, `ol-${index}-${itemIndex}`)}</li>)}</ol>);
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      nodes.push(<blockquote key={`quote-${index}`}>{quote.map((item, itemIndex) => <Fragment key={itemIndex}>{inlineMarkdown(item, `quote-${index}-${itemIndex}`)}{itemIndex < quote.length - 1 && <br />}</Fragment>)}</blockquote>);
      continue;
    }

    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    nodes.push(<p key={`p-${index}`}>{paragraph.map((item, itemIndex) => <Fragment key={itemIndex}>{inlineMarkdown(item, `p-${index}-${itemIndex}`)}{itemIndex < paragraph.length - 1 && <br />}</Fragment>)}</p>);
  }

  return <>{nodes}</>;
}

function isBlockStart(line: string): boolean {
  return /^(#{1,4})\s+/.test(line) || /^[-*+]\s+/.test(line) || /^\d+[.)]\s+/.test(line) || /^>\s?/.test(line) || line.trimStart().startsWith("```");
}

function inlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^\s)]+\))/g;
  const parts = text.split(pattern).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={`${keyPrefix}-${index}`}>{part.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\(([^\s)]+)\)$/.exec(part);
    if (link) {
      const href = safeHref(link[2]);
      return href ? <a key={`${keyPrefix}-${index}`} href={href} target="_blank" rel="noreferrer">{link[1]}</a> : <span key={`${keyPrefix}-${index}`}>{link[1]}</span>;
    }
    return <Fragment key={`${keyPrefix}-${index}`}>{part}</Fragment>;
  });
}

function safeHref(value: string): string {
  if (value.startsWith("/") || value.startsWith("#")) return value;
  try {
    const url = new URL(value);
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? value : "";
  } catch {
    return "";
  }
}
