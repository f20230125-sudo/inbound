import { useEffect, useId, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card } from './ui/card';
import { Skeleton } from './ui/skeleton';
import type { Field, Provenance, Revision, Settings, Snapshot } from '../types';
import { badgeVariant, date, deadlineText, fieldValue, label } from '../lib/format';
export function Section({ title, children, id, className = '' }: {
    title: string;
    children: ReactNode;
    id?: string;
    className?: string;
}) {
    return <Card className={`section ${className}`} id={id}><h2>{title}</h2>{children}</Card>;
}
export function StatusBadge({ value }: {
    value: string;
}) { const text = label(value); return <Badge variant={badgeVariant(text)}>{text}</Badge>; }
export function Loading({ text }: {
    text: string;
}) { return <div aria-busy="true"><p>{text}</p><Skeleton className="h-20 w-full"/></div>; }
export function Failure({ text, retry }: {
    text: string;
    retry: () => void;
}) { return <div role="alert"><p>{text}</p><Button variant="outline" onClick={retry}>Retry</Button></div>; }
export function mutationReason(settings: Settings) { return settings.mode === 'replay' ? 'Available in local mode' : settings.paused ? 'Resume work to make changes' : ''; }
export function PauseControl({ paused, replay, save, active = false }: {
    paused: boolean;
    replay: boolean;
    save: (value: boolean) => Promise<void>;
    active?: boolean;
}) {
    const [busy, setBusy] = useState(false);
    const [failed, setFailed] = useState(false);
    const [stageWarning, setStageWarning] = useState(false);
    async function toggle() { setBusy(true); setFailed(false); try {
        await save(!paused);
        setStageWarning(!paused && active);
    }
    catch {
        setFailed(true);
    }
    finally {
        setBusy(false);
    } }
    return <div className="pause-control"><Button variant="outline" disabled={replay || busy} onClick={toggle}>{paused ? 'Resume work' : 'Pause new work'}</Button><p role="status">{paused ? 'Paused — imports, extraction and pack work are stopped.' : 'Work enabled'}</p>{stageWarning && paused && <p role="status">Pause saved. The current stage may finish; no next stage or retry will start.</p>}{replay && <p>Read-only replay. Pause can be changed in local mode.</p>}{failed && <p role="alert">Pause could not be saved. Work may still be enabled.</p>}</div>;
}
export function SnapshotBanner({ snapshot }: {
    snapshot: Snapshot;
}) {
    return <div className="snapshot"><p>Last successful import: {date(snapshot.imported_at)}</p><p>Latest message in that import: {date(snapshot.latest_message_at)}</p>{snapshot.stale && <div className="notice review"><strong>Snapshot may be out of date</strong><p>Last successful import: {date(snapshot.imported_at)}. New mail may be missing.</p><Link to="/settings#import">Import messages</Link></div>}{snapshot.latest_import_failure && <div className="notice"><strong>Latest import failed. Showing the last successful snapshot.</strong><p><Link to={`/settings?run=${snapshot.latest_import_failure.id}#runs`}>View run</Link></p></div>}</div>;
}
export function DeadlineDisplay({ record, now, frozen = true, admin = false }: {
    record: Field | null | undefined;
    now: string;
    frozen?: boolean;
    admin?: boolean;
}) {
    const [tick, setTick] = useState(0);
    useEffect(() => { if (frozen)
        return; const timer = window.setInterval(() => setTick(v => v + 1), 60000); return () => clearInterval(timer); }, [frozen]);
    const result = deadlineText(record, frozen ? now : new Date(new Date(now).getTime() + tick * 60000).toISOString());
    return <div className={`deadline ${result.tone}`}><strong>{admin && result.tone === 'past' ? `Deadline passed · ${result.label.replace(/^Expired · /, '')}` : result.label}</strong>{result.absolute && <p>{result.absolute}</p>}</div>;
}
export function CopyAnswer({ label: title, answer, provenance, needed = false }: {
    label: string;
    answer: string;
    provenance: string;
    needed?: boolean;
}) {
    const [message, setMessage] = useState('');
    async function copy() { try {
        await navigator.clipboard.writeText(answer);
        setMessage('Copied');
    }
    catch {
        setMessage('Could not copy. Select the answer text to copy it.');
    } }
    return <div className="answer"><h3>{title}</h3>{needed ? <p className="review">Answer needed from you: What broke, and how did you fix it?</p> : <><p className="answer-text" tabIndex={0}>{answer}</p><p className="meta">{answer.length} characters</p><Button variant="outline" onClick={copy}>Copy answer</Button></>}<p className="meta">{provenance}</p><p role="status">{message}</p></div>;
}
export function Highlight({ text, quote }: {
    text: string;
    quote: string;
}) {
    const at = quote ? text.indexOf(quote) : -1;
    return <pre className="source-text">{at < 0 ? text : <>{text.slice(0, at)}<mark>{quote}</mark>{text.slice(at + quote.length)}</>}</pre>;
}
export function SourceText({ title, quote, provenance, revisions = [], fallback }: {
    title: string;
    quote: string;
    provenance?: Provenance;
    revisions?: Revision[];
    fallback?: string;
}) {
    const id = useId();
    const revision = revisions.find(r => r.provider_id === provenance?.message_id);
    const location = provenance?.location || provenance?.source || 'body';
    const source = location === 'subject' ? revision?.subject : location === 'attachment' ? fallback : revision?.body_text;
    return <div className="provenance"><p className="quote">{quote ? `“${quote}”` : ''}</p><p className="meta">{provenance?.message_id} {provenance?.sent_at && `· sent ${date(provenance.sent_at)}`} {provenance?.revision_id && `· revision ${revisions.findIndex(r => r.id === provenance.revision_id) + 1 || provenance.revision_id}`} · {location}</p>{provenance?.locations?.map((loc, i) => <p className="meta" key={i}>{Object.entries(loc).filter(([k]) => k !== 'source_text').map(([k, v]) => `${label(k)}: ${v}`).join(' · ')}</p>)}{quote && <details><summary aria-controls={id}>View source</summary><div id={id}><p className="meta">Source for {title.toLowerCase()}, message {provenance?.message_id}, {location}</p><Highlight text={source || fallback || quote} quote={quote}/></div></details>}</div>;
}
export function ConflictCandidates({ candidates = [], title, revisions }: {
    candidates?: Field[];
    title: string;
    revisions?: Revision[];
}) {
    return <ul className="candidates">{candidates.map((c, i) => <li key={i}><strong>{fieldValue(c.normalized)}</strong><SourceText title={title} quote={c.source_text || ''} provenance={c.provenance} revisions={revisions}/></li>)}</ul>;
}
