import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { useDesk } from '../App';
import { request } from '../lib/api';
import { date, label } from '../lib/format';
import type { Run, Settings } from '../types';
import { Button } from '../components/ui/button';
import { Failure, Loading, PauseControl, Section, StatusBadge } from '../components/shared';
export function PayloadPolicySummary({ settings }: {
    settings: Settings;
}) {
    return <Section title="Payload policy — read-only"><dl>{[
            ['Private payloads to cloud models', settings.payload_policy.private_payloads],
            ['Approved private-field allowlist', settings.payload_policy.allowlist.join(', ') || 'Empty'],
            ['Synthetic/public payloads', 'Subject to policy; live transport disabled in this build'],
            ['Current model execution', settings.execution], ['External network services', 'Disabled in this build'],
            ['Gmail', 'Not connected'], ['Notifications', 'Not implemented in this build'],
        ].map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl></Section>;
}
export function DataPaths({ settings }: {
    settings: Settings;
}) {
    return <Section title="Data paths"><dl>{Object.entries({ database: 'Database', import_folder: 'Import folder', evidence_registry: 'Evidence registry', pack_output_folder: 'Pack output folder', cache: 'Cache and temporary files', source_provenance: 'Source provenance' }).map(([key, value]) => <div key={key}><dt>{value}</dt><dd className="path">{settings.paths[key]}</dd></div>)}</dl></Section>;
}
export function ImportControl({ runs, refreshRuns }: {
    runs?: Run[];
    refreshRuns: () => Promise<void>;
}) {
    const { settings, refresh } = useDesk();
    const [starting, setStarting] = useState(false);
    const [runId, setRunId] = useState<number>();
    const [error, setError] = useState('');
    const observed = runs?.find(r => r.id === runId);
    const current = runs?.find(r => r.kind === 'import' && r.status === 'running');
    const active = starting || !!current;
    useEffect(() => { if (observed && observed.status !== 'running')
        void refresh(); }, [observed?.status, refresh]);
    async function start() { setStarting(true); setError(''); try {
        const r = await request<{
            run_id: number;
        }>('/import', settings.csrf_token, {});
        window.dispatchEvent(new Event('inbound-work-started'));
        setRunId(r.run_id);
        await refreshRuns();
    }
    catch (e) {
        setError(e instanceof Error ? e.message : 'Import could not be started.');
    }
    finally {
        setStarting(false);
    } }
    return <Section title="Import messages" id="import"><label>Source format:<select value={settings.source_format || 'export'} disabled><option value="export">Export text</option><option value="eml">EML folder</option></select></label><p className="meta">Source format is configured locally.</p><p>Import folder: <span className="path">{settings.paths.import_folder}</span></p><p>Source provenance: {settings.paths.source_provenance}</p><Button disabled={settings.mode === 'replay' || settings.paused || active} onClick={() => void start()}>Import messages</Button>{settings.mode === 'replay' ? <p>Imports are available in local mode.</p> : settings.paused ? <p>Import blocked while paused. Resume work to import messages.</p> : null}{current && <p role="status">Import running · {current.stage || 'Starting'} · <Link to={`/settings?run=${current.id}#runs`}>View run</Link></p>}{observed?.status === 'completed' && <p role="status">Imported {observed.counts.imported || 0} new messages · {observed.counts.unchanged || 0} already present · {observed.counts.rejected || 0} rejected</p>}{observed && ['failed', 'blocked', 'paused'].includes(observed.status) && <p role="alert">Latest import failed. Showing the last successful snapshot. <Link to={`/settings?run=${observed.id}#runs`}>View run</Link></p>}{error && <p role="alert">{error}</p>}</Section>;
}
export function RunLedger({ runs, error, refresh }: {
    runs?: Run[];
    error: boolean;
    refresh: () => Promise<void>;
}) {
    const [params, setParams] = useSearchParams();
    const kind = params.get('type') || '';
    const result = params.get('result') || '';
    const selected = params.get('run');
    function filter(key: string, value: string) { setParams(p => { const next = new URLSearchParams(p); value ? next.set(key, value) : next.delete(key); return next; }, { replace: true }); }
    return <Section title="Run ledger" id="runs"><div className="filters"><label>Run type:<select value={kind} onChange={e => filter('type', e.target.value)}><option value="">All types</option>{['Import', 'Triage', 'Extraction', 'Pack', 'Digest', 'Evaluation'].map(t => <option key={t} value={{ Extraction: 'extract', Evaluation: 'eval' }[t] || t.toLowerCase()}>{t}</option>)}</select></label><label>Result:<select value={result} onChange={e => filter('result', e.target.value)}><option value="">All results</option>{['Running', 'Completed', 'Paused', 'Blocked', 'Failed'].map(t => <option key={t} value={t.toLowerCase()}>{t}</option>)}</select></label><Button variant="outline" onClick={() => setParams({})}>Clear filters</Button></div>{error ? <Failure text="Run ledger could not be loaded. Retry." retry={() => void refresh()}/> : !runs ? <Loading text="Loading runs…"/> : !runs.length ? <p>No runs recorded.</p> : <div className="responsive-table"><table><caption>Runs, most recent first</caption><thead><tr>{['Started', 'Type', 'Result', 'Counts', 'Duration', 'Model calls', 'Replay/cache hits', 'Details'].map(t => <th key={t} scope="col">{t}</th>)}</tr></thead><tbody>{runs.filter(r => (!kind || r.kind === kind) && (!result || r.status === result)).map(r => <tr key={r.id}><td data-label="Started">{date(r.started_at)}</td><td data-label="Type">{label(r.kind)}</td><td data-label="Result"><span className={['failed', 'blocked'].includes(r.status) ? 'past' : ''}>{label(r.status)}</span></td><td data-label="Counts">{Object.entries(r.counts).map(([k, v]) => <p key={k}>{label(k)}: {v}</p>)}</td><td data-label="Duration">{r.duration_seconds == null ? 'In progress' : `${r.duration_seconds.toFixed(2)} s`}</td><td data-label="Model calls">{r.model_calls}</td><td data-label="Replay/cache hits">{r.cache_hits}</td><td data-label="Details"><details open={String(r.id) === selected}><summary>Details · Run {r.id}</summary><p>Run ID: {r.id} · {r.mode}</p><p>Source type: {r.source_type || 'Not recorded'}</p><p>Started {date(r.started_at)} · Finished {date(r.finished_at)}</p><p>Current / last stage: {r.stage || 'Not recorded'}</p><p>Provider execution type: {r.execution}</p><p>Opportunity: {r.opportunity_id || 'Not recorded'} · Revision: {r.revision_id || 'Not recorded'} · Pack: {r.pack_id || 'Not recorded'}</p><p>Error: {r.error || 'None'}</p><p>Retry history: {r.retry_history.length ? r.retry_history.join(', ') : 'None'}</p></details></td></tr>)}</tbody></table></div>}</Section>;
}
export default function SettingsPage() {
    const { settings, savePause } = useDesk();
    const [runs, setRuns] = useState<Run[]>();
    const [error, setError] = useState(false);
    const refreshRuns = useCallback(async () => { try {
        setRuns(await request<Run[]>('/runs'));
        setError(false);
    }
    catch {
        setError(true);
    } }, []);
    const active = runs?.some(r => r.status === 'running');
    useEffect(() => { void refreshRuns(); }, [refreshRuns]);
    useEffect(() => { if (!active)
        return; const timer = window.setInterval(() => { if (!document.hidden)
        void refreshRuns(); }, 5000); const visible = () => { if (!document.hidden)
        void refreshRuns(); }; document.addEventListener('visibilitychange', visible); return () => { clearInterval(timer); document.removeEventListener('visibilitychange', visible); }; }, [active, refreshRuns]);
    const b = settings.budgets;
    return <><a href="#runs">Jump to runs</a><div className="settings-grid"><div><Section title="Pause"><PauseControl paused={settings.paused} replay={settings.mode === 'replay'} save={savePause} active={active}/></Section><Section title="Budgets"><p>Offline mode — live model calls are disabled.</p><p>Changing a budget does not enable a provider.</p><dl>{[
            ['Daily model call limit', b.daily_call_limit], ['Daily model spend limit', `${b.daily_spend_limit} ${b.currency}`], ['Calls used today', b.calls_used_today], ['Spend used today', b.spend_used_today === null ? 'Not recorded' : `${b.spend_used_today} ${b.currency}`], ['Budget resets at', b.resets_at ? `${date(b.resets_at)} · Dubai` : 'Not recorded · Asia/Dubai'],
        ].map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><p>Model comparison: Not run</p><StatusBadge value="Not run"/></Section><PayloadPolicySummary settings={settings}/><DataPaths settings={settings}/><ImportControl runs={runs} refreshRuns={refreshRuns}/></div><RunLedger runs={runs} error={error} refresh={refreshRuns}/></div></>;
}
