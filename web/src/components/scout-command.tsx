import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useDesk } from '../App';
import { DATA_CHANGED, request } from '../lib/api';
import { date } from '../lib/format';
import { boundedHistory, HISTORY_KEY, readHistory } from '../lib/scout-history';
import type { Citation, Command, ScoutReply, Turn } from '../lib/scout-history';
import { SafeMarkdown } from './memory-markdown';
import { Button } from './ui/button';

interface Evidence {
    label: string;
    entity_type: Citation['entity_type'];
    version: string | number;
    snapshot_at?: string;
    href: string;
    newer_information: boolean;
    content: Record<string, unknown>;
}
const suggestions = ["What's due this week?", 'What assignments are due?', 'What changed since yesterday?', 'What do you know about my projects?'];

function SourceRecord({ record }: { record: Record<string, unknown> }) {
    return <div className="scout-source"><p>{String(record.status || 'Recorded')} · {typeof record.normalized === 'string' ? record.normalized : ''}</p>
        {typeof record.source_text === 'string' && <blockquote>{record.source_text}</blockquote>}
        {Array.isArray(record.candidates) && record.candidates.map((value, i) => <SourceRecord key={i} record={value} />)}
        {Array.isArray(record.normalized) && record.normalized.map((value: { title?: string; requirements?: { text: string }[] }, i) => <div key={i}><p>{value.title}</p>{value.requirements?.map((r, j) => <p key={j}>{r.text}</p>)}</div>)}
    </div>;
}

function EvidenceContent({ value }: { value: Evidence }) {
    const content = value.content;
    if (value.entity_type === 'task') return <><h4>{String(content.course || 'Course unknown')} · {String(content.title)}</h4>
        <SourceRecord record={content.deadline as Record<string, unknown>} /><blockquote>{String(content.source_quote)}</blockquote>
    </>;
    if (value.entity_type === 'memory') return <><h4>{String(content.display_title || content.name)}</h4><SafeMarkdown text={String(content.content || '')} /></>;
    if (value.entity_type === 'revision' || value.entity_type === 'message') return <><h4>{String(content.subject)}</h4>
        <p>Sent {date(String(content.sent_at || value.snapshot_at))}</p>
        <SourceRecord record={(content.evidence || content.deadline) as Record<string, unknown>} />
        {content.relocation && typeof content.relocation === 'object' && typeof (content.relocation as { relocation_quote?: string }).relocation_quote === 'string' ? <blockquote>{(content.relocation as { relocation_quote: string }).relocation_quote}</blockquote> : null}
        {typeof content.blocker === 'string' && <p>{content.blocker}</p>}
        {typeof content.classification_reason === 'string' && <p>Classification: {content.classification_reason}</p>}
    </>;
    if (value.entity_type === 'step') return <><p>{String(content.text)}</p><p className="meta">Recorded actor: {String(content.actor)}</p></>;
    if (value.entity_type === 'skill') return <><p>Approved skill: {String(content.name)}</p>
        {Array.isArray(content.evidence) && content.evidence.map((proof: { title: string; note: string; source_hash: string }, i) => <div key={i}><h4>{proof.title}</h4><p>{proof.note}</p><p className="meta">Source hash: {proof.source_hash}</p></div>)}
    </>;
    const definition = content.definition as { effect?: string; mailbox?: string; subject?: string; category?: string };
    return <><p>{String(content.scope)} · {String(content.status)}</p><p>{definition.effect?.replaceAll('_', ' ') || `${definition.mailbox} · ${definition.subject || 'Any subject'} · ${definition.category}`}</p></>;
}

export function ScoutCommand({ returnToWork }: { returnToWork: () => void }) {
    const { settings, refresh } = useDesk();
    const input = useRef<HTMLInputElement>(null);
    const conversation = useRef<HTMLElement>(null);
    const evidencePanel = useRef<HTMLElement>(null);
    const [question, setQuestion] = useState('');
    const [history, setHistory] = useState<Turn[]>(readHistory);
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [evidence, setEvidence] = useState<Evidence>();
    const [announcement, setAnnouncement] = useState('');
    useEffect(() => {
        try { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history)); } catch { /* In-memory history remains bounded when storage is unavailable. */ }
    }, [history]);
    // A live update must not close what Uzair is reading: citations already keep the cited
    // version, so the panel stays open and says that newer information arrived.
    const [changedSince, setChangedSince] = useState(false);
    useEffect(() => {
        const changed = () => setChangedSince(true);
        window.addEventListener(DATA_CHANGED, changed);
        return () => window.removeEventListener(DATA_CHANGED, changed);
    }, []);
    useEffect(() => { setChangedSince(false); }, [evidence]);
    useEffect(() => { if (evidence) evidencePanel.current?.focus(); }, [evidence]);
    useEffect(() => {
        const shortcut = (event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
                event.preventDefault(); input.current?.focus();
            }
            if (event.key === 'Escape' && (document.activeElement === input.current || conversation.current?.contains(document.activeElement))) {
                event.preventDefault(); setEvidence(undefined);
                if (open) { setOpen(false); input.current?.focus(); } else returnToWork();
            }
        };
        window.addEventListener('keydown', shortcut);
        return () => window.removeEventListener('keydown', shortcut);
    }, [open, returnToWork]);
    async function ask(text = question, selection?: string, index?: number) {
        if (busy || !text.trim()) return;
        setBusy(true); setError(''); setOpen(true); setEvidence(undefined);
        try {
            const params = new URLSearchParams({ q: text, ...(selection ? { selection } : {}) });
            const reply = await request<ScoutReply>(`/scout/query?${params}`);
            setHistory(old => boundedHistory(index === undefined ? [...old, { question: text, reply }] : old.map((turn, i) => i === index ? { question: text, reply } : turn)));
            setAnnouncement('Scout replied.'); setQuestion('');
        } catch (cause) { setError(cause instanceof Error ? cause.message : 'Local lookup failed.'); }
        finally { setBusy(false); }
    }
    async function execute(command: Command, index: number) {
        if (busy || !['/api/scout/command', '/api/scout/pause'].includes(command.path)) return;
        setBusy(true); setError('');
        try {
            const reply = await request<ScoutReply>(command.path.slice(4), settings.csrf_token, { ticket: command.ticket });
            setHistory(old => boundedHistory(old.map((turn, i) => i === index ? { ...turn, reply } : turn)));
            setEvidence(undefined); setAnnouncement('Scout command completed.');
            window.dispatchEvent(new Event(DATA_CHANGED)); await refresh();
        } catch (cause) { setError(cause instanceof Error ? cause.message : 'Command failed. Ask again for a fresh preview.'); }
        finally { setBusy(false); }
    }
    async function openCitation(citation: Citation) {
        setError('');
        try { setEvidence(await request<Evidence>(citation.url.slice(4))); }
        catch (cause) { setEvidence(undefined); setError(cause instanceof Error ? cause.message : 'Evidence unavailable. Ask again.'); }
    }
    return <div className="scout-command">
        <form onSubmit={event => { event.preventDefault(); void ask(); }}>
            <label htmlFor="scout-command">Ask Scout or give a command</label>
            <div className="scout-input-row"><input id="scout-command" ref={input} readOnly={busy} value={question} maxLength={500} onChange={event => setQuestion(event.target.value)} placeholder="What's due this week?" aria-describedby="command-help" aria-controls={open ? 'scout-conversation' : undefined} /><Button type="submit" disabled={busy || !question.trim()}>Ask Scout</Button></div>
        </form>
        <p id="command-help" className="meta">Local, supported requests · Ctrl / ⌘ K · Questions work while paused</p>
        <div className="actions">{suggestions.map(text => <Button key={text} variant="ghost" disabled={busy} onClick={() => void ask(text)}>{text}</Button>)}</div>
        {history.length > 0 && <Button variant="ghost" aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? 'Close conversation' : 'Show conversation'}</Button>}
        <p role="status" className="sr-only">{announcement}{busy ? ' Working locally.' : ''}</p>
        {error && <p role="alert">{error}</p>}
        {open && <section id="scout-conversation" ref={conversation} aria-label="Conversation with Scout" aria-busy={busy}>
            <p className="meta">History stays in this browser tab: at most 20 exchanges and 200,000 characters. Clear it here or close the tab.</p>
            <Button variant="ghost" disabled={busy} onClick={() => { setHistory([]); setEvidence(undefined); setOpen(false); input.current?.focus(); }}>Clear conversation</Button>
            <ol className="scout-turns">{history.map((turn, index) => <li key={index}>
                <p className="scout-question"><strong>You</strong> · {turn.question}</p>
                <p><strong>Scout</strong> · {turn.reply.text}</p>
                {turn.reply.snapshot_at && <p className="meta">Snapshot queried {date(turn.reply.snapshot_at)} · Dubai</p>}
                {turn.reply.items.length > 0 && <ul>{turn.reply.items.map((item, i) => <li key={i}><p>{item.text}</p><div className="actions">{item.citations.map((citation, j) => <Button key={j} variant="ghost" onClick={() => void openCitation(citation)}>{citation.label} · version {String(citation.version).slice(0, 12)}</Button>)}</div></li>)}</ul>}
                <div className="actions">{turn.reply.choices.map(choice => <Button key={choice.key} variant="outline" disabled={busy} onClick={() => void ask(turn.question, choice.key, index)}>Choose {choice.label}</Button>)}</div>
                {turn.reply.command && <Button disabled={busy || settings.mode === 'replay' || (settings.paused && turn.reply.command.path !== '/api/scout/pause')} onClick={() => void execute(turn.reply.command!, index)}>Confirm command</Button>}
                {turn.reply.undo && <Button variant="outline" disabled={busy || settings.mode === 'replay' || settings.paused} onClick={() => void execute(turn.reply.undo!, index)}>Undo</Button>}
                {turn.reply.suggestion && <p><Link to={`/memory#rule-${turn.reply.suggestion.id}`}>{turn.reply.suggestion.title} · Review suggestion and scope</Link></p>}
                <div className="actions">{turn.reply.suggestions.map(text => <Button key={text} variant="ghost" disabled={busy} onClick={() => void ask(text)}>{text}</Button>)}</div>
            </li>)}</ol>
            {evidence && <section ref={evidencePanel} tabIndex={-1} className="scout-evidence" aria-label="Cited evidence"><h3>{evidence.label}</h3>
                <p className="meta">Cited version {String(evidence.version).slice(0, 12)}{evidence.snapshot_at ? ` · Snapshot ${date(evidence.snapshot_at)}` : ''}</p>
                {(evidence.newer_information || changedSince) && <p className="review">Newer information exists. This is the original cited version.</p>}
                <EvidenceContent value={evidence} />
                <Link to={evidence.href}>Open source workspace</Link>
                <Button variant="ghost" onClick={() => setEvidence(undefined)}>Close evidence</Button>
            </section>}
        </section>}
    </div>;
}
