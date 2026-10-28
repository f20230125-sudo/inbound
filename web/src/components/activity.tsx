import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { DATA_CHANGED, request } from '../lib/api';
import { date } from '../lib/format';
import type { AgentStep, StepsPage } from '../types';
import { Button } from './ui/button';

export function mergeSteps(previous: AgentStep[], incoming: AgentStep[]) {
    const byId = new Map(previous.map(step => [step.id, step]));
    for (const step of incoming) byId.set(step.id, step);
    return [...byId.values()].sort((a, b) => a.id - b.id).slice(-100);
}

/** A Gmail check that found nothing: started, "No new messages", finished. */
export function quiet(step: AgentStep) {
    return step.kind === 'gmail.started' || step.kind === 'gmail.finished'
        || (step.kind === 'gmail.fetched' && /no new messages/i.test(step.text));
}

type Row = AgentStep | { fold: AgentStep[] };

/** Fold each run of quiet Gmail checks into one row, so real work stays visible. */
export function foldQuiet(steps: AgentStep[]): Row[] {
    const rows: Row[] = [];
    let run: AgentStep[] = [];
    const flush = () => {
        if (run.filter(s => s.kind === 'gmail.fetched').length > 1) rows.push({ fold: run });
        else rows.push(...run);
        run = [];
    };
    for (const step of steps) {
        if (quiet(step)) run.push(step);
        else { flush(); rows.push(step); }
    }
    flush();
    return rows;
}

function stepItem(row: Row) {
    if ('fold' in row) {
        const checks = row.fold.filter(s => s.kind === 'gmail.fetched');
        const first = row.fold[0], last = row.fold[row.fold.length - 1];
        return <li key={`fold-${first.id}`} data-step-id={last.id}>
            <p><Link to={last.href}>I checked Gmail {checks.length} times. No new messages.</Link></p>
            <p className="meta"><time dateTime={first.occurred_at}>{date(first.occurred_at)}</time> to <time dateTime={last.occurred_at}>{date(last.occurred_at)}</time></p>
        </li>;
    }
    const step = row;
    return <li key={step.id} data-step-id={step.id}>
        <p><Link to={step.href}>{step.text}</Link></p>
        <p className="meta"><time dateTime={step.occurred_at}>{date(step.occurred_at)}</time> · {step.phase === 'progress' ? 'In progress' : step.outcome}</p>
    </li>;
}

export function Activity({ onReplayChange }: { onReplayChange?: (value: boolean) => void }) {
    const [steps, setSteps] = useState<AgentStep[]>([]);
    const [error, setError] = useState(false);
    const [loaded, setLoaded] = useState(false);
    const [recording, setRecording] = useState<string | null>(null);
    const [announcement, setAnnouncement] = useState('');
    const [pending, setPending] = useState(0);
    const live = useRef<AgentStep[]>([]);
    const cursor = useRef(0);
    const list = useRef<HTMLOListElement>(null);
    const source = useRef<EventSource | null>(null);
    const replaying = useRef(false);
    const away = useRef(false);
    const mounted = useRef(true);
    const reconnect = useRef<() => void>(() => {});
    const replaySequence = useRef(0);

    useEffect(() => {
        mounted.current = true;
        let stopped = false;
        let announcementTimer: number | undefined;
        let refreshTimer: number | undefined;
        let announced = 0;
        let catchingUp = false;
        function receive(incoming: AgentStep[], initial = false) {
            if (stopped || replaying.current) return;
            const fresh = incoming.filter(step => step.id > cursor.current);
            if (!fresh.length) return;
            if (!initial) {
                const bounds = list.current?.getBoundingClientRect();
                away.current = !!bounds && (bounds.bottom > window.innerHeight + 20 || bounds.bottom < 0 || !!list.current?.contains(document.activeElement));
            }
            cursor.current = Math.max(cursor.current, ...fresh.map(step => step.id));
            live.current = mergeSteps(live.current, fresh);
            if (initial || !away.current) setSteps(live.current);
            else setPending(n => n + fresh.length);
            if (!initial) {
                announced += fresh.length;
                if (announcementTimer === undefined) announcementTimer = window.setTimeout(() => {
                    if (replaying.current) { announced = 0; announcementTimer = undefined; return; }
                    setAnnouncement(`${announced} new activity steps.`);
                    announced = 0; announcementTimer = undefined;
                }, 1000);
                if (fresh.some(step => step.phase === 'committed_result') && refreshTimer === undefined) {
                    refreshTimer = window.setTimeout(() => {
                        if (!replaying.current) window.dispatchEvent(new Event(DATA_CHANGED)); refreshTimer = undefined;
                    }, 250);
                }
            }
        }
        async function catchUp(initial = false) {
            if (catchingUp || replaying.current) return;
            catchingUp = true;
            try {
                let more = true;
                while (more && !stopped && !replaying.current) {
                    const result = await request<StepsPage>(`/agent/steps${initial && cursor.current === 0 ? '' : `?after=${cursor.current}`}`);
                    if (stopped || replaying.current) return;
                    receive(result?.steps || [], initial);
                    more = !!result?.has_more;
                    setLoaded(true); setError(false);
                }
            } catch { if (!stopped) setError(true); }
            finally { catchingUp = false; }
        }
        function connect() {
            if (stopped || replaying.current || source.current || typeof EventSource === 'undefined') return;
            const stream = new EventSource(`/api/agent/stream?after=${cursor.current}`);
            source.current = stream;
            stream.onmessage = event => {
                try { receive([JSON.parse(event.data) as AgentStep]); setError(false); }
                catch { setError(true); }
            };
            stream.onerror = () => { if (!stopped) setError(true); };
        }
        reconnect.current = () => { void catchUp().then(connect); };
        void catchUp(true).then(connect);
        const timer = window.setInterval(() => {
            if (!document.hidden && !replaying.current) void catchUp().then(connect);
        }, 10000);
        const scroll = () => {
            const bounds = list.current?.getBoundingClientRect();
            away.current = !!bounds && (bounds.bottom > window.innerHeight + 20 || bounds.bottom < 0);
        };
        window.addEventListener('scroll', scroll, { passive: true });
        return () => {
            stopped = true; mounted.current = false;
            onReplayChange?.(false);
            source.current?.close(); source.current = null;
            clearInterval(timer); clearTimeout(announcementTimer); clearTimeout(refreshTimer);
            window.removeEventListener('scroll', scroll);
        };
    }, [onReplayChange]);

    async function replay() {
        const sequence = ++replaySequence.current;
        replaying.current = true;
        onReplayChange?.(true);
        source.current?.close(); source.current = null;
        setAnnouncement(''); setError(false); setPending(0);
        setRecording('Loading recorded check…');
        try {
            let after = 0;
            let history: AgentStep[] = [];
            let label = '';
            let more = true;
            let recordingId: number | undefined;
            let through: number | undefined;
            while (more) {
                const result = await request<StepsPage>(`/agent/steps?replay=${recordingId || 'last'}&after=${after}${through === undefined ? '' : `&through=${through}`}`);
                if (!mounted.current || sequence !== replaySequence.current) return;
                history = mergeSteps(history, result.steps);
                recordingId = result.recording_id; through = result.through;
                label = result.label || 'No recorded check is available.';
                after = result.after; more = result.has_more;
            }
            if (mounted.current) { setSteps(history); setRecording(label); setLoaded(true); }
        } catch { if (mounted.current && sequence === replaySequence.current) { setRecording('Recorded check unavailable.'); setError(true); setLoaded(true); } }
    }
    function resume() {
        replaySequence.current++;
        replaying.current = false; setRecording(null); setSteps(live.current); setPending(0);
        onReplayChange?.(false); reconnect.current();
    }
    function showActivity() {
        setSteps(live.current); setPending(0); away.current = false;
        window.requestAnimationFrame(() => list.current?.scrollIntoView({ block: 'end', behavior: 'instant' }));
    }
    return <>
        <p className="meta">{recording || 'Live activity · oldest first · up to 100 steps'}</p>
        <div className="actions">{recording ? <Button variant="outline" onClick={resume}>Return to live activity</Button> : <Button variant="outline" onClick={() => void replay()}>Replay last check</Button>}
            {pending > 0 && <Button variant="outline" onClick={showActivity}>New activity ({pending})</Button>}</div>
        {error && <p role="status">Activity connection unavailable. Saved steps remain visible; retrying locally.</p>}
        {!loaded ? <p>Loading activity…</p> : !steps.length ? <p>No steps recorded.</p> : (() => {
            const rows = foldQuiet(steps);
            return <>
                {rows.length > 10 && <details><summary>Earlier activity ({rows.length - 10})</summary>
                    <ol className="work-log" aria-label="Earlier activity">{rows.slice(0, -10).map(stepItem)}</ol>
                </details>}
                <ol ref={list} className="work-log" aria-label={recording ? 'Recorded activity' : 'Live activity'}>
                    {rows.slice(-10).map(stepItem)}
                </ol>
            </>;
        })()}
        <p className="sr-only" aria-live="polite" aria-atomic="true">{recording ? '' : announcement}</p>
        <Link className="dispatch-footer" to="/settings#runs">View runs</Link>
    </>;
}
