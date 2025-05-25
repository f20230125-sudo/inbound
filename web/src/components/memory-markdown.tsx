import type { ReactNode } from 'react';

function safeLink(value: string) {
    try {
        const url = new URL(value);
        return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
}

function inline(text: string): ReactNode[] {
    // Deliberately small Markdown subset, built from React text nodes. Raw HTML stays
    // visible text; images, embeds and executable URL schemes never become elements.
    const tokens = /(!?\[[^\]\n]{1,300}\]\([^\s)]{1,2048}\)|`[^`\n]+`|\*\*[^*\n]+\*\*)/g;
    return text.split(tokens).map((part, index) => {
        if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
        if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
        const href = link && safeLink(link[2]);
        return href && link ? <a key={index} href={href} target="_blank" rel="noreferrer noopener">{link[1]}</a> : part;
    });
}

export function SafeMarkdown({ text }: { text: string }) {
    const lines = text.replace(/\r\n/g, '\n').split('\n');
    const blocks: ReactNode[] = [];
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (!line.trim()) continue;
        if (line.startsWith('```')) {
            const code: string[] = [];
            while (++i < lines.length && !lines[i].startsWith('```')) code.push(lines[i]);
            blocks.push(<pre key={i}><code>{code.join('\n')}</code></pre>);
        } else if (/^#{1,6}\s/.test(line)) {
            blocks.push(<h4 key={i}>{inline(line.replace(/^#{1,6}\s+/, ''))}</h4>);
        } else if (/^[-*+]\s/.test(line)) {
            const items = [line.replace(/^[-*+]\s+/, '')];
            while (i + 1 < lines.length && /^[-*+]\s/.test(lines[i + 1])) items.push(lines[++i].replace(/^[-*+]\s+/, ''));
            blocks.push(<ul key={i}>{items.map((item, n) => <li key={n}>{inline(item)}</li>)}</ul>);
        } else if (/^\d+\.\s/.test(line)) {
            const items = [line.replace(/^\d+\.\s+/, '')];
            while (i + 1 < lines.length && /^\d+\.\s/.test(lines[i + 1])) items.push(lines[++i].replace(/^\d+\.\s+/, ''));
            blocks.push(<ol key={i}>{items.map((item, n) => <li key={n}>{inline(item)}</li>)}</ol>);
        } else {
            blocks.push(<p key={i}>{inline(line)}</p>);
        }
    }
    return <div className="memory-markdown">{blocks}</div>;
}
