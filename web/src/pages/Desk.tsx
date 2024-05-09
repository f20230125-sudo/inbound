import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useDesk } from '../App';
import type { AgentState, Run } from '../types';
import { DATA_CHANGED, request, useResource } from '../lib/api';
import { date, label } from '../lib/format';
import { Briefing, ScoutFace } from '../components/scout';
import { DeadlineDisplay, Failure, Loading, Section } from '../components/shared';
import { Button } from '../components/ui/button';

export default function DeskPage() {
    const { settings, refresh } = useDesk();
    const [state, setState] = useState<AgentState>();
    const [disconnected, setDisconnected] = useState(false);
    const [checking, setChecking] = useState(false);
    const [checkError, setCheckError] = useState('');
    const runs = useResource<Run[]>('/runs', true);
    const command = useRef<HTMLInputElement>(null);
    const work = useRef<HTMLAnchorElement>(null);
    const load = useCallback(async () => {
        try { const value = await request<AgentState>('/agent/state'); setState(value); setDisconnected(false); }
        catch { setDisconnected(true); }
    }, []);
    useEffect(() => {
        let active = true;
        const update = () => { if (active && !document.hidden) void load(); };
        update();
        const timer = window.setInterval(update, 10000);
        document.addEventListener('visibilitychange', update);
        window.addEventListener(DATA_CHANGED, update);
        return () => { active = false; clearInterval(timer); document.removeEventListener('visibilitychange', update); window.removeEventListener(DATA_CHANGED, update); };
    }, [load, settings.paused]);
    useEffect(() => {
        const shortcut = (event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); command.current?.focus(); }
            if (event.key === 'Escape' && document.activeElement === command.current) { event.preventDefault(); work.current?.focus(); }
        };
        window.addEventListener('keydown', shortcut);
        return () => window.removeEventListener('keydown', shortcut);
    }, []);
    async function checkNow() {
        setChecking(true); setCheckError('');
        try { await request('/gmail/sync', settings.csrf_token, {}); window.dispatchEvent(new Event(DATA_CHANGED)); await refresh(); await load(); }
        catch (error) { setCheckError(error instanceof Error ? error.message : 'Gmail check failed.'); await load(); }
        finally { setChecking(false); }
    }
    const mood = disconnected ? 'disconnected' : settings.paused ? 'paused' : state?.mood || 'idle';
    return <div className="dispatch">
        <section className="scout-presence" aria-labelledby="scout-name">
            {state || disconnected ? <ScoutFace mood={mood} /> : <div className="scout-face" aria-hidden="true" />}
            <div><p className="dispatch-kicker">Your Inbound agent</p><h2 id="scout-name">Scout</h2>
                <p className="scout-status" role="status">{disconnected ? "I can't reach the local service. Saved information below may be out of date." : settings.paused ? "I'm paused. Your saved information is available." : state?.status || 'Loading saved state…'}</p>
                {disconnected ? <Button variant="outline" onClick={() => void load()}>Reconnect</Button> : state ? <Briefing clauses={state.briefing} /> : <Loading text="Loading briefing…" />}
                {state?.gmail_connected && <div className="actions"><Button variant="outline" disabled={settings.paused || settings.mode === 'replay' || checking || state.working || disconnected} onClick={() => void checkNow()}>{checking ? 'Checking Gmail…' : 'Check now'}</Button></div>}
                {checkError && <p role="alert">{checkError}</p>}
            </div>
        </section>
        <div className="scout-command"><label htmlFor="scout-command">Ask Scout or give a command</label>
            <input id="scout-command" ref={command} readOnly placeholder="Commands arrive in M15" aria-describedby="command-help" />
            <p id="command-help" className="meta"><span>Commands arrive in M15.</span> Use the controls below for now. <span aria-hidden="true">Ctrl / ⌘ K</span></p>
        </div>
        <div className="dispatch-columns">
            <Section title="Your next decisions" id="decisions">
                {state ? state.decisions.length ? <ol className="decision-list">{state.decisions.map(item => <li key={item.id}>
                    <h3>{item.title}</h3><p>{item.reason}</p>
                    {item.deadline && <DeadlineDisplay record={item.deadline} now={settings.clock} />}
                    <Link to={item.href}>{item.action}</Link>
                </li>)}</ol> : <p>No decisions in the saved snapshot.</p> : <p>{disconnected ? 'Decisions are unavailable until the service reconnects.' : 'Loading decisions…'}</p>}
                <Link ref={work} className="dispatch-footer" to="/work">Open all work</Link>
            </Section>
            <Section title="My latest work" id="latest-work">
                <p className="meta">Recorded runs · most recent first</p>
                {runs.error ? <Failure text="Run ledger could not be loaded." retry={runs.reload} /> : !runs.value ? <Loading text="Loading runs…" /> : !runs.value.length ? <p>No runs recorded.</p> : <ol className="work-log">{runs.value.slice(0, 5).map(run => <li key={run.id}>
                    <p><Link to={`/settings?run=${run.id}#runs`}>{label(run.kind)} · {label(run.status)}</Link></p>
                    <p className="meta"><time dateTime={run.finished_at || run.started_at}>{date(run.finished_at || run.started_at)}</time>{run.status === 'running' && run.stage ? ` · ${label(run.stage)}` : ''}</p>
                </li>)}</ol>}
                <Link className="dispatch-footer" to="/settings#runs">View activity</Link>
            </Section>
        </div>
    </div>;
}
